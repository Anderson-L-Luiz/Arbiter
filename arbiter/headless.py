"""Headless driver — same loop as the TUI but writes to log files.

Usage:
    python -m arbiter.headless <project_dir> --task-file <path> [--rounds N] [--stop-score F]
    python -m arbiter.headless <project_dir> -t "task text" [--rounds N] [--stop-score F]

Writes _arbiter_logs/{claude,gemini,status}.log under the project dir.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .config import ArbiterConfig
from .runner import ArbiterRunner


async def _run() -> int:
    ap = argparse.ArgumentParser("arbiter-headless")
    ap.add_argument("project_dir", help="Directory Claude Code will work in")
    task_group = ap.add_mutually_exclusive_group(required=True)
    task_group.add_argument("-t", "--task", help="Task description (inline)")
    task_group.add_argument("--task-file", help="Path to file containing the task description")
    ap.add_argument("-n", "--rounds", type=int, default=3)
    ap.add_argument("--stop-score", type=float, default=9.0)
    args = ap.parse_args()

    project = os.path.abspath(args.project_dir)
    if args.task_file:
        with open(args.task_file, "r", encoding="utf-8") as f:
            task = f.read().strip()
    else:
        task = args.task
    rounds = args.rounds
    stop_score = args.stop_score

    os.makedirs(project, exist_ok=True)
    log_dir = os.path.join(project, "_arbiter_logs")
    os.makedirs(log_dir, exist_ok=True)

    claude_f = open(os.path.join(log_dir, "claude.log"), "a", encoding="utf-8", buffering=1)
    gemini_f = open(os.path.join(log_dir, "gemini.log"), "a", encoding="utf-8", buffering=1)
    status_f = open(os.path.join(log_dir, "status.log"), "a", encoding="utf-8", buffering=1)

    def on_claude(line: str) -> None:
        claude_f.write(line + "\n")

    def on_gemini(line: str) -> None:
        gemini_f.write(line + "\n")

    def on_status(text: str) -> None:
        status_f.write(text + "\n")
        print(f"[status] {text}", flush=True)

    cfg = ArbiterConfig(
        project_dir=project,
        task=task,
        rounds=rounds,
        stop_score=stop_score,
    )
    runner = ArbiterRunner(cfg, on_claude, on_gemini, on_status)
    results = await runner.run()

    summary_path = os.path.join(log_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Task: {task}\n")
        f.write(f"Rounds run: {len(results)}\n\n")
        for r in results:
            f.write(f"=== Round {r.index} — score={r.score} ===\n")
            f.write(f"  screenshots: {len(r.screenshots)}\n")
            for s in r.screenshots:
                f.write(f"    - {s}\n")
            f.write("  verdict:\n")
            for line in r.verdict.splitlines()[:40]:
                f.write(f"    {line}\n")
            f.write("\n")

    print(f"[done] rounds={len(results)}  summary={summary_path}")
    claude_f.close()
    gemini_f.close()
    status_f.close()
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
