# Arbiter

A split-pane terminal UI that runs **Claude Code** as an autonomous builder on one side and **Gemini** as a judge/evaluator on the other, in an automatic iteration loop.

```
┌────────────────────────────── Arbiter ──────────────────────────────┐
│ Project: …/my-ui   Rounds: 5   Stop@: 9.0   State: Round 2/5 …     │
├──────────────────────────────┬──────────────────────────────────────┤
│ 🛠 Claude Code — BUILDER     │ ⚖ Gemini — JUDGE                     │
│ (--dangerously-skip-perms)   │ (gemini-2.5-pro, multimodal)         │
│                              │                                      │
│ …claude stream…              │ …gemini verdict…                     │
│                              │  SCORE: 7.5                          │
│                              │  GAPS: - …                           │
└──────────────────────────────┴──────────────────────────────────────┘
```

## What it does

Each round:

1. **BUILDER** — Claude Code is launched headless in the project dir with `--dangerously-skip-permissions` and the task prompt (plus the judge's previous verdict, if any). Its stdout streams live into the left pane.
2. Arbiter collects any new PNG/JPG files the builder dropped under `./screenshots/`.
3. **JUDGE** — Gemini CLI is launched with `gemini-2.5-pro`, the same task, the builder's CHANGELOG, and `@"path"` references to the new screenshots. Its verdict streams into the right pane.
4. Arbiter parses `SCORE:` from the verdict. If `score >= stop_score`, the loop stops; otherwise the verdict is fed into the builder's next round.

## Requirements

- Python 3.10+
- `claude` CLI on PATH (Claude Code)
- `gemini` CLI on PATH (Google Gemini CLI). On Windows, Arbiter bypasses the `.cmd` shim and invokes `node <bundle>/gemini.js` directly to preserve quoted `@"path"` argv — the same trick used in `Dunamisv2/dunamis/gemini_cli.py`.
- `pip install -r requirements.txt`

## Usage

```bash
python -m arbiter.app /path/to/project \
    -t "Build a landing page for a pomodoro timer with clear hierarchy and dark mode" \
    -n 5 --stop-score 9
```

Keys: **s** start · **c** cancel · **q** quit

## Contract for the builder

Tell Claude (via the task) to save screenshots of the UI state into `./screenshots/round_<N>_<label>.png` at the end of each round. Arbiter diffs mtimes so only screenshots produced during the round are sent to Gemini.

## Why this shape

- **Claude Code** is the best autonomous code editor and is genuinely good at multi-file refactors and running commands.
- **Gemini 2.5 Pro** is strong at multimodal critique — it looks at the screenshots and writes specific, visual UX/UI gaps.
- The loop converts Gemini's critique directly into Claude's next-round brief, so Claude operates on concrete, grounded feedback instead of its own assumptions.
