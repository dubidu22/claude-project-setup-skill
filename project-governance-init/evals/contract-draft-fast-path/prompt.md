---
tags: [project-governance-init, mode-c]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, WebSearch, WebFetch]
---

Next milestone for ledgerlite (our Python CLI, click + sqlite, macOS and Ubuntu) is v0.2 "budget alerts": I set a monthly budget per category in a config file, and when I import transactions the CLI warns me if a category goes over budget for that month. Draft the acceptance contract for it as plans/contract-001-budget-alerts.yaml. Research what good budget-alert and CLI-error behaviour looks like so we don't miss edge cases, but keep it to what v0.2 really needs.

I'm heading out and can't answer questions in this session. Make your own assumptions where you need to, mark them so I can check them, and don't treat anything as approved. Finish with a short hand-back I can read in a minute.
