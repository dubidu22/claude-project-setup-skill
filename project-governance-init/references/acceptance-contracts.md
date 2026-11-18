# Acceptance contracts: research, criteria, freeze

How a milestone's acceptance contract is drafted, approved, changed and closed
(rules `ROLE-10`, `PLAN-03` to `PLAN-05`, `REV-03`). Init scaffolds this file
into the workspace as `tools/acceptance-contracts.md` for the coordinator and
the acceptance thread; the audit judges existing contracts against it.
`tools/contract_tool.py` checks the mechanical part. Run the tool, do not read
its source.

## Contents
1. Why contracts
2. Who does what
3. The seven steps
4. Writing a good criterion
5. Research categories
6. Changing an approved contract
7. Closing a milestone
8. Token budget

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
| Interview | coordinator, with the owner | `PLAN-03` | researches or drafts criteria itself |
| Research, draft, lint | acceptance thread (fresh, on the `implementation_and_critical_review` model) | `ROLE-10` | approves, or talks to the owner |
| Approval | owner | `ROLE-03` | — |
| Record approval (status, D-number, hash) | coordinator | `PLAN-03` | edits criteria |
| Plans and PR proof per criterion | implementation threads | `PLAN-04` | changes a criterion |
| Confirm claimed criteria | review threads | `REV-03` | accepts a claim without proof |
| Close the milestone | coordinator | `PLAN-05` | closes with an open must criterion |

A dispatcher, where one exists, has no part in acceptance contracts.

The acceptance thread hands back one file and the output of
`contract_tool.py summary` (four lines: goal, criteria counts, assumptions,
sources). The coordinator never needs the research itself.

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
   this contract). `could` items leave the contract before approval and become
   GitHub issues per `GH-01`, so nothing researched is lost.
5. **Lint:** `python3 tools/contract_tool.py lint plans/contract-<NNN>-<slug>.yaml`.
   Fix every ERROR; look at every WARN.
6. **Owner approval.** The coordinator presents: the goal sentence, the
   `must` list, the assumptions, and the cut `could` items, as a decision card
   with a recommendation. Only the owner's own message approves. The
   coordinator then sets `status: approved`, fills `approval` (owner, date,
   D-number, and `hash` from `contract_tool.py hash`) and logs the D-entry.
   From then on lint fails if a criterion, its verify step, the goal or the
   core probe is edited in place.
7. **Freeze and execute.** From now on criteria change only by a new version
   (section 6). Implementation plans cite the ids they cover and threads read
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

Approved criteria are frozen (`PLAN-03`). If one turns out wrong:

1. The thread that found it stops work on that criterion and reports it with
   evidence (why it is wrong or impossible).
2. The coordinator has an acceptance thread draft version N+1: copy the file,
   bump `contract.version`, set `status: draft`, clear `approval`, record the
   change in `changes`.
3. Owner approval, a new D-number and a new hash, exactly as in step 6. The old version
   gets `status: superseded`.

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

- **Drafting.** Research stays in the acceptance thread; only the four-line
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
