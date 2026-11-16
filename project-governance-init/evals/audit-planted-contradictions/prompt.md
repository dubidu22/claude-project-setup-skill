---
tags: [project-governance-init, mode-b]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Our tidewatch project has been running with a coordinator and worker threads for a couple of months and the rules file has been hand-edited a lot along the way. Threads keep doing contradictory things (one review thread merged a KB PR without review, another refused to; a critical PR into release/0.4 ran only on ubuntu). Please audit governance/claude-project-rules.yaml (state file is next to it, and there's a CLAUDE.md in the repo root) for contradictions, stale state, missing scopes and anything that's just burning tokens. I want a written audit report I can act on, saved as audit-report.md, with concrete fixes rather than just "this is wrong".

Input files: governance/claude-project-rules.yaml, governance/project-state.yaml, CLAUDE.md
