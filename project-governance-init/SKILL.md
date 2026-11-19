---
name: project-governance-init
description: >
  Set up, change, migrate, specify work for, or audit the governance of a project run by
  several Claude threads: a coordinator chat plus implementation, review, KB and audit
  threads with lanes, PR review rounds, a decision log and owner-approved acceptance
  contracts. Use it to bootstrap such a project or change a setting later (model routing,
  token profile, lanes, dispatcher), to
  migrate an older or hand-edited ruleset, and to audit a ruleset, roadmap or acceptance
  contract for contradictions, unclear roles, stale state, untestable criteria or wasted
  tokens. Use it to specify work (a feature idea or change of plans becomes researched
  acceptance criteria, issue drafts and a roadmap update) only when the project has this
  governance or the user asks for "specify" or an acceptance contract; an ordinary feature
  request or coding task is not a trigger. Trigger for short asks like "set up the
  coordinator", "governance for my repo", "switch to cheaper models", "check my project
  rules" or "specify: budget alerts".
---

# Project governance

Three jobs, one knowledge base. Pick by what the user asks for and read only
that file; never mention this choice to the user.

| The user wants | Read | Changes files? |
|---|---|---|
| governance for a project that has none | `init.md` | yes: generates and scaffolds |
| a setting changed in a running project (models, token profile, dispatcher, ...) | `init.md`, section "Changing settings" | yes: regenerates the rules, keeps live state |
| a project that already runs on a ruleset but has no `governance-config.json` (older or hand-edited) brought onto the generator | `init.md`, section "Migrating an existing ruleset" | yes, after a diff the owner has seen; state, decision log and ledgers are kept |
| a feature idea or a change of plans turned into criteria, issues and a roadmap update | `specify.md` | drafts only, until the owner says yes |
| an existing ruleset, state file, roadmap or acceptance contract checked | `audit.md` | no: report only |

**Say first, then act.** Before any tool call or hand-off, write one line in
the chat the user typed in: what is starting and where questions will appear.
If the work runs in another thread, name that thread and say whether the user
has to answer something there; say so again when that thread is waiting for
them. A user who sees nothing after typing a command assumes it failed.

**Files only.** This skill reads and writes files in the workspace and the
repo. It never changes settings of the Claude app, the project or the account
(default model, a chat's model, permissions, connectors), even when a tool for
it exists. If such a change is needed, name it and let the user make it.

Called with no request at all (only the skill's name): reply in the same chat
with the three jobs as a short list and start nothing until the user picks.
Otherwise, if it is unclear which one is meant, ask one question there. None of the three turns
into another on its own: an audit reports and stops; specify never changes
rules; init never writes criteria.

**When not to start.** A feature request, bug report or coding task in a
project without this governance (no `claude-project-rules.yaml`, no
`roadmap.yaml`, no `plans/contract-*`) is ordinary work: do it, or let the
normal flow handle it, and do not open a specify interview. Specify starts
there only when the user asks for it by name or asks for acceptance criteria
or an acceptance contract.

**Keep the coordinator chat small.** Init and specify hold interviews; an
audit reads many files. Run them in their own chat. If you are called in the
coordinator chat of a governed project, say in one line that the work starts
in a separate thread and where the questions will appear, then hand over.

Shared by all three:

- `references/governance-model.md`: roles, lanes, criticality, coordinator
  load, token economy, the rule catalog.
- `references/acceptance-contracts.md`: how acceptance criteria are
  researched, written, grouped into work packages, approved and frozen, and
  how the roadmap is kept.
- `references/audit-checklist.md`: semantic checks and the report format.
- `scripts/`: `generate_project_rules.py` and `scaffold_workspace.py` write
  files (init only); `audit_rules.py`, `ledger_tool.py`, `repo_readiness.py`
  and `contract_tool.py` only read (`pr_checks.py` is copied into the
  project's repository to run in CI), except `contract_tool.py record-issue`, which notes a created
  issue number (specify only). `contract_tool.py pickup` is the coordinator's
  check before it records a contract. Run the tools; do not read their source.
