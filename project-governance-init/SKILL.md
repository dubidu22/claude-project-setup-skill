---
name: project-governance-init
description: >
  Set up or audit governance for a project run by several Claude threads (a coordinator
  chat plus implementation, review, KB and audit threads working through lanes, PR review
  rounds, a decision log and owner-approved acceptance contracts). Use it whenever the user
  wants to bootstrap or regenerate a multi-thread Claude project: write
  `claude-project-rules.yaml` / `project-state.yaml`, pick a token-economy profile, route
  models to roles, define lanes and `lane:*` labels, set autonomy limits and owner sign-off
  gates, add a dispatcher for an overloaded coordinator, or scaffold plans/, kb/, ledgers,
  labels and the acceptance-contract tooling. Also use it to audit, lint or review an
  existing ruleset, rules YAML, CLAUDE.md governance section or acceptance contract for
  contradictions, unclear roles, stale state, untestable criteria or wasted tokens. And use
  it to specify work: turn a brief feature idea or a change of plans into researched
  acceptance criteria, GitHub issue drafts and an updated roadmap. Trigger even for short
  asks like "set up the coordinator", "governance for my repo", "check my project rules",
  "I want to add X", "specify this feature" or "my plans changed".
---

# Project governance

Three jobs, one knowledge base. Pick by what the user asks for and read only
that file; never mention this choice to the user.

| The user wants | Read | Changes files? |
|---|---|---|
| governance for a project that has none, or a setting changed in an existing one | `init.md` | yes: generates and scaffolds |
| a feature idea or a change of plans turned into criteria, issues and a roadmap update | `specify.md` | drafts only, until the owner says yes |
| an existing ruleset, state file, roadmap or acceptance contract checked | `audit.md` | no: report only |

If it is unclear which one is meant, ask one question. None of the three turns
into another on its own: an audit reports and stops; specify never changes
rules; init never writes criteria.

Shared by all three:

- `references/governance-model.md`: roles, lanes, criticality, coordinator
  load, token economy, the rule catalog.
- `references/acceptance-contracts.md`: how acceptance criteria are
  researched, written, grouped into work packages, approved and frozen, and
  how the roadmap is kept.
- `references/audit-checklist.md`: semantic checks and the report format.
- `scripts/`: `generate_project_rules.py` and `scaffold_workspace.py` write
  files (init only); `audit_rules.py` and `contract_tool.py` only read.
