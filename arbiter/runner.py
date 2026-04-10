"""Subprocess orchestration for Claude Code (builder) and Gemini CLI (judge)."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

from .artifacts import ScreenshotTracker
from .config import ArbiterConfig
from .prompts import (
    BUILDER_SYSTEM,
    JUDGE_SYSTEM,
    builder_prompt,
    judge_prompt,
    parse_score,
)


LineSink = Callable[[str], None]


async def _stream_process(
    argv: List[str],
    cwd: str,
    sink: LineSink,
    timeout: int,
    stdin_data: Optional[bytes] = None,
) -> int:
    """Run a subprocess, stream combined stdout+stderr line-by-line to `sink`.

    Returns exit code. Raises asyncio.TimeoutError on timeout (process killed).
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    if stdin_data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def pump() -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            try:
                sink(chunk.decode("utf-8", errors="replace").rstrip("\r\n"))
            except Exception:
                pass

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise

    return proc.returncode if proc.returncode is not None else -1


@dataclass
class RoundResult:
    index: int
    builder_output: str
    verdict: str
    score: Optional[float]
    screenshots: List[str]


class ArbiterRunner:
    """Drives the builder/judge loop."""

    def __init__(
        self,
        config: ArbiterConfig,
        on_claude_line: LineSink,
        on_gemini_line: LineSink,
        on_status: Callable[[str], None],
    ):
        self.cfg = config
        self._on_claude = on_claude_line
        self._on_gemini = on_gemini_line
        self._on_status = on_status
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self) -> List[RoundResult]:
        os.makedirs(self.cfg.project_dir, exist_ok=True)
        tracker = ScreenshotTracker(self.cfg.screenshots_dir)
        results: List[RoundResult] = []
        last_verdict: Optional[str] = None

        for i in range(1, self.cfg.rounds + 1):
            if self._cancelled:
                self._on_status(f"Cancelled before round {i}")
                break

            self._on_status(f"Round {i}/{self.cfg.rounds} — Claude building")
            tracker.snapshot()

            # ---- Builder: Claude Code ----
            bp = builder_prompt(self.cfg.task, i, self.cfg.rounds, last_verdict)
            builder_buf: List[str] = []

            def claude_sink(line: str, _buf=builder_buf) -> None:
                _buf.append(line)
                self._on_claude(line)

            self._on_claude(f"─── Round {i}/{self.cfg.rounds} ───")
            claude_argv = [
                self.cfg.claude_path,
                "--dangerously-skip-permissions",
                "--model", self.cfg.claude_model,
                "--append-system-prompt", BUILDER_SYSTEM,
                "-p", bp,
            ]
            try:
                rc = await _stream_process(
                    claude_argv, self.cfg.project_dir, claude_sink,
                    timeout=self.cfg.per_round_timeout,
                )
            except asyncio.TimeoutError:
                self._on_claude("[claude timed out]")
                rc = -1
            if rc != 0:
                self._on_claude(f"[claude exited rc={rc}]")

            builder_output = "\n".join(builder_buf)

            # ---- Judge: Gemini CLI ----
            if self._cancelled:
                break
            shots = tracker.new_files()
            self._on_status(
                f"Round {i}/{self.cfg.rounds} — Gemini judging ({len(shots)} screenshot(s))"
            )
            self._on_gemini(f"─── Round {i}/{self.cfg.rounds} — {len(shots)} screenshot(s) ───")

            jp = judge_prompt(self.cfg.task, i, self.cfg.rounds, builder_output, shots)
            full_prompt = JUDGE_SYSTEM + "\n\n" + jp

            judge_buf: List[str] = []

            def gemini_sink(line: str, _buf=judge_buf) -> None:
                _buf.append(line)
                self._on_gemini(line)

            invoker = self.cfg.gemini_invoker()
            gemini_argv = list(invoker) + ["-m", self.cfg.gemini_model]
            # Add parent dirs of screenshots as workspace
            seen_dirs: List[str] = []
            for s in shots:
                d = os.path.dirname(os.path.abspath(s))
                if d and d not in seen_dirs:
                    seen_dirs.append(d)
            for d in seen_dirs:
                gemini_argv += ["--include-directories", d]
            gemini_argv += ["-p", full_prompt]

            try:
                rc = await _stream_process(
                    gemini_argv, self.cfg.project_dir, gemini_sink,
                    timeout=self.cfg.per_round_timeout,
                )
            except asyncio.TimeoutError:
                self._on_gemini("[gemini timed out]")
                rc = -1
            if rc != 0:
                self._on_gemini(f"[gemini exited rc={rc}]")

            verdict = "\n".join(judge_buf)

            # Retry with fallback model on capacity / rate-limit errors.
            capacity_markers = (
                "MODEL_CAPACITY_EXHAUSTED",
                "No capacity available",
                "rateLimitExceeded",
                "RESOURCE_EXHAUSTED",
                "status: 429",
            )
            if (
                self.cfg.gemini_fallback_model
                and self.cfg.gemini_fallback_model != self.cfg.gemini_model
                and any(m in verdict for m in capacity_markers)
            ):
                fallback = self.cfg.gemini_fallback_model
                self._on_gemini(f"[retrying with fallback model: {fallback}]")
                judge_buf.clear()
                retry_argv = list(invoker) + ["-m", fallback]
                for d in seen_dirs:
                    retry_argv += ["--include-directories", d]
                retry_argv += ["-p", full_prompt]
                try:
                    rc = await _stream_process(
                        retry_argv, self.cfg.project_dir, gemini_sink,
                        timeout=self.cfg.per_round_timeout,
                    )
                except asyncio.TimeoutError:
                    self._on_gemini("[gemini fallback timed out]")
                    rc = -1
                if rc != 0:
                    self._on_gemini(f"[gemini fallback exited rc={rc}]")
                verdict = "\n".join(judge_buf)
            score = parse_score(verdict)
            last_verdict = verdict

            results.append(RoundResult(
                index=i, builder_output=builder_output, verdict=verdict,
                score=score, screenshots=shots,
            ))

            if score is not None and score >= self.cfg.stop_score:
                self._on_status(f"Stop — score {score} >= {self.cfg.stop_score}")
                break

        self._on_status("Done")
        return results
