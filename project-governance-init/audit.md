# Audit: check a project's governance, change nothing

Checks an existing setup against the same model init generates from:
`references/governance-model.md` (roles, lanes, criticality, coordinator load,
token economy) and `references/acceptance-contracts.md` (what a sound
acceptance contract looks like).

## Read-only

The audit never edits, regenerates, scaffolds, approves or deletes anything:
not the ruleset, the state file, `governance-config.json`, the roadmap, an
acceptance contract, a GitHub issue, `CLAUDE.md` or any repo file. Its only output is the report, in the
reply, or as one new file when the owner names one. Both scripts below only
read. Fixes are proposed as exact replacement text or config changes; applying
them is the owner's decision, through init (rules and settings) or specify
(criteria and roadmap). The audit never runs the generator with `--set`.

## Steps

1. **Gather.** `claude-project-rules.yaml` (or rules living in `CLAUDE.md` /
   project instructions), `project-state.yaml`, `governance-config.json` if
   present, the repo's `CLAUDE.md`, the newest decision-log entries, CI
   workflow files, `roadmap.yaml`, and every `plans/contract-*.yaml`.
2. **Mechanical pass on the rules.**
   ```bash
   python3 scripts/audit_rules.py <rules.yaml> [--state <state.yaml>] [--json]
   ```
   It finds duplicate ids, missing or unknown `applies_to`, undeclared labels,
   state leaking into rules, dead history, implausible or non-numeric
   thresholds, undefined optional roles, a missing hard stop for critical
   PRs, merge conditions without "no open must-fix finding", an authority
   order that ranks the decision log above the owner, per-role extracts that
   are out of step with the ruleset, in a repository a ruleset, config,
   extract or roadmap that differs from its copy on the remote's default
   branch or a `default_branch` line that disagrees with the remote (A14;
   run `git fetch` first), a single review round for routine PRs, invariants
   that nothing but review enforces (A15), and the common contradiction
   patterns.
   Exit code 1 means at least one error.
3. **Mechanical pass on each acceptance contract.**
   ```bash
   python3 scripts/contract_tool.py lint <plans/contract-NNN-slug.yaml>
   ```
   Run it from the workspace so it finds the state file, the decision log and
   the ruleset next to `plans/`. It finds untestable or compound criteria,
   missing verify steps, unsourced research, uncovered categories, an approval
   that is not the owner's or whose message does not name the hash, a contract
   that differs from its pickup record or, in a repo, from the copy on the
   default branch (edited after approval, even if its hash was recomputed;
   run `git fetch` first so the comparison is current), a work-package label the ruleset does not have, and
   criteria outside any work package. Then the roadmap against the contracts
   and, if there is a ledger, its entries:
   ```bash
   python3 scripts/contract_tool.py roadmap <roadmap.yaml> --plans <plans dir>
   python3 scripts/ledger_tool.py check --ledger <ledger dir>
   python3 scripts/ledger_tool.py stats --ledger <ledger dir>
   python3 scripts/repo_readiness.py <repo>
   ```
   `stats` gives the share of reverted PRs and the finding kinds that came up
   in more than one PR; `repo_readiness.py` says whether the repository has
   the checks the rules lean on.
4. **Semantic pass.** Work through `references/audit-checklist.md`: the
   contradiction pairs, scope and role ownership, state leakage, token cost,
   and for contracts whether the criteria are the right ones. Rules most often
   contradict `CLAUDE.md` and recent decisions rather than each other.
5. **Report** in the exact format the checklist gives. Quote the rule or
   criterion ids on both sides of every finding and give replacement text, not
   just the complaint. End with the next step for the owner: which edits to
   approve, or which `governance-config.json` values to change before running
   init again.

## Things that are easy to get wrong

- Fixing while auditing. Even an obvious typo stays in the report.
- Auditing in the coordinator chat. The audit reads many files; run it in its
  own chat and give the coordinator the verdict paragraph only.
- Calling a contract approved, or a ruleset safe, because the scripts came back
  clean. The scripts cannot tell whether a criterion or a rule is the right one.
- Reporting a contradiction without both ids and without proposed text.
