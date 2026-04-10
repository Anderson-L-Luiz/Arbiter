"""Prompt builders for the builder and the judge."""
from __future__ import annotations

import os
from typing import List, Optional


BUILDER_SYSTEM = (
    "You are the BUILDER in an iterative build-and-judge loop. "
    "A separate Gemini judge will evaluate your work after each round and "
    "return a structured critique. Your job is to make concrete, shippable "
    "changes to the project. Prefer running code, clear UX, and visible UI "
    "improvements. When UI is involved, produce screenshots into "
    "./screenshots/round_<N>_<label>.png so the judge can see them."
)


def builder_prompt(task: str, round_index: int, total_rounds: int,
                   previous_verdict: Optional[str]) -> str:
    parts: List[str] = []
    parts.append(f"# Round {round_index}/{total_rounds}")
    parts.append("")
    parts.append("## Task")
    parts.append(task.strip())
    parts.append("")
    if previous_verdict:
        parts.append("## Gemini judge's previous verdict — address every gap below")
        parts.append(previous_verdict.strip())
        parts.append("")
    parts.append("## Instructions")
    parts.append("- Work autonomously. Do not ask questions.")
    parts.append("- Make the highest-impact change this round.")
    parts.append("- If the target has a UI, save screenshots of the current state into ./screenshots/ as PNGs.")
    parts.append("- End your turn with a short CHANGELOG of what you changed this round.")
    return "\n".join(parts)


JUDGE_SYSTEM = (
    "You are the JUDGE in an iterative build-and-judge loop. A Claude Code "
    "builder just finished a round of work on a project. Evaluate the current "
    "state with a focus on UX and UI quality, usability, visual hierarchy, "
    "accessibility, and whether the task was actually advanced. Be specific "
    "and actionable — the builder will read your critique and fix it next round."
)


def judge_prompt(task: str, round_index: int, total_rounds: int,
                 builder_summary: str, screenshots: List[str]) -> str:
    parts: List[str] = []
    parts.append(f"# Round {round_index}/{total_rounds} — Evaluation")
    parts.append("")
    parts.append("## Original task")
    parts.append(task.strip())
    parts.append("")
    parts.append("## Builder's report from this round")
    parts.append((builder_summary or "(no report)").strip())
    parts.append("")
    if screenshots:
        parts.append("## Screenshots from this round")
        for p in screenshots:
            # gemini-cli @file syntax
            parts.append(f'@"{os.path.abspath(p)}"')
        parts.append("")
    parts.append("## Respond in this exact format")
    parts.append("SCORE: <number 0-10, one decimal>")
    parts.append("VERDICT: <one sentence>")
    parts.append("GAPS:")
    parts.append("- <specific, actionable gap #1>")
    parts.append("- <specific, actionable gap #2>")
    parts.append("- ...")
    parts.append("NEXT_ROUND_FOCUS: <one sentence telling the builder what to do next>")
    return "\n".join(parts)


def parse_score(verdict_text: str) -> Optional[float]:
    for line in verdict_text.splitlines():
        s = line.strip()
        if s.upper().startswith("SCORE:"):
            rest = s.split(":", 1)[1].strip()
            # Take the first number-looking token
            num = ""
            for ch in rest:
                if ch.isdigit() or ch == ".":
                    num += ch
                elif num:
                    break
            try:
                return float(num) if num else None
            except ValueError:
                return None
    return None
