---
tags: [project-governance-init, init]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Set up the multi-thread Claude governance for a new project and write everything into ./out/. Details:

- Project: routewise, repo github.com/mkeller/routewise, public
- Owner: Mara Keller (GitHub mkeller), timezone Europe/Vienna, Ubuntu with bash, clone at ~/code/routewise
- Fullstack web app (FastAPI backend, React frontend, Postgres). Default lanes for that stack are fine. CI on ubuntu only.
- Balanced token profile. We will run three lanes at once.
- On my last project the coordinator chat was drowning: every fix list, status update and merge request went through it and it compressed several times per batch. I don't want that again, set it up so the coordinator only deals with batches and with me.
- Autonomy per milestone, round-4 stop on, my hand steps are deploying to production and creating milestones. Ping me when a milestone's acceptance contract is ready for my approval.
- The workspace lives in the repo under ./governance (but write to ./out/ for now).

I can't answer follow-ups in this session. Generate the rules, state, scaffolding and the instructions for each coordinating thread, then summarise who does what.
