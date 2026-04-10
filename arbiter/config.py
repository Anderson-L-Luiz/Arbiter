"""Arbiter configuration."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional


def _find_claude() -> str:
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    return "claude"


def _find_gemini() -> str:
    for name in ("gemini", "gemini.cmd", "gemini.exe"):
        p = shutil.which(name)
        if p:
            return p
    return "gemini"


def _resolve_node_invoker(cli_path: str) -> Optional[List[str]]:
    """Bypass the Windows .cmd shim by invoking `node bundle/gemini.js` directly.

    Same trick used in Dunamisv2/dunamis/gemini_cli.py — the .cmd shim causes
    cmd.exe to re-parse argv and mangle quoted @\"path\" attachment tokens."""
    node = shutil.which("node")
    if not node:
        return None
    cli_dir = os.path.dirname(os.path.abspath(cli_path))
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


@dataclass
class ArbiterConfig:
    project_dir: str
    task: str
    rounds: int = 5
    stop_score: float = 9.0  # stop when Gemini's score >= this
    claude_path: str = field(default_factory=_find_claude)
    claude_model: str = "sonnet"
    gemini_path: str = field(default_factory=_find_gemini)
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str = "gemini-2.5-flash"
    screenshots_subdir: str = "screenshots"
    per_round_timeout: int = 60 * 30  # 30 min per side

    @property
    def screenshots_dir(self) -> str:
        return os.path.join(self.project_dir, self.screenshots_subdir)

    def gemini_invoker(self) -> List[str]:
        inv = _resolve_node_invoker(self.gemini_path)
        return inv if inv else [self.gemini_path]
