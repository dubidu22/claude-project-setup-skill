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
them is the owner's decision, through init (rules) or specify (criteria and
roadmap).

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
   state leaking into rules, dead history, implausible thresholds, undefined
   optional roles and the common contradiction patterns. Exit code 1 means at
   least one error.
3. **Mechanical pass on each acceptance contract.**
   ```bash
   python3 scripts/contract_tool.py lint <plans/contract-NNN-slug.yaml>
   ```
   It finds untestable or compound criteria, missing verify steps, unsourced
   research, uncovered categories, an approval that is not the owner's, and
   approved criteria edited in place (hash mismatch), and criteria outside any
   work package. Then the roadmap against the contracts:
   ```bash
   python3 scripts/contract_tool.py roadmap <roadmap.yaml> --plans <plans dir>
   ```
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
- Calling a contract approved, or a ruleset safe, because the scripts came back
  clean. The scripts cannot tell whether a criterion or a rule is the right one.
- Reporting a contradiction without both ids and without proposed text.
