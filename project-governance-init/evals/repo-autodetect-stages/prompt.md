---
tags: [project-governance-init, mode-a, autodetect]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Walk me through setting up the multi-thread Claude governance rules for the repo in ./soundforge (coordinator + worker threads, lanes, rules yaml, state yaml). I'd like the governance files to live inside the repo under ./soundforge/governance because I'll run the coordinator from Claude Code, not from a claude.ai Project. Owner is Tomasz Nowak (tnowak on GitHub), Europe/Warsaw, Linux with bash, public repo tnowak/soundforge, clone at ~/src/soundforge. Models: whatever you recommend.

Go stage by stage and give me your recommendation for each with the reasoning. I can't reply during this session, so for each stage take your own recommendation and move on, then generate everything at the end; I'll go over the summary and adjust afterwards. Look at the repo first, don't just guess the stack.

Input files: soundforge/
