---
tags: [project-governance-init, init]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'm starting a new project and want the multi-thread Claude governance set up for it (coordinator + implementation/review/KB threads, lanes, the rules yaml and the state yaml, the whole thing). Here's everything you need:

- Project: ledgerlite, repo github.com/rwaller/ledgerlite, private repo
- Owner: Rosa Waller (GitHub rwaller), timezone America/Chicago, macOS with zsh, clone lives at ~/dev/ledgerlite
- It's a Python CLI tool (click + sqlite). Checks we run: ruff, mypy, pytest. CI only needs ubuntu and macos, no windows.
- The coordinator will live in a claude.ai Project, so the shared files belong under /mnt/project-files. BUT for now write everything into ./out/ in the current directory so I can copy it over.
- Keep it frugal on tokens, except I want the watchdog every 60 minutes, not 120.
- Autonomy until v0.5 ships. Yes to the round-4 stop. My hand steps: publishing to PyPI, creating GitHub milestones, testing the CLI on my work laptop. Ping me when the first `ledgerlite import` command works end to end, and when v0.5 is done.
- Lanes: the default python preset is fine.
- No telemetry ever, default banned licences, plus two hard rules: the sqlite schema must stay backwards compatible across minor versions, and ledgerlite.cli may import ledgerlite.core but never the reverse.

I'm heading out so I can't answer follow-ups in this session. Use your own recommendations for anything I didn't cover and generate everything, including the scaffolding and the coordinator's project instructions. Finish with a summary of what you made and which values you had to assume.
