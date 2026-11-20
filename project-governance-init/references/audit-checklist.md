# Audit checklist

Load this after the two mechanical passes in `audit.md`. The scripts catch the
mechanical problems; this checklist is for the findings that need a reader who
understands what the rules and criteria are *for*. `governance-model.md`
(section 6 for the invariants, section 1 for roles and coordinator load) and
`acceptance-contracts.md` are the standard being checked against. The audit
reports; it changes nothing.

## Inputs to gather

- `claude-project-rules.yaml` (required), the extracts in `rules/` and
  `project-state.yaml` if present.
- The repository's `CLAUDE.md`, any `kb/process.md` / `kb/architecture.md`,
  the newest 10 to 20 decision-log entries, and workflow files under
  `.github/workflows/`. Rules often contradict *these*, not each other.
- `roadmap.yaml`, every `plans/contract-*.yaml`, `plans/issues-*.json`, the
  plans and PR bodies that cite them, the ledger (`ledger_tool.py table` and
  `check`), and the open issues if GitHub is reachable (read only).
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
implementation | review | kb | audit | all` (plus `assist`). A `dispatcher`,
`specify` or `assist` scope needs a rule in `roles` that defines the role. Also check that the scope is *right*: a rule about merge
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
| Hard stop at the last critical round | `autonomy`, `pull_requests_and_reviews`, `execution_profile.token_economy.critical_max_review_rounds` | no rule stops a critical PR for owner sign-off (a hand edit to "coordinator escalation"); an autonomy grant lets the coordinator approve after the last round; the round a rule names differs from `critical_max_review_rounds`; non-critical cap exceeds critical cap |
| Criticality and merge go | `plans_and_criticality`, `pull_requests_and_reviews`, `roles` | no rule says who decides whether a PR is critical; the dispatcher or the author decides it alone; merge allowed with an open must-fix finding; `REV-01` defers must-fix findings to issues; `REV-01` and `REV-04` fire at the same round with no stated order, or the rounds after escalation are not stated |
| Owner approval | `roles` | something other than the owner's own messages counts as approval; a thread may edit the ruleset |
| Acceptance-contract freeze | `plans_and_criticality`, `autonomy` | an autonomy grant (`AUTO-01`) lets a thread approve or change an acceptance contract that `PLAN-03` reserves for the owner; `PLAN-05` closes milestones without the core probe; `REV-03` missing while `PLAN-04` requires proof in PR bodies |
| Dispatcher authority | `roles`, `pull_requests_and_reviews` | the dispatcher may grant merge go for critical PRs, approve plans or decide scope; a rule still tells the coordinator to do what `ROLE-11` gave the dispatcher (two owners for one duty); `ROLE-04` relays fix lists while `THR-04` routes them through round reports |
| Force-push / branch freeze | `pull_requests_and_reviews`, `CLAUDE.md` | repo docs say "always force-push after rebase" while rules say never |
| Authority order | header `authority`, `project_instructions`, `ROLE-01` | the decision log ranks above the owner's messages although `ROLE-01` lets the owner override any entry; the ruleset or approved contracts are missing from the list; two sources both claim to win; decision log not above repo `CLAUDE.md`; D-entries for owner decisions without the owner's message quoted |
| One writer per file | `threads_and_watchdog`, `roles`, templates | the coordinator and the KB thread both write the decision log, with no pending-decisions file between them; two roles write the same ledger, the state file or the roadmap (for example an assist thread editing `owner_open_steps`, or a dispatcher "keeping the ledgers current"); in a repo, no rule names the branch working files are committed on |
| Reviewed copies | git, `project_profile.default_branch` | in a repo: the ruleset, config, extracts or roadmap on the working branch differ from the default branch (A14, C040); `default_branch` names a branch other than the remote's default; the checkout has no `origin/HEAD`, so the tools could not arbitrate; anyone used `lint --no-git` and treated the result as verified |
| Checks before prose | the whole ruleset, `github-setup/`, the repository | a rule a machine could check is left to prose (PR title, file ownership, force pushes) although the checks were scaffolded and never installed; invariants with "Enforced by: review only" (A15); a rule added to answer a mistake that a lint rule or test would stop; `ledger_tool.py stats` shows the same finding kind in several PRs and no check came of it; comments or notes in the code that justify a workaround; the repository lacks CI, tests or a linter (`repo_readiness.py`) while several lanes run |
| Exemptions and overrides | `github-setup/pr-check-exemptions.json`, `ledger/overrides/` | a debt exemption without an open issue; a path glob widened instead of an exemption; an override reused for a later head or kept as a setting; several overrides for the same reason; a `fixes_kinds` claim that `ledger_tool.py stats` shows as regressed |
| Proof and leftovers | `ledger/deferred/`, `ledger/prs/`, `github-setup/` | a check that was never seen to fail (`pr_checks.py --self-test` reports DEAD, or an invariant's check has no `(proved: ...)` note); `ledger_tool.py triage` lists open items while a batch is running; a hand-back `blocked` or `question` older than a batch; an audit report without a verdict per flag |
| Proof | `VER-01`, `REV-03`, `kb/verification.md`, PR bodies | `kb/verification.md` still says "draft" while PRs cite it; criteria marked as proven without an evidence file; proof through a test-only shortcut or one entry point of several; a journey that was loosened until it passed; a single review round for routine PRs |
| Observable triggers | `threads_and_watchdog` | a rule depends on something a thread cannot see: its own compression count as the only replacement trigger, its context size in tokens, a timer nobody fires, `/compact` in a claude.ai Project, a model that is "set" with no rule saying by whom |

## 4. Token efficiency

Rank token findings by how often something is re-sent uncached, not by its
size (governance-model section 9). First, habits that throw the cache away:

- threads woken after more than `cache_ttl_minutes` instead of being replaced
  from a handoff (look for long gaps between entries of one thread in the
  ledgers and round reports); a watchdog rule that nudges cold threads
- model routing where critical work is reviewed on a weaker model than it was
  written on, or a cheaper routine model whose PRs need more review rounds
  than before (compare rounds per PR, `ledger_tool.py stats`)
- a rule or routine that changes a thread's model or tool set mid-thread (for
  example one review thread switching models between critical and regular PRs)
- logs, diffs or full tool output pasted into chat or written into round
  reports that other threads then read
- a new thread spawned per small fix while a warm thread on the same code exists
- the coordinator woken many times a day for single questions or status
  updates, or reading diffs, logs or whole contracts
- saving in the wrong place: one review round, or review skipped, while
  coordination chatter stays (the reverted share in `ledger_tool.py stats`
  is the number that shows whether a saving cost quality)
- work packages of the wrong size: `ledger_tool.py stats` shows compactions
  on most PRs or a third round on routine PRs (too big), or many one-line PRs
  each from a fresh thread (too small)
- plans and round reports without a current three-line handoff
- a coordinator rule that forbids compaction outright, or one that has the
  coordinator compact after a long wait instead of before it
- `cache_ttl_minutes` that does not match how the owner pays (60 on a
  subscription, 5 on an API key or usage credits)

Then the text every thread reads at its start. Flag:

- threads told to read the whole ruleset instead of their extract
  (`rules/<role>.yaml`), or extracts that are missing or out of step
- more than ~40 rules binding one role (its own plus those for all), or any
  rule over ~450 characters that could be two
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
- No rule or routine lets a thread change settings of the Claude app, the
  project, the account, the repository or the hosting; such changes are owner
  steps, named exactly.
- Owner hand steps are walked through in an assist thread, not in the
  coordinator chat; threads the owner must answer in are announced; no rule or
  routine has a password, key or token pasted into a chat.
- The coordinator is not a relay: fix lists go through round reports, status
  is read from ledgers and PR state. A coordinator rule that forwards
  per-PR messages is a token finding and a role finding.
- Authority stays where it belongs: scope, the roadmap, acceptance contracts
  and sign-off at the last critical round with the owner; drafting them with specify, which
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
- Was the contract approved by the owner's own message, and does that message
  name the hash? Did the owner's pick-up message name it too? In a repo,
  does the working copy equal the copy on the default branch (lint C039;
  `git fetch` first)? Is there a pickup record (`approved_contracts` in the state
  file, a D-entry in the decision log) with the same hash? A contract whose
  three hashes agree but whose text differs from what the PRs were reviewed
  against is the case to look for by reading, since a thread that can write
  all three files could have changed them together.
- Were the verify steps shown to the owner (the hand-back used `brief
  --owner`), and does any of them run a command the owner would not expect?

Propose rewritten criterion text with a verify step for each one that fails.

Issues and roadmap, after `contract_tool.py roadmap --plans`:

- Does `plans/issues-<contract id>.json` name an issue for every work package,
  with no package created twice? Do the GitHub issues still match
  `contract_tool.py issues` for the approved version? An issue whose criteria text differs from the contract has drifted;
  the contract wins.
- Is there an issue or PR for work that no approved criterion covers, or an
  `active` milestone whose contract the coordinator never picked up (no
  D-number)?
- Does `project-state.yaml` list the same active milestones as `roadmap.yaml`?
- Do `superseded` versions and `dropped` milestones still have open PRs with
  no owner decision (`PLAN-05`)?

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
