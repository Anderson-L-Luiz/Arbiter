"""Arbiter v2 — three-pane interactive TUI: Gemini | You | Claude."""
from __future__ import annotations

import argparse
import asyncio
import os
from typing import Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
)

from .agents import ClaudeAgent, GeminiAgent
from .artifacts import ScreenshotTracker
from .commands import (
    Action,
    Command,
    HELP_TEXT,
    Target,
    parse,
)
from .prompts import (
    BUILDER_SYSTEM,
    JUDGE_SYSTEM,
    builder_prompt,
    judge_prompt,
    parse_score,
)


# ── Project picker screen ────────────────────────────────────────


class ProjectPicker(Screen):
    """Full-screen directory picker shown at startup if no project_dir given."""

    CSS = """
    ProjectPicker { layout: vertical; }
    #picker_header { height: 3; padding: 1; background: $boost; }
    #dir_input { margin: 1 2; }
    DirectoryTree { height: 1fr; margin: 0 2; }
    #picker_hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def __init__(self, start_path: str = "~"):
        super().__init__()
        self.start_path = os.path.expanduser(start_path)
        self.chosen: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Static(
            " ARBITER — Select project folder\n"
            " Navigate and press Enter on a directory, or type a path below.",
            id="picker_header",
        )
        yield Input(
            placeholder="Type a path and press Enter (e.g. C:\\Projects\\my-app)",
            id="dir_input",
        )
        yield DirectoryTree(self.start_path, id="dir_tree")
        yield Static(
            " Enter=select folder  |  Ctrl+C=quit",
            id="picker_hint",
        )

    @on(Input.Submitted, "#dir_input")
    def on_input_submit(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        if path and os.path.isdir(path):
            self.chosen = os.path.abspath(path)
            self.dismiss(self.chosen)
        elif path:
            os.makedirs(path, exist_ok=True)
            self.chosen = os.path.abspath(path)
            self.dismiss(self.chosen)

    @on(DirectoryTree.DirectorySelected, "#dir_tree")
    def on_dir_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        path = str(event.path)
        self.query_one("#dir_input", Input).value = path

    def key_enter(self) -> None:
        inp = self.query_one("#dir_input", Input)
        if inp.value.strip():
            self.on_input_submit(Input.Submitted(inp, inp.value))


# ── Main three-pane app ──────────────────────────────────────────


class ArbiterApp(App):
    TITLE = "Arbiter v2"
    CSS = """
    Screen { layout: vertical; }

    #status_bar {
        height: 2;
        padding: 0 1;
        background: $boost;
        color: $text;
    }

    #panes { height: 1fr; }

    .agent_pane {
        width: 1fr;
        border: round $primary;
    }
    #gemini_pane { border-title-color: $warning; }
    #center_pane {
        width: 1fr;
        border: round $accent;
        border-title-color: $accent;
        min-width: 30;
    }
    #claude_pane { border-title-color: $success; }

    RichLog { height: 1fr; }
    #user_input {
        dock: bottom;
        margin: 0 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("escape", "focus_input", "Focus input", show=False),
    ]

    def __init__(
        self,
        project_dir: Optional[str] = None,
        task: Optional[str] = None,
        claude_model: str = "sonnet",
        gemini_model: str = "gemini-2.5-flash",
    ):
        super().__init__()
        self._initial_project = project_dir
        self._initial_task = task
        self.claude_model = claude_model
        self.gemini_model = gemini_model

        # Set after project is chosen
        self.project_dir: Optional[str] = project_dir
        self.claude: Optional[ClaudeAgent] = None
        self.gemini: Optional[GeminiAgent] = None

        # Loop state
        self._loop_task: Optional[asyncio.Task] = None
        self._loop_paused = False
        self._loop_cancelled = False

    # ── Layout ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status_bar")
        with Horizontal(id="panes"):
            with Vertical(classes="agent_pane", id="gemini_pane") as gp:
                gp.border_title = "⚖  Gemini — JUDGE"
                yield RichLog(id="gemini_log", highlight=False, markup=False, wrap=True)
            with Vertical(id="center_pane") as cp:
                cp.border_title = "💬  You — ARBITER"
                yield RichLog(id="center_log", highlight=False, markup=False, wrap=True)
                yield Input(
                    placeholder="/help for commands — type a message to talk to both agents",
                    id="user_input",
                )
            with Vertical(classes="agent_pane", id="claude_pane") as clp:
                clp.border_title = "🛠  Claude Code — BUILDER"
                yield RichLog(id="claude_log", highlight=False, markup=False, wrap=True)
        yield Footer()

    def _update_status(self, extra: str = "") -> None:
        parts = []
        if self.project_dir:
            parts.append(f"Project: {os.path.basename(self.project_dir)}")
        parts.append(f"Claude: {self.claude_model}")
        parts.append(f"Gemini: {self.gemini_model}")
        if self._loop_task and not self._loop_task.done():
            parts.append("Loop: RUNNING")
        elif self._loop_paused:
            parts.append("Loop: PAUSED")
        if extra:
            parts.append(extra)
        try:
            self.query_one("#status_bar", Static).update(" " + "  |  ".join(parts))
        except Exception:
            pass

    # ── Lifecycle ─────────────────────────────────────────────

    async def on_mount(self) -> None:
        if not self.project_dir:
            # Show project picker
            start = os.path.expanduser("~\\PROJECTS")
            if not os.path.isdir(start):
                start = os.path.expanduser("~")

            def on_pick(result: Optional[str]) -> None:
                if result:
                    self.project_dir = result
                    self._init_agents()
                    self._welcome()
                else:
                    self.exit()

            self.push_screen(ProjectPicker(start), callback=on_pick)
        else:
            self._init_agents()
            self._welcome()

    def _init_agents(self) -> None:
        assert self.project_dir
        os.makedirs(self.project_dir, exist_ok=True)
        self.claude = ClaudeAgent(self.project_dir, model=self.claude_model)
        self.gemini = GeminiAgent(self.project_dir, model=self.gemini_model)
        self._update_status()

    def _welcome(self) -> None:
        cl = self.query_one("#center_log", RichLog)
        cl.write("Welcome to Arbiter v2")
        cl.write(f"Project: {self.project_dir}")
        cl.write("")
        cl.write("Talk to both agents, or use commands:")
        cl.write("  /claude <msg>   → Claude only")
        cl.write("  /gemini <msg>   → Gemini only")
        cl.write("  <msg>           → both agents")
        cl.write("  /loop [N] [score] → auto build→judge loop")
        cl.write("  /stop /pause /resume /status /help")
        cl.write("")
        if self._initial_task:
            cl.write(f"Task loaded: {self._initial_task[:120]}...")
            cl.write("Type /loop to start the auto-iterate loop, or just chat.")
        self.query_one("#user_input", Input).focus()

    def action_focus_input(self) -> None:
        self.query_one("#user_input", Input).focus()

    # ── Log helpers (thread-safe) ─────────────────────────────

    def _log_claude(self, line: str) -> None:
        self.call_from_thread(self.query_one("#claude_log", RichLog).write, line)

    def _log_gemini(self, line: str) -> None:
        self.call_from_thread(self.query_one("#gemini_log", RichLog).write, line)

    def _log_center(self, line: str) -> None:
        self.call_from_thread(self.query_one("#center_log", RichLog).write, line)

    def _log_center_sync(self, line: str) -> None:
        """Use when already on the main thread."""
        self.query_one("#center_log", RichLog).write(line)

    # ── Input handling ────────────────────────────────────────

    @on(Input.Submitted, "#user_input")
    def on_user_submit(self, event: Input.Submitted) -> None:
        raw = event.value
        event.input.value = ""
        if not raw.strip():
            return

        cmd = parse(raw)
        self._handle_command(cmd, raw)

    def _handle_command(self, cmd: Command, raw: str) -> None:
        cl = self.query_one("#center_log", RichLog)

        if cmd.action == Action.QUIT:
            self._stop_everything()
            self.exit()
            return

        if cmd.action == Action.HELP:
            for line in HELP_TEXT.splitlines():
                cl.write(line)
            return

        if cmd.action == Action.STATUS:
            cl.write(f"  Project: {self.project_dir}")
            cl.write(f"  Claude: {'RUNNING' if self.claude and self.claude.is_running else 'idle'}")
            cl.write(f"  Gemini: {'RUNNING' if self.gemini and self.gemini.is_running else 'idle'}")
            cl.write(f"  Loop: {'RUNNING' if self._loop_task and not self._loop_task.done() else 'PAUSED' if self._loop_paused else 'idle'}")
            return

        if cmd.action == Action.CLEAR:
            self.query_one("#claude_log", RichLog).clear()
            self.query_one("#gemini_log", RichLog).clear()
            cl.clear()
            return

        if cmd.action == Action.PROJECT:
            if cmd.text and os.path.isdir(cmd.text):
                self.project_dir = os.path.abspath(cmd.text)
                self._init_agents()
                cl.write(f"Project changed to: {self.project_dir}")
            elif cmd.text:
                os.makedirs(cmd.text, exist_ok=True)
                self.project_dir = os.path.abspath(cmd.text)
                self._init_agents()
                cl.write(f"Created and switched to: {self.project_dir}")
            else:
                cl.write("Usage: /project <path>")
            return

        if cmd.action == Action.LOOP_STOP:
            self._stop_everything()
            cl.write("Stopped.")
            return

        if cmd.action == Action.PAUSE:
            self._loop_paused = True
            cl.write("Paused — will stop after current agent finishes. /resume to continue.")
            self._update_status()
            return

        if cmd.action == Action.RESUME:
            self._loop_paused = False
            cl.write("Resumed.")
            self._update_status()
            return

        if cmd.action == Action.LOOP_START:
            if not self._initial_task and not cmd.text:
                cl.write("No task set. Send a message first, then /loop to iterate on it.")
                return
            task = self._initial_task or cmd.text or ""
            self._start_loop(task, cmd.rounds, cmd.stop_score)
            return

        if cmd.action == Action.MESSAGE:
            if not self.project_dir:
                cl.write("No project selected. Use /project <path>.")
                return
            self._send_message(cmd)
            return

    # ── Message sending ───────────────────────────────────────

    def _send_message(self, cmd: Command) -> None:
        cl = self.query_one("#center_log", RichLog)
        target_label = {
            Target.CLAUDE: "→ claude",
            Target.GEMINI: "→ gemini",
            Target.BOTH: "→ both",
        }
        label = target_label.get(cmd.target, "→ both")
        cl.write(f"  [{label}] {cmd.text[:200]}")

        if cmd.target == Target.CLAUDE or cmd.target == Target.BOTH:
            asyncio.create_task(self._send_to_claude(cmd.text))
        if cmd.target == Target.GEMINI or cmd.target == Target.BOTH:
            asyncio.create_task(self._send_to_gemini(cmd.text))

    async def _send_to_claude(self, text: str) -> None:
        if not self.claude:
            return
        self._log_claude(f"─── You ───")
        self._log_claude(f"{text[:300]}")
        self._log_claude(f"─── Claude ───")
        self._update_status("Claude: working...")
        await self.claude.send(text, self._log_claude)
        self.call_from_thread(self._update_status)

    async def _send_to_gemini(self, text: str) -> None:
        if not self.gemini:
            return
        self._log_gemini(f"─── You ───")
        self._log_gemini(f"{text[:300]}")
        self._log_gemini(f"─── Gemini ───")
        self.call_from_thread(self._update_status, "Gemini: working...")
        await self.gemini.send(text, self._log_gemini)
        self.call_from_thread(self._update_status)

    # ── Auto-iterate loop ─────────────────────────────────────

    def _start_loop(self, task: str, rounds: int, stop_score: float) -> None:
        if self._loop_task and not self._loop_task.done():
            self._log_center_sync("Loop already running. /stop first.")
            return
        self._loop_cancelled = False
        self._loop_paused = False
        self._initial_task = task
        self._loop_task = asyncio.create_task(
            self._run_loop(task, rounds, stop_score)
        )
        self._log_center_sync(f"Loop started: {rounds} rounds, stop@{stop_score}")
        self._update_status()

    async def _run_loop(self, task: str, rounds: int, stop_score: float) -> None:
        assert self.claude and self.gemini and self.project_dir
        tracker = ScreenshotTracker(os.path.join(self.project_dir, "screenshots"))
        last_verdict: Optional[str] = None

        for i in range(1, rounds + 1):
            if self._loop_cancelled:
                self._log_center(f"Loop cancelled at round {i}.")
                break

            # Wait if paused
            while self._loop_paused and not self._loop_cancelled:
                await asyncio.sleep(0.5)
            if self._loop_cancelled:
                break

            # ── Builder round ──
            self._log_center(f"━━━ Round {i}/{rounds} — Claude building ━━━")
            self.call_from_thread(self._update_status, f"Round {i}/{rounds} — building")
            tracker.snapshot()

            bp = builder_prompt(task, i, rounds, last_verdict)
            self._log_claude(f"─── Round {i}/{rounds} ───")
            builder_output = await self.claude.send(
                bp, self._log_claude, system=BUILDER_SYSTEM
            )

            if self._loop_cancelled:
                break
            while self._loop_paused and not self._loop_cancelled:
                await asyncio.sleep(0.5)
            if self._loop_cancelled:
                break

            # ── Judge round ──
            shots = tracker.new_files()
            self._log_center(
                f"━━━ Round {i}/{rounds} — Gemini judging ({len(shots)} screenshot(s)) ━━━"
            )
            self.call_from_thread(
                self._update_status,
                f"Round {i}/{rounds} — judging ({len(shots)} shots)",
            )

            jp = judge_prompt(task, i, rounds, builder_output, shots)
            self._log_gemini(f"─── Round {i}/{rounds} ───")

            if shots:
                verdict = await self.gemini.send_with_files(
                    jp, shots, self._log_gemini, system=JUDGE_SYSTEM
                )
            else:
                verdict = await self.gemini.send(
                    jp, self._log_gemini, system=JUDGE_SYSTEM
                )

            last_verdict = verdict
            score = parse_score(verdict)
            self._log_center(
                f"  Round {i} score: {score if score is not None else '?'}"
            )

            if score is not None and score >= stop_score:
                self._log_center(f"Target score reached ({score} >= {stop_score}). Done!")
                break

        self._log_center("━━━ Loop complete ━━━")
        self.call_from_thread(self._update_status)

    def _stop_everything(self) -> None:
        self._loop_cancelled = True
        self._loop_paused = False
        if self.claude:
            self.claude.cancel()
        if self.gemini:
            self.gemini.cancel()
        self._update_status()


# ── Entry points ──────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser("arbiter")
    ap.add_argument("project_dir", nargs="?", default=None,
                    help="Project directory (opens picker if omitted)")
    task_group = ap.add_mutually_exclusive_group()
    task_group.add_argument("-t", "--task", help="Task description (inline)")
    task_group.add_argument("--task-file", help="Path to task description file")
    ap.add_argument("-n", "--rounds", type=int, default=5)
    ap.add_argument("--stop-score", type=float, default=9.0)
    ap.add_argument("--claude-model", default="sonnet")
    ap.add_argument("--gemini-model", default="gemini-2.5-flash")
    args = ap.parse_args()

    task = None
    if args.task_file:
        with open(args.task_file, "r", encoding="utf-8") as f:
            task = f.read().strip()
    elif args.task:
        task = args.task

    project = os.path.abspath(args.project_dir) if args.project_dir else None

    ArbiterApp(
        project_dir=project,
        task=task,
        claude_model=args.claude_model,
        gemini_model=args.gemini_model,
    ).run()


if __name__ == "__main__":
    main()
