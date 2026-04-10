"""Agent abstraction — wraps Claude Code and Gemini CLI as async message-passing actors."""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, List, Optional

LineSink = Callable[[str], None]


@dataclass
class AgentMessage:
    """A single message sent to or received from an agent."""
    role: str  # "user" | "assistant" | "system"
    text: str
    round_index: Optional[int] = None


class BaseAgent:
    """Async agent that wraps a CLI subprocess."""

    name: str = "agent"
    icon: str = "●"

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.history: List[AgentMessage] = []
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._cancelled = False

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass

    def _build_argv(self, prompt: str, system: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    async def send(
        self,
        prompt: str,
        sink: LineSink,
        system: Optional[str] = None,
        timeout: int = 1800,
    ) -> str:
        """Send a message, stream output line-by-line to sink, return full text."""
        self._cancelled = False
        self.history.append(AgentMessage(role="user", text=prompt))
        argv = self._build_argv(prompt, system)

        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.project_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        lines: List[str] = []
        assert self._proc.stdout is not None

        async def pump() -> None:
            while True:
                chunk = await self._proc.stdout.readline()  # type: ignore
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                lines.append(line)
                try:
                    sink(line)
                except Exception:
                    pass

        try:
            await asyncio.wait_for(
                asyncio.gather(pump(), self._proc.wait()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.cancel()
            sink(f"[{self.name} timed out after {timeout}s]")

        rc = self._proc.returncode if self._proc.returncode is not None else -1
        if rc != 0 and not self._cancelled:
            sink(f"[{self.name} exited rc={rc}]")

        self._proc = None
        full = "\n".join(lines)
        self.history.append(AgentMessage(role="assistant", text=full))
        return full


class ClaudeAgent(BaseAgent):
    name = "claude"
    icon = "🛠"

    def __init__(
        self,
        project_dir: str,
        model: str = "sonnet",
        claude_path: Optional[str] = None,
    ):
        super().__init__(project_dir)
        self.model = model
        self.claude_path = claude_path or self._find_claude()

    @staticmethod
    def _find_claude() -> str:
        for name in ("claude", "claude.cmd", "claude.exe"):
            p = shutil.which(name)
            if p:
                return p
        return "claude"

    def _build_argv(self, prompt: str, system: Optional[str] = None) -> List[str]:
        argv = [
            self.claude_path,
            "--dangerously-skip-permissions",
            "--model", self.model,
        ]
        if system:
            argv += ["--append-system-prompt", system]
        argv += ["-p", prompt]
        return argv


class GeminiAgent(BaseAgent):
    name = "gemini"
    icon = "⚖"

    def __init__(
        self,
        project_dir: str,
        model: str = "gemini-2.5-flash",
        gemini_path: Optional[str] = None,
    ):
        super().__init__(project_dir)
        self.model = model
        self.gemini_path = gemini_path or self._find_gemini()
        self._invoker: Optional[List[str]] = self._resolve_invoker()

    @staticmethod
    def _find_gemini() -> str:
        for name in ("gemini", "gemini.cmd", "gemini.exe"):
            p = shutil.which(name)
            if p:
                return p
        return "gemini"

    def _resolve_invoker(self) -> Optional[List[str]]:
        """Bypass the Windows .cmd shim by invoking node + bundle/gemini.js directly."""
        node = shutil.which("node")
        if not node:
            return None
        resolved = shutil.which(self.gemini_path) or self.gemini_path
        cli_dir = os.path.dirname(os.path.abspath(resolved))
        candidates = [
            os.path.join(cli_dir, "node_modules", "@google", "gemini-cli", "bundle", "gemini.js"),
            os.path.join(os.path.dirname(cli_dir), "npm", "node_modules", "@google", "gemini-cli", "bundle", "gemini.js"),
        ]
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(
                os.path.join(appdata, "npm", "node_modules", "@google", "gemini-cli", "bundle", "gemini.js")
            )
        for cand in candidates:
            if os.path.exists(cand):
                return [node, "--no-warnings=DEP0040", cand]
        return None

    def _base_cmd(self) -> List[str]:
        if self._invoker:
            return list(self._invoker)
        return [self.gemini_path]

    def _build_argv(self, prompt: str, system: Optional[str] = None) -> List[str]:
        cmd = self._base_cmd() + ["-m", self.model]
        full_prompt = prompt
        if system:
            full_prompt = system + "\n\n" + prompt
        cmd += ["-p", full_prompt]
        return cmd

    def _build_argv_with_files(
        self, prompt: str, files: List[str], system: Optional[str] = None
    ) -> List[str]:
        """Build command with @file references and --include-directories."""
        cmd = self._base_cmd() + ["-m", self.model]
        # Add parent dirs of files as workspace
        seen_dirs: List[str] = []
        file_refs: List[str] = []
        for f in files:
            if not os.path.isabs(f):
                f = os.path.abspath(f)
            if not os.path.exists(f):
                continue
            d = os.path.dirname(f)
            if d and d not in seen_dirs:
                seen_dirs.append(d)
            file_refs.append(f'@"{f}"')

        for d in seen_dirs:
            cmd += ["--include-directories", d]

        full_prompt = prompt
        if system:
            full_prompt = system + "\n\n" + prompt
        if file_refs:
            full_prompt += "\n\n" + " ".join(file_refs)
        cmd += ["-p", full_prompt]
        return cmd

    async def send_with_files(
        self,
        prompt: str,
        files: List[str],
        sink: LineSink,
        system: Optional[str] = None,
        timeout: int = 1800,
    ) -> str:
        """Send a message with file attachments (screenshots etc.)."""
        self._cancelled = False
        self.history.append(AgentMessage(role="user", text=prompt))
        argv = self._build_argv_with_files(prompt, files, system)

        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.project_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        lines: List[str] = []
        assert self._proc.stdout is not None

        async def pump() -> None:
            while True:
                chunk = await self._proc.stdout.readline()  # type: ignore
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                lines.append(line)
                try:
                    sink(line)
                except Exception:
                    pass

        try:
            await asyncio.wait_for(
                asyncio.gather(pump(), self._proc.wait()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.cancel()
            sink(f"[{self.name} timed out after {timeout}s]")

        rc = self._proc.returncode if self._proc.returncode is not None else -1
        if rc != 0 and not self._cancelled:
            sink(f"[{self.name} exited rc={rc}]")

        self._proc = None
        full = "\n".join(lines)
        self.history.append(AgentMessage(role="assistant", text=full))
        return full
