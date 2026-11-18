# claude-project-setup-skill

A Claude skill, `project-governance-init`, that sets up or audits the governance for a project run by several Claude threads (a coordinator chat plus implementation, review, KB and audit threads working through lanes, PR review rounds and a decision log).

## What it does

One skill, two jobs, one shared knowledge base:

- **Init** (`init.md`): a six-stage walkthrough (identity, model routing vs. token economy, autonomy gates, lanes and labels, quality gates, generation) that renders `claude-project-rules.yaml` and `project-state.yaml` deterministically and scaffolds the shared workspace: `plans/`, `kb/`, ledgers, coordinator instructions, GitHub lane labels, and the acceptance-contract method, template and checker. Optionally adds a dispatcher thread for per-PR operations. Also regenerates from an existing `governance-config.json`.
- **Audit** (`audit.md`): checks an existing ruleset, state file and acceptance contracts for contradictions, unclear roles, stale state, untestable criteria and token bloat. Read-only: it reports and proposes exact fixes, and changes nothing.

Both work from the same model in `references/`: roles and lanes, coordinator load and token economy, and owner-approved acceptance contracts per milestone.

## Layout

```
project-governance-init/
├── SKILL.md                       picks init or audit
├── init.md                        set up or regenerate (writes files)
├── audit.md                       check and report (read-only)
├── scripts/
│   ├── generate_project_rules.py  config JSON -> rules + state YAML      (init)
│   ├── scaffold_workspace.py      renders assets/templates into the workspace (init)
│   ├── audit_rules.py             mechanical ruleset check, read-only    (audit, init self-check)
│   └── contract_tool.py           acceptance-contract lint, summary, brief, hash, /goal line (read-only)
├── references/
│   ├── governance-model.md        the model, the five invariants, rule catalog
│   ├── acceptance-contracts.md    how a contract is researched, written, approved, frozen
│   └── audit-checklist.md         semantic checks and report format
├── assets/templates/              scaffold templates
└── evals/                         test cases (claude plugin eval layout)
```

## Install

Package the folder with the skill-creator `package_skill.py` script, or copy `project-governance-init/` into your skills directory.

## Run the tests

From Claude Code (v2.1.269 or later), inside `project-governance-init/`:

```bash
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```
