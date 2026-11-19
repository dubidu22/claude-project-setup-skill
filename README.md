# claude-project-setup-skill

A Claude skill, `project-governance-init`, that sets up, changes, migrates or audits the governance for a project run by several Claude threads (a coordinator chat plus implementation, review, KB and audit threads working through lanes, PR review rounds and a decision log), and turns feature ideas into owner-approved acceptance contracts.

## What it does

One skill, three jobs, one shared knowledge base:

- **Init** (`init.md`): a six-stage walkthrough (identity, model routing vs. token economy, autonomy gates, lanes and labels, quality gates, generation) that renders `claude-project-rules.yaml`, a per-role extract of it for each thread type, and `project-state.yaml`, and scaffolds the shared workspace: `plans/`, `kb/`, the ledger, `roadmap.yaml`, coordinator instructions, GitHub setup files, and the acceptance-contract method, template and checker. It also changes settings in a running project (`--set model_preset=economy`, `--set profile_key=frugal`, ...) with a preview of what changes, and migrates an older or hand-edited ruleset onto the generator after showing the difference. Live state, the decision log and ledgers are kept.
- **Specify** (`specify.md`): turns a brief feature idea or a change of plans into an acceptance contract with researched, testable criteria, a few work packages that become GitHub issues, and an updated roadmap. The owner sees every criterion and verify step and approves by quoting the contract's hash; issues are created only on a separate yes, after a pre-flight check, and their numbers are recorded.
- **Audit** (`audit.md`): checks an existing ruleset, state file, roadmap, acceptance contracts and ledger for contradictions, unclear roles, stale state, untestable criteria, contracts edited after approval and token bloat. Read-only: it reports and proposes exact fixes, and changes nothing.

All three work from the same model in `references/`: roles and lanes, coordinator load and token economy, cache-aware thread habits, operating mechanics per environment, and owner-approved acceptance contracts per milestone.

## Layout

```
project-governance-init/
├── SKILL.md                       picks init, specify or audit
├── init.md                        set up, change settings, migrate (writes files)
├── specify.md                     idea or plan change -> criteria, issues, roadmap (drafts until approved)
├── audit.md                       check and report (read-only)
├── scripts/
│   ├── generate_project_rules.py  config JSON -> rules, per-role extracts, state; --set, --dry-run, --derive-config
│   ├── scaffold_workspace.py      renders assets/templates into the workspace; --github writes github-setup/
│   ├── audit_rules.py             mechanical ruleset check, read-only
│   ├── contract_tool.py           contract lint, owner view, hash, pickup check, comparison with the default branch, issue drafts and pre-flight, roadmap check, /goal line
│   ├── ledger_tool.py             tables, statistics (rounds, reverts, repeated findings) and the merge gate from the ledger entries, read-only
│   ├── repo_readiness.py          does the repository have CI, tests, a linter, a way to run it? read-only
│   └── pr_checks.py               pull-request checks for the project's CI: title, closing keywords, lane label, file ownership, critical paths
├── references/
│   ├── governance-model.md        the model, the five invariants, rule catalog, operating mechanics, what is enforced by what, checks before prose
│   ├── acceptance-contracts.md    criteria, work packages, approval, freeze, roadmap
│   └── audit-checklist.md         semantic checks and report format
├── assets/templates/              scaffold templates
└── evals/                         test cases (claude plugin eval layout)
tests/                             pytest suite for the scripts and the eval fixtures
```

## Install

Package the folder with the skill-creator `package_skill.py` script, or copy `project-governance-init/` into your skills directory.

## Run the tests

Two kinds of test, for two different things.

**The scripts** (fast, deterministic, also run by CI on every push and pull request):

```bash
pip install pytest pyyaml
python3 -m pytest tests -q
```

They cover the generator (type checks, quoting, the self-check of its own output, options, versioning, migration), the audit, the contract tool (the freeze, the owner view, issues, reading YAML with and without PyYAML), the scaffold and the ledger tool. They also build every eval fixture the way the eval runner does and check that it is sound, so fixtures cannot go stale.

**The skill's behaviour** (slow, needs Claude Code v2.1.269 or later), inside `project-governance-init/`:

```bash
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```

The eval cases cover the unattended paths (owner cannot reply), the interactive ones (stage 1 of the walkthrough, a settings preview that waits for a yes, the first interview question, approval with and without the hash, issue creation), and routing (bare invocation, an ordinary feature request that must not start specify, an audit asked to fix things). Fixtures that depend on the generator are built at test time by each case's `place-files.sh`.
