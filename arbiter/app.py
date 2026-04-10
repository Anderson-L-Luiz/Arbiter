"""Textual split-pane TUI: Gemini (judge) left | Claude Code (builder) right."""
from __future__ import annotations

import argparse
import asyncio
import os
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from .config import ArbiterConfig
from .runner import ArbiterRunner


class ArbiterApp(App):
    TITLE = "Arbiter — Claude × Gemini"
    CSS = """
    Screen { layout: vertical; }
    #status { height: 3; padding: 0 1; background: $boost; color: $text; }
    #panes { height: 1fr; }
    .pane { width: 1fr; border: round $primary; }
    #gemini_pane { border-title-color: $warning; }
    #claude_pane { border-title-color: $success; }
    RichLog { height: 1fr; }
    #round_bar { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "cancel_run", "Cancel run"),
        Binding("s", "start_run", "Start"),
    ]

    def __init__(self, config: ArbiterConfig):
        super().__init__()
        self.cfg = config
        self.runner: Optional[ArbiterRunner] = None
        self._task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text("idle"), id="status")
        yield Static("", id="round_bar")
        with Horizontal(id="panes"):
            # LEFT: Gemini judge
            with Vertical(classes="pane", id="gemini_pane") as gp:
                gp.border_title = "⚖  Gemini — JUDGE"
                yield RichLog(id="gemini_log", highlight=False, markup=False, wrap=True)
            # RIGHT: Claude Code builder
            with Vertical(classes="pane", id="claude_pane") as cp:
                cp.border_title = "🛠  Claude Code — BUILDER"
                yield RichLog(id="claude_log", highlight=False, markup=False, wrap=True)
        yield Footer()

    def _status_text(self, state: str) -> str:
        task_preview = self.cfg.task[:100] + ("…" if len(self.cfg.task) > 100 else "")
        return (
            f" Project: {os.path.basename(self.cfg.project_dir)}   "
            f"Rounds: {self.cfg.rounds}   "
            f"Stop@: {self.cfg.stop_score}   "
            f"Model: {self.cfg.gemini_model}\n"
            f" State: {state}\n"
            f" Task: {task_preview}"
        )

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#status", Static).update(self._status_text(text))
        except Exception:
            pass

    def _set_round(self, text: str) -> None:
        try:
            self.query_one("#round_bar", Static).update(f" {text}")
        except Exception:
            pass

    def on_mount(self) -> None:
        gl = self.query_one("#gemini_log", RichLog)
        cl = self.query_one("#claude_log", RichLog)
        gl.write("⚖  Gemini judge — waiting for builder to finish first round…")
        gl.write("")
        cl.write("🛠  Claude Code builder — starting…")
        cl.write(f"   Task: {self.cfg.task[:200]}")
        cl.write(f"   Dir:  {self.cfg.project_dir}")
        cl.write("")
        # Auto-start
        self.call_after_refresh(self.action_start_run)

    def action_start_run(self) -> None:
        if self._task and not self._task.done():
            return
        cl = self.query_one("#claude_log", RichLog)
        gl = self.query_one("#gemini_log", RichLog)

        def on_claude(line: str) -> None:
            self.call_from_thread(cl.write, line)

        def on_gemini(line: str) -> None:
            self.call_from_thread(gl.write, line)

        def on_status(text: str) -> None:
            self.call_from_thread(self._set_status, text)
            self.call_from_thread(self._set_round, text)

        self.runner = ArbiterRunner(self.cfg, on_claude, on_gemini, on_status)
        self._task = asyncio.create_task(self._run_wrapper())

    async def _run_wrapper(self) -> None:
        assert self.runner is not None
        try:
            results = await self.runner.run()
            # Show final score summary
            summary_parts = []
            for r in results:
                s = r.score if r.score is not None else "?"
                summary_parts.append(f"R{r.index}={s}")
            final = " | ".join(summary_parts)
            self.call_from_thread(
                self._set_status, f"DONE — Scores: {final}"
            )
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(
                self.query_one("#claude_log", RichLog).write,
                f"[error] {e!r}",
            )
            self.call_from_thread(self._set_status, f"error: {e!r}")

    def action_cancel_run(self) -> None:
        if self.runner:
            self.runner.cancel()
            self._set_status("cancelling…")


def main() -> None:
    ap = argparse.ArgumentParser("arbiter")
    task_group = ap.add_mutually_exclusive_group(required=True)
    task_group.add_argument("-t", "--task", help="Task description (inline)")
    task_group.add_argument("--task-file", help="Path to file with the task description")
    ap.add_argument("project_dir", help="Directory Claude Code will operate in")
    ap.add_argument("-n", "--rounds", type=int, default=5)
    ap.add_argument("--stop-score", type=float, default=9.0)
    ap.add_argument("--claude-model", default="sonnet")
    ap.add_argument("--gemini-model", default="gemini-2.5-flash")
    args = ap.parse_args()

    if args.task_file:
        with open(args.task_file, "r", encoding="utf-8") as f:
            task = f.read().strip()
    else:
        task = args.task

    cfg = ArbiterConfig(
        project_dir=os.path.abspath(args.project_dir),
        task=task,
        rounds=args.rounds,
        stop_score=args.stop_score,
        claude_model=args.claude_model,
        gemini_model=args.gemini_model,
    )
    ArbiterApp(cfg).run()


if __name__ == "__main__":
    main()
