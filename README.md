# claude-project-setup-skill

A Claude skill, `project-governance-init`, that sets up or audits the governance for a project run by several Claude threads (a coordinator chat plus implementation, review, KB and audit threads working through lanes, PR review rounds and a decision log).

## What it does

- **Mode A, new project**: a six-stage walkthrough (identity, model routing vs. token economy, autonomy gates, lanes and labels, quality gates, generation) that renders `claude-project-rules.yaml` and `project-state.yaml` deterministically and scaffolds the shared workspace (`plans/`, `kb/`, ledgers, coordinator instructions, GitHub lane labels).
- **Mode B, audit**: a mechanical lint (`scripts/audit_rules.py`) plus a semantic checklist for contradictions, stale state, missing scopes and token bloat in an existing ruleset.
- **Mode C, acceptance contract**: interview, researched and sourced acceptance criteria, Pareto cut, owner approval and a frozen, versioned contract per milestone; `scripts/contract_tool.py` lints it and prints the `/goal` line for implementation threads.

## Layout

```
project-governance-init/
├── SKILL.md                       instructions Claude follows
├── scripts/
│   ├── generate_project_rules.py  config JSON -> rules + state YAML
│   ├── audit_rules.py             mechanical ruleset audit
│   ├── scaffold_workspace.py      renders assets/templates into the workspace
│   └── contract_tool.py           acceptance-contract lint, summary, /goal line
├── references/
│   ├── governance-model.md        the model, the five invariants, rule catalog
│   ├── audit-checklist.md         Mode B checklist and report format
│   └── acceptance-contracts.md    Mode C method: research, criteria, freeze
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
