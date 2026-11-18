---
tags: [project-governance-init, specify]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, WebSearch, WebFetch]
---

My plans for ledgerlite changed, three things (workspace is ./governance):

1. For v0.1 I no longer care about re-importing the same file without duplicates. What I do need is that the import also accepts semicolon-separated files, because that's what my bank actually exports.
2. I want the PDF export before the budget alerts.
3. Let's use typer instead of click for the CLI.

Sort out what each of these means for the project and prepare whatever needs my decision. I can't reply in this session; don't approve anything on my behalf.
