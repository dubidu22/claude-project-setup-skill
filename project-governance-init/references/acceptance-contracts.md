# Acceptance contracts: research, criteria, freeze

How a feature idea or plan change becomes an acceptance contract, work
packages and a roadmap update, and how a contract is approved, changed and
closed (rules `ROLE-10`, `PLAN-03` to `PLAN-05`, `REV-03`). Specify follows
this method; the audit judges contracts against it. Init scaffolds this file
into the workspace as `tools/acceptance-contracts.md`. `tools/contract_tool.py`
checks the mechanical part. Run the tool, do not read its source.

## Contents
1. Why contracts
2. Who does what
3. The seven steps
4. Writing a good criterion
5. Research categories
6. Changing an approved contract
7. Closing a milestone
8. Token budget
9. Work packages and issues
10. The roadmap

---

## 1. Why contracts

A plan says *how* a thread will build something. A contract says *when it is
done*, in terms the owner agreed to before any code exists. Without it, review
rounds argue about "done" instead of checking it, and every thread reads the
milestone goal a little differently. With it, "done" is a list of binary checks
that a `/goal` loop, a reviewer and CI can all run.

Naming: the ruleset already uses "contract" for layer and external contracts
(`CRIT-01`, `AUTO-02`). This document always means the *acceptance contract*,
and rule text spells it out.

The method combines two sources: the goal-engine flow (interview, research
best-practice criteria, versioned contract, approval, autonomous build until the
criteria hold) and the evidence discipline of sourced legal gates (every
researched claim carries a source and a retrieval date; a missing source is
reported, never papered over).

## 2. Who does what

One owner per step; no step has two.

| Step | Who | Rule | Never |
|------|-----|------|-------|
| Interview, research, draft, work packages, roadmap update, lint | specify thread (its own chat, on the `specify` model) | `ROLE-10` | approves; touches rules, state, code or D-numbers |
| Approve the contract; say yes to creating issues | owner | `ROLE-03` | — |
| Record the approval (status, date, hash, the owner's message); create issues and record their numbers | specify thread, on the owner's own message that names the hash | `ROLE-10` | edits the contract afterwards |
| Tell the coordinator to pick the contract up, naming its hash | owner | `ROLE-03` | — |
| Pick up: check the contract against the hash the owner named (`contract_tool.py pickup`), record the printed line in the state file and the pending decisions, mirror the roadmap's active milestones, batch work packages by lane | coordinator | `PLAN-03` | picks up without the owner's hash; interviews, researches or edits the contract |
| Compile the pending pickup entry into the decision log | KB thread | `ROLE-08` | changes the hash or the quote |
| Plans and PR proof per criterion | implementation threads | `PLAN-04` | changes a criterion |
| Confirm claimed criteria | review threads | `REV-03` | accepts a claim without proof |
| Close the milestone; handle dropped work | coordinator | `PLAN-05` | closes with an open must criterion |

A dispatcher, where one exists, has no part in acceptance contracts.

The coordinator reads the output of `contract_tool.py summary` (five lines:
goal, criteria counts, assumptions, sources, and the pickup line to record)
and never needs the interview or the research.

## 3. The seven steps

1. **Interview, one question at a time, each with a recommendation.** Ask only
   what the repo and earlier contracts cannot answer. The three questions that
   shape most criteria:
   - Who uses it? (only the owner / a few known people / the public: decides
     login, roles, privacy and abuse criteria)
   - What must be better than today when it is done? (the goal sentence)
   - How is it reached and run? (CLI, browser, phone, offline, which OS)
   Then: hard constraints (budget, data that must never leave the machine,
   deadlines) and what is explicitly out of scope.
   **Fast path:** if the owner cannot answer in this session, draft with stated
   assumptions (`source.kind: assumption`) and list them at the top of the
   hand-back. The owner resolves them at approval.
2. **Research best-practice criteria per category** (section 5). Search,
   then open the pages you take criteria from; a search snippet is not a source.
   Record `source.ref` (URL) and `source.retrieved` (YYYY-MM-DD). Prefer
   standards, official docs and well-maintained guides (OWASP, WCAG, platform
   guidelines, the framework's own docs) over blog lists. No network: say so in
   the hand-back and mark the category "not researched"; never fill it from
   memory and call it researched.
3. **Draft** criteria that pass section 4. Typical size: 10 to 30 `must`
   criteria per milestone. A login alone can produce fifty candidates; that is
   what step 4 is for.
4. **Pareto cut.** Tag each criterion `must` (the milestone fails without it),
   `should` (in this contract, may be deferred with an issue) or `could` (not in
   this contract). `could` items move to the contract's `cut` list with a reason
   before approval and become `backlog` issues (section 9), so nothing
   researched is lost. Then group the rest into work packages (section 9) and
   update the roadmap (section 10).
5. **Lint:** `python3 tools/contract_tool.py lint plans/contract-<NNN>-<slug>.yaml`
   and `python3 tools/contract_tool.py roadmap roadmap.yaml --plans plans`.
   Fix every ERROR; look at every WARN.
6. **Owner approval.** The specify thread presents: the goal sentence, the
   whole contract as `contract_tool.py brief <contract> --owner` prints it
   (scope, every criterion with its verify step, the core probe, the cut
   items, the hash), the assumptions, the roadmap change and the issue
   titles. The owner approves by quoting the hash ("approved 3fa9c1d2e4b7"),
   so the yes is tied to exactly what was shown, verify commands included.
   The specify thread then sets `status: approved` and fills `approval.by`,
   `date`, `hash` and `owner_message`. Section 6 says what is frozen from
   then on and how that is checked.
7. **Pickup and execution.** The owner tells the coordinator "pick up <id>
   <hash>", with the hash they approved. The coordinator runs
   `contract_tool.py pickup <contract> --hash <hash> --decision D-<n>`: it
   lints the contract, compares its content with the hash the owner named
   (and, in a repo, with the copy on the default branch) and only then prints
   the pickup line `<id> v<version> D-<n> hash <hash>`. The coordinator
   records that line in `approved_contracts` of the state file and in
   `kb/pending-decisions.md`; the KB thread compiles it into the decision
   log. Naming the hash at pickup closes the gap between approval and pickup,
   when no record exists yet to compare with. The coordinator never writes
   into the contract. `contract_tool.py goal` refuses a contract without that record,
   so no loop starts on a contract the coordinator has not seen. Implementation plans cite the ids they cover and threads read
   `python3 tools/contract_tool.py brief <contract> [--ids AC-3,AC-4]` instead
   of the whole file. A thread working in Claude Code can run the loop with the
   line printed by `python3 tools/contract_tool.py goal <contract> [--ids ...]
   --turns <goal_turn_cap>`.

## 4. Writing a good criterion

A criterion is one observable, binary statement with a way to check it.

| Property | Bad | Good |
|----------|-----|------|
| Observable | "The import is robust" | "Importing a CSV with a missing column exits 2 and names the column" |
| Binary | "Startup is fast" | "`app --help` returns in under 300 ms on the CI runner" |
| Atomic | "Users can log in and reset passwords securely" | two criteria, each with its own check |
| Checkable | "Data is safe" | "After `kill -9` during write, the database passes `PRAGMA integrity_check`" |

`verify.type` is one of:
- `test`: an automated test; `verify.how` names the test or test file.
- `command`: a command and its expected result.
- `inspection`: a reviewer checks a named artefact (file, config, header) against
  a stated condition. Use sparingly.
- `manual`: only the owner can check it (device, hearing, real account). These
  become owner hand steps; keep them under about a third of the contract.

Words that make a criterion untestable unless a number or a concrete condition
follows them: fast, quick, easy, simple, intuitive, user-friendly, robust,
secure, safe, clean, nice, good, proper(ly), appropriate(ly), reasonable,
seamless, modern, efficient, scalable, reliable, as expected, works.
The lint script warns on them unless the criterion holds a measurement or a
comparison ("under 300 ms", "exits 2", "at most 3 retries"); a bare number
such as a version ("Python 3") does not count.

## 5. Research categories

Go through every category. Each one needs at least one criterion or an entry
in `research.categories_skipped` as `name: reason`; lint warns otherwise. This
is where the hidden criteria live. The category keys are the names in
parentheses.

| Category | Typical criteria |
|----------|------------------|
| Happy path (`happy_path`) | the core flow end to end, with real-looking data |
| Input validation (`input_validation`) | empty, too long, wrong type, wrong encoding, duplicates |
| Error states (`error_states`) | network down, disk full, permission denied, partial failure; message names the cause and the fix |
| Data and persistence (`data_persistence`) | survives restart, migration forward and back, backup/restore, concurrent writes |
| Security and privacy (`security_privacy`) | authN/authZ if more than one user, secrets never logged, OWASP items relevant to the surface, no telemetry (`INV-03`) |
| Accessibility (`accessibility`) | keyboard-only use, contrast, screen-reader names (WCAG 2.2 AA where a UI exists) |
| Performance budgets (`performance`) | explicit numbers on named hardware or the CI runner |
| Platform (`platform`) | each target platform in `project_profile.target_platforms` |
| Operability (`operability`) | logs, exit codes, `--help`, config errors, upgrade path |
| Licences and dependencies (`licences_dependencies`) | `INV-01`; new dependencies named in the contract if the milestone needs them |

## 6. Changing an approved contract

Approved criteria are frozen (`PLAN-03`). A change comes from the owner (new
wish) or from a thread that found a criterion wrong or impossible (it stops
work on that criterion and reports the evidence to the coordinator, who asks
the owner). Either way the change goes through specify:

1. Copy the file to `contract-<NNN>-<slug>-v<N>.yaml`, bump
   `contract.version`, set `status: draft`, clear `approval`, and record what
   changed and why in `changes`. Research only what the change touches.
2. Owner approval and a new hash, as in step 6; the previous file gets
   `status: superseded`. The coordinator logs a new D-number on pickup.
3. If the new version removes a criterion that has open work, `PLAN-05`
   applies: no new work on it, open PRs finish their round, the owner decides
   per PR whether to merge or close.

Never edit an approved file in place; a criterion that silently changes after
review is the failure this whole method exists to prevent.

**What is frozen, and how it is checked.** The hash covers the goal, users,
access, constraints, out of scope, the core probe and every criterion with
its priority and verify step. Work packages, sources and the cut list are
not part of it. A hash stored in the contract alone would prove nothing,
since whoever edits a criterion can recompute it. So the same hash is kept
in three places with three different writers, and `contract_tool.py lint`
and `goal` compare them:

| Where | Written by | Lint finding if it disagrees |
|---|---|---|
| `approval.hash` in the contract | specify thread | C027: edited in place |
| `approval.owner_message` (the owner's "approved <hash>") | specify thread, quoting the owner | C038: the message approves something else |
| `approved_contracts` in the state file, and the decision log | coordinator, then KB thread | C037: differs from what was picked up |
| the copy on the default branch (in a repo) | the owner's merged pull request | C039: differs from the copy the owner reviewed |

The fourth is the strong one. With an in-repo workspace, contracts reach the
default branch only by pull request, and with CODEOWNERS and required
code-owner review that pull request needs the owner's review. Threads work
on the governance branch, which is not protected, so the tool does not trust
the copy there: `lint`, `goal` and `pickup` compare an approved contract
with `origin/<default_branch>` (run `git fetch` first) and fail if it
differs, if its approval fields differ, or if it is not on that branch at
all. Rewriting the contract, the owner's message and the pickup record
together on the governance branch therefore no longer passes.

In a claude.ai Project there is no git and no such barrier. There the three
records make a silent change take coordinated edits in files owned by other
roles, which the audit looks for, and the hash the owner names again at
pickup ties the pickup to their approval; but a thread that rewrites all of
them after pickup is caught only by someone reading the files.

A contract approved under an older tool version carries a hash that does not
cover users, access, constraints and out of scope. Lint reports that as a
warning (C027) and names the full hash; the next version gets it.

## 7. Closing a milestone

A milestone is done when, in one session or one CI run on the merge commit:

- every `must` criterion is shown passing by its `verify` step,
- every `should` criterion is passing or has a linked `deferred` issue,
- the `core_probe` passes,
- the coordinator records the result as a D-entry with the run's link or output.

The `core_probe` is the one check that proves the goal sentence itself, end to
end, from a fresh clone (for example: "fresh clone, follow README, import the
sample file, the report shows 12 rows"). Unit tests can all be green while the
core probe fails; that is why it is separate.

## 8. Token budget

Contracts cost tokens three times: drafting, reading, verifying. Keep each small.

- **Drafting.** Interview and research stay in the specify thread; only the four-line
  summary reaches the coordinator. Open at most two sources per category and
  stop a category when a source adds no new `must` candidate. On the `frugal`
  profile, research only the categories the interview made relevant and skip
  the rest with a reason.
- **Reading.** Worker threads read `contract_tool.py brief --ids ...` (id,
  priority, text, verify step), not the YAML with its sources and history.
  Nobody reads the tool's source.
- **Verifying.** Reviewers take a criterion's proof from CI output when CI
  already ran its verify step, and re-run only what CI did not cover. `/goal`
  loops stop at `execution_profile.token_economy.goal_turn_cap` turns.
- **Size.** Aim for 10 to 30 `must` criteria; lint warns above 40. A criterion
  nobody would notice failing is a `could`.

## 9. Work packages and issues

A contract's `work_packages` group its `must` and `should` criteria into a few
units of work, each with one `lane:*` label. They exist so that GitHub issues
can be generated instead of written: `contract_tool.py issues <contract>`
prints one issue draft per package (title, label, milestone, the criteria as a
checklist with their verify steps, and a pointer to the contract version and
hash) and one `backlog` draft per `cut` item.

- Size a package as one unit of work: one thread can finish it without
  compacting and without a long wait, it ends in one PR, and a reviewer can
  check it in one round (`PLAN-04`). Too small wastes the fixed cost of
  starting a thread; too large costs more than proportionally, because a long
  thread re-reads its growing history every turn, is likelier to compact, and
  produces a diff that needs more review rounds.
- As a rule of thumb, about six criteria per package at most (lint warns
  above that; `--max-package-criteria` changes it) and at most eight packages
  per milestone. A milestone that needs more is two milestones.
- Split by what can be built and reviewed on its own, inside one lane label,
  not just by lane: "import with validation" and "report" rather than
  "everything in lane:cli". Do not go down to one package per criterion.
- `after: [key]` on a package says it cannot start before another one is
  merged. Use it only for real dependencies; unordered packages can run in
  parallel lanes.
- The numbers are starting points. The ledger entries record compactions
  per PR and rounds per PR (`ledger_tool.py stats`): packages that
  regularly cause a compaction or a third round are too big for this project.
- Every `must` and `should` criterion is in exactly one package; lint fails
  otherwise.
- An issue cites criteria, it never defines them. The contract is the only
  place a criterion is written, because issues can be edited by anyone and
  nothing freezes them. To change a criterion, change the contract.
- Each package's label must be one of the ruleset's file-ownership labels;
  lint checks it against `claude-project-rules.yaml`.
- Issues are created only after the owner's explicit yes, after approval,
  and only after the pre-flight: `contract_tool.py issues <contract>
  --preflight` names the labels and milestones the issues need; if one is
  missing on GitHub, nothing is created until it exists (labels:
  `github-setup/create-labels.sh`; milestones are an owner hand step).
- Every created issue is recorded at once with `contract_tool.py
  record-issue <contract> <package key> <number>` (in
  `plans/issues-<contract id>.json`). `issues` then marks each draft
  `create`, `exists` (skip) or `replaces #N` (the package had an issue from
  an earlier version), and lists issues whose package is gone. A second run
  therefore creates nothing twice, and a new version says exactly which
  issue numbers it affects; closing or editing those is the owner's call.
- Regrouping packages does not change the hash: it covers what done means,
  not how the work is cut.

## 10. The roadmap

`roadmap.yaml` in the workspace root is the ordered list of milestones:
`name`, `goal` (one sentence), `status` (`planned`, `active`, `done`,
`dropped`) and `contract` (its id). Order is priority.

- The owner decides it; a specify thread is its only writer. The coordinator
  mirrors the `active` entries into `project-state.yaml` on pickup and, when
  it closes a milestone (`PLAN-05`), records that in `closed_milestones`
  there and in the decision log; the next specify run sets `done` in the
  roadmap.
- A milestone turns `active` only together with an approved contract.
  `contract_tool.py roadmap roadmap.yaml --plans plans` checks this, along
  with duplicate names, dropped milestones that still have an approved
  contract, and contracts for milestones that are not on the roadmap.
- Reordering, postponing or dropping needs no research and no contract
  change, only the owner's decision. Dropping a milestone with open work
  triggers `PLAN-05`.
- Keep it short: one entry per milestone, no task lists. Tasks are the work
  packages of the milestone's contract.
