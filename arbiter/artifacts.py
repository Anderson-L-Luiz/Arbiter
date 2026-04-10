"""Track new screenshots produced in the project during each round."""
from __future__ import annotations

import os
from typing import Dict, List


class ScreenshotTracker:
    """Tracks PNG/JPG files under a watched directory by mtime.

    `snapshot()` at round start, `new_files()` at round end to get only
    the files created/modified during the round.
    """

    def __init__(self, watched_dir: str):
        self.watched_dir = watched_dir
        self._baseline: Dict[str, float] = {}

    def _walk(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not os.path.isdir(self.watched_dir):
            return out
        for root, _, files in os.walk(self.watched_dir):
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    p = os.path.join(root, f)
                    try:
                        out[p] = os.path.getmtime(p)
                    except OSError:
                        pass
        return out

    def snapshot(self) -> None:
        os.makedirs(self.watched_dir, exist_ok=True)
        self._baseline = self._walk()

    def new_files(self) -> List[str]:
        current = self._walk()
        new: List[str] = []
        for path, mtime in current.items():
            base = self._baseline.get(path)
            if base is None or mtime > base:
                new.append(path)
        new.sort(key=lambda p: current[p])
        return new
