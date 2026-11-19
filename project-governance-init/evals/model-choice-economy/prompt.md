---
tags: [project-governance-init, init]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Set up the multi-thread Claude governance for a new project and write everything into ./out/. Details:

- Project: trailmark, repo github.com/jorin/trailmark, private
- Owner: Jo Rinaldi (GitHub jorin), timezone Europe/Rome, macOS with zsh, clone at ~/src/trailmark
- Python library, default lanes, CI on ubuntu only, balanced token profile, I pay by subscription.
- Models: I want Sonnet on high effort for the day-to-day implementation and review work. Opus should be the coordinator and should only be used for the difficult things: critical changes, working out acceptance criteria, and anything the cheaper model keeps getting wrong.
- Autonomy per milestone, round-4 stop on, my hand steps are PyPI publishing and creating milestones.

I can't answer follow-ups in this session. Generate the rules, state and scaffolding, then tell me briefly which model does what.
