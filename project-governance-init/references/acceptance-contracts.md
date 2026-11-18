# Acceptance contracts: research, criteria, freeze

How a feature idea or plan change becomes an acceptance contract, work
packages and a roadmap update, and how a contract is approved, changed and
closed (rules `ROLE-10`, `PLAN-03` to `PLAN-06`, `REV-03`). Specify follows
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
| Interview, research, draft, work packages, roadmap update, lint | specify thread (its own chat, on the `implementation_and_critical_review` model) | `ROLE-10` | approves; touches rules, state, code or D-numbers |
| Approve the contract; say yes to creating issues | owner | `ROLE-03` | — |
| Record the approval (status, date, hash); create issues | specify thread, on the owner's own message | `ROLE-10` | edits criteria afterwards |
| Pick up: lint, log the D-number, mirror the roadmap into the state file, batch work packages by lane | coordinator | `PLAN-03` | interviews, researches or edits criteria |
| Plans and PR proof per criterion | implementation threads | `PLAN-04` | changes a criterion |
| Confirm claimed criteria | review threads | `REV-03` | accepts a claim without proof |
| Close the milestone; handle dropped work | coordinator | `PLAN-05`, `PLAN-06` | closes with an open must criterion |

A dispatcher, where one exists, has no part in acceptance contracts.

The coordinator reads the output of `contract_tool.py summary` (four lines:
goal, criteria counts, assumptions, sources) and never needs the interview or
the research.

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
   `must` list, the assumptions, the cut items, the roadmap change and the
   issue titles. Only the owner's own message approves. The specify thread
   then sets `status: approved` and fills `approval.by`, `date` and `hash`
   (from `contract_tool.py hash`). From then on lint fails if a criterion, its
   verify step, the goal or the core probe is edited in place.
7. **Pickup and execution.** The coordinator lints the contract, logs the
   approval as a D-number (in `approval.decision` and the decision log) and
   batches the work packages. `contract_tool.py goal` refuses a contract
   without a D-number, so no loop starts on a contract the coordinator has not
   seen. Implementation plans cite the ids they cover and threads read
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
The lint script warns on them.

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
3. If the new version removes a criterion that has open work, `PLAN-06`
   applies: no new work on it, open PRs finish their round, the owner decides
   per PR whether to merge or close.

Never edit an approved file in place; a criterion that silently changes after
review is the failure this whole method exists to prevent, and `approval.hash`
makes lint catch it.

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

- Batch by lane, not by criterion: three to six packages per milestone. The
  ruleset batches PRs by lane (`LANE-01`); issues follow the same grain.
- Every `must` and `should` criterion is in exactly one package; lint fails
  otherwise.
- An issue cites criteria, it never defines them. The contract is the only
  place a criterion is written, because issues can be edited by anyone and
  nothing freezes them. To change a criterion, change the contract.
- Issues are created only after the owner's explicit yes, after approval. On
  a new contract version, regenerate the drafts and tell the owner which
  existing issues they replace; closing or editing those is the owner's call.
- Regrouping packages does not change the hash: it covers the goal, the core
  probe and the criteria, not how the work is cut.

## 10. The roadmap

`roadmap.yaml` in the workspace root is the ordered list of milestones:
`name`, `goal` (one sentence), `status` (`planned`, `active`, `done`,
`dropped`) and `contract` (its id). Order is priority.

- The owner decides it; a specify thread edits it; the coordinator mirrors
  the `active` entries into `project-state.yaml` on pickup and sets `done`
  when it closes a milestone (`PLAN-05`). Nobody else writes it.
- A milestone turns `active` only together with an approved contract.
  `contract_tool.py roadmap roadmap.yaml --plans plans` checks this, along
  with duplicate names, dropped milestones that still have an approved
  contract, and contracts for milestones that are not on the roadmap.
- Reordering, postponing or dropping needs no research and no contract
  change, only the owner's decision. Dropping a milestone with open work
  triggers `PLAN-06`.
- Keep it short: one entry per milestone, no task lists. Tasks are the work
  packages of the milestone's contract.
