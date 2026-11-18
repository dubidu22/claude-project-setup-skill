---
tags: [project-governance-init, audit]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

A worker thread drafted the acceptance contract for our reminders milestone and the coordinator already marked it approved: plans/contract-004-reminders.yaml. Before any implementation thread starts on it, check it properly. Write contract-review.md with what must be fixed before it can bind anyone, and give rewritten text (with a verify step) for every criterion that isn't testable as written. Don't approve anything yourself.

Input file: plans/contract-004-reminders.yaml
