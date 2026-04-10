"""Command parser — routes user input to agents or controls the loop."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class Target(Enum):
    CLAUDE = auto()
    GEMINI = auto()
    BOTH = auto()


class Action(Enum):
    MESSAGE = auto()       # send text to agent(s)
    LOOP_START = auto()    # start auto-iterate loop
    LOOP_STOP = auto()     # stop auto-iterate loop
    PAUSE = auto()         # pause current agent
    RESUME = auto()        # resume paused agent
    STATUS = auto()        # show current state
    CLEAR = auto()         # clear pane(s)
    PROJECT = auto()       # change project dir
    HELP = auto()          # show help
    QUIT = auto()          # exit


@dataclass
class Command:
    action: Action
    target: Optional[Target] = None
    text: str = ""
    rounds: int = 5
    stop_score: float = 9.0


HELP_TEXT = """Commands:
  /claude <msg>     Send message to Claude Code only
  /gemini <msg>     Send message to Gemini only
  /both <msg>       Send message to both agents
  <msg>             Same as /both — broadcasts to both

  /loop [N] [score] Start auto build→judge loop (N rounds, stop at score)
  /stop             Stop the current loop or running agent
  /pause            Pause after current agent finishes
  /resume           Resume paused loop

  /status           Show agent states and round info
  /clear            Clear all panes
  /project <path>   Change project directory
  /help             Show this help
  /quit or /exit    Exit Arbiter
"""


def parse(raw: str) -> Command:
    """Parse raw user input into a Command."""
    text = raw.strip()
    if not text:
        return Command(action=Action.HELP)

    # Slash commands
    if text.startswith("/"):
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            return Command(action=Action.QUIT)

        if cmd == "/help":
            return Command(action=Action.HELP)

        if cmd == "/status":
            return Command(action=Action.STATUS)

        if cmd == "/clear":
            return Command(action=Action.CLEAR)

        if cmd == "/pause":
            return Command(action=Action.PAUSE)

        if cmd == "/resume":
            return Command(action=Action.RESUME)

        if cmd == "/stop":
            return Command(action=Action.LOOP_STOP)

        if cmd == "/project":
            return Command(action=Action.PROJECT, text=rest.strip())

        if cmd == "/claude":
            return Command(action=Action.MESSAGE, target=Target.CLAUDE, text=rest)

        if cmd == "/gemini":
            return Command(action=Action.MESSAGE, target=Target.GEMINI, text=rest)

        if cmd == "/both":
            return Command(action=Action.MESSAGE, target=Target.BOTH, text=rest)

        if cmd == "/loop":
            rounds = 5
            score = 9.0
            tokens = rest.split()
            if len(tokens) >= 1:
                try:
                    rounds = int(tokens[0])
                except ValueError:
                    pass
            if len(tokens) >= 2:
                try:
                    score = float(tokens[1])
                except ValueError:
                    pass
            return Command(
                action=Action.LOOP_START,
                rounds=rounds,
                stop_score=score,
                text=rest,
            )

        # Unknown slash command → treat as message to both
        return Command(action=Action.MESSAGE, target=Target.BOTH, text=text)

    # No slash → message to both
    return Command(action=Action.MESSAGE, target=Target.BOTH, text=text)
