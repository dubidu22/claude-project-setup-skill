# Audit checklist

Load this after the two mechanical passes in `audit.md`. The scripts catch the
mechanical problems; this checklist is for the findings that need a reader who
understands what the rules and criteria are *for*. `governance-model.md`
(section 6 for the invariants, section 1 for roles and coordinator load) and
`acceptance-contracts.md` are the standard being checked against. The audit
reports; it changes nothing.

## Inputs to gather

- `claude-project-rules.yaml` (required) and `project-state.yaml` if present.
- The repository's `CLAUDE.md`, any `kb/process.md` / `kb/architecture.md`,
  the newest 10 to 20 decision-log entries, and workflow files under
  `.github/workflows/`. Rules often contradict *these*, not each other.
- `roadmap.yaml`, every `plans/contract-*.yaml`, the plans and PR bodies that
  cite them, and the open issues if GitHub is reachable (read only).
- If `governance-config.json` exists, regenerate into a temporary directory
  outside the project (never over the live files) and
  diff: hand edits that drifted from the generator are the first suspects.

## 1. Static rules versus mutable state

A ruleset is read by every thread at start-up and after every compression.
Anything in it that changes week to week is paid for on every read and goes
stale silently. Flag and move to `project-state.yaml`:

- pause / slow-down / freeze flags, active milestones, "currently" or "this
  week" wording, message ids, open-batch lists, pending notifications
- owner commands that were issued and later lifted ("history", "lifted",
  "no longer", dates in the past tense)
- rules that only make sense for one release ("during the v0.2 crunch")

## 2. Scope: every rule names who it binds

`applies_to` must be one of `owner | coordinator | dispatcher | specify |
implementation | review | kb | audit | all`. A `dispatcher` or `specify`
scope needs a rule in `roles` that defines the role. Also check that the scope is *right*: a rule about merge
protocol scoped to `implementation` (which never merges) is dead; a rule about
plan approval scoped to `review` binds the wrong thread.

## 3. Contradiction pairs

Check each pair explicitly and quote both rule ids in the finding.

| Invariant | Look for | Typical contradiction |
|-----------|----------|------------------------|
| Lane separation | `lanes`, `project_profile.file_ownership_labels` | rules require `lane:infra` but the label is not declared; a lane may edit core without the lock; docs need the lock; `max_concurrent_lanes` exceeds the lane count |
| Release CI precedence | `testing_and_ci`, workflow `on:` triggers | a release-branch trigger (ubuntu-only, skip matrix) stated as applying to *all* PRs; no dispatch/label path for the full matrix; `CRIT-02` demands full CI but no workflow can provide it |
| KB criticality scope | `plans_and_criticality`, `github_kb_and_release`, `roles` | KB docs critical *and* every KB PR requires review *and* KB thread self-merges: pick two; or decision-log PRs exempt but process docs also exempt |
| Atomic replacement | `threads_and_watchdog` | "replaced immediately", "mid-review", or a KB-thread exception that lets it be replaced mid-PR |
| Round-4 hard stop | `autonomy`, `pull_requests_and_reviews`, `execution_profile.token_economy.critical_max_review_rounds` | autonomy grant lets the coordinator approve after round 4; `critical_max_review_rounds` is not 4 while rules say round 4; non-critical cap exceeds critical cap |
| Owner approval | `roles` | something other than the owner's own messages counts as approval; a thread may edit the ruleset |
| Acceptance-contract freeze | `plans_and_criticality`, `autonomy` | an autonomy grant (`AUTO-01`) lets a thread approve or change an acceptance contract that `PLAN-03` reserves for the owner; `PLAN-05` closes milestones without the core probe; `REV-03` missing while `PLAN-04` requires proof in PR bodies |
| Dispatcher authority | `roles`, `pull_requests_and_reviews` | the dispatcher may grant merge go for critical PRs, approve plans or decide scope; a rule still tells the coordinator to do what `ROLE-11` gave the dispatcher (two owners for one duty); `ROLE-04` relays fix lists while `THR-04` routes them through round reports |
| Force-push / branch freeze | `pull_requests_and_reviews`, `CLAUDE.md` | repo docs say "always force-push after rebase" while rules say never |
| Authority order | header `authority`, `project_instructions` | two sources both claim to win; decision log not above repo `CLAUDE.md` |

## 4. Token efficiency

Every token in the ruleset is multiplied by the number of threads and the
number of compressions. Flag:

- more than ~60 rules, or any rule over ~450 characters that could be two
- duplicated wording (same rule stated in two sections)
- explanations and rationale inside rules (move to KB; keep the rule)
- history sections, command logs, changelogs
- rules restating what the generator's `authority` list already implies

Propose the replacement text for each flagged rule, not just the complaint.

## 5. Roles: one duty, one owner

- Every role a rule is scoped to is defined in `roles`, and every thread type
  that exists in the project has a role (a "worker thread" with no scope is
  bound by nothing).
- No duty has two owners. Typical overlaps: coordinator and dispatcher both
  spawn or nudge threads; coordinator and review both grant merge go; a rule
  scoped to `implementation` describes something only the coordinator does.
- The coordinator is long-lived: no rule replaces it on a compression count,
  and none makes it read diffs, logs, research or whole contracts. Without a
  dispatcher and with three or more lanes, expect it to compress; recommend
  turning the dispatcher on.
- The coordinator is not a relay: fix lists go through round reports, status
  is read from ledgers and PR state. A coordinator rule that forwards
  per-PR messages is a token finding and a role finding.
- Authority stays where it belongs: scope, the roadmap, acceptance contracts
  and round-4 sign-off with the owner; drafting them with specify, which
  approves nothing; critical merge go and plan approval with the
  coordinator; nothing critical with a dispatcher.

## 6. Acceptance contracts

For each `plans/contract-*.yaml`, after `contract_tool.py lint`:

- Is every `must` criterion something the owner would notice failing? If not
  it is a `should` or a `could`.
- Does each criterion state one observable, binary thing, and does its verify
  step actually prove it (a test that exists, a command with an expected result)?
- Does the core probe prove the goal sentence end to end, from a fresh clone?
- Are skipped categories skipped for a reason that holds for this milestone?
- Do plans and PR bodies cite criterion ids with proof (`PLAN-04`), and did a
  review confirm them (`REV-03`)?
- Was the contract approved by the owner's own message, with a D-number in the
  decision log that matches `approval.decision`?

Propose rewritten criterion text with a verify step for each one that fails.

Issues and roadmap, after `contract_tool.py roadmap --plans`:

- Do the GitHub issues still match `contract_tool.py issues` for the approved
  version? An issue whose criteria text differs from the contract has drifted;
  the contract wins.
- Is there an issue or PR for work that no approved criterion covers, or an
  `active` milestone whose contract the coordinator never picked up (no
  D-number)?
- Does `project-state.yaml` list the same active milestones as `roadmap.yaml`?
- Do `superseded` versions and `dropped` milestones still have open PRs with
  no owner decision (`PLAN-06`)?

## 7. Report format

Use exactly this structure so the owner can act on it top-down:

```markdown
# Ruleset audit: <project> (<rules file>, version <v>, dated <date>)

## Verdict
One paragraph: is the ruleset safe to run threads on as-is? What must change first?

## Must fix (contradictions and invariant violations)
- **<RULE-ID> vs <RULE-ID>** — what they say, why it bites, proposed fix (quote the new rule text).

## Should fix (scope and roles, state leakage, drift from generator)
- ...

## Acceptance contracts, issues and roadmap
- <C-NNN> <AC-N>: what is wrong, proposed criterion text and verify step; roadmap and issue drift. Omit the section when there are no contracts.

## Token savings
- <RULE-ID>: current N chars → proposed M chars; or "delete section X (~N tokens per thread start)".

## Mechanical findings
Paste or summarise `audit_rules.py` output; mark which items the sections above already cover.

## Suggested next step
For the owner to decide, since the audit applies nothing: either "approve these
edits via PR (critical, `META-01`)" with the list, or "change these values in
governance-config.json and run init again: ...". A finding on an approved
contract or the roadmap is always "run specify: new version, new owner
approval".
```

Severity guide: a contradiction between two *active* rules, or a violation of
one of the five invariants, is always Must fix. State leakage and missing
scopes are Should fix unless the leaked state is a pause flag (then Must fix,
because a stale `paused: true` halts the project).
