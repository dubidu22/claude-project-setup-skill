# Acceptance contracts: research, criteria, freeze

Read this before Mode C, or when a thread asks how a contract is drafted,
approved or changed. It describes the method behind `PLAN-03`, `PLAN-04` and
`REV-03`; `scripts/contract_tool.py` checks the result mechanically (the scaffold copies it
to `<workspace_root>/tools/` so every thread can run it).

## Contents
1. Why contracts
2. Who does what
3. The seven steps
4. Writing a good criterion
5. Research categories
6. Changing an approved contract
7. Closing a milestone

---

## 1. Why contracts

A plan says *how* a thread will build something. A contract says *when it is
done*, in terms the owner agreed to before any code exists. Without it, review
rounds argue about "done" instead of checking it, and every thread reads the
milestone goal a little differently. With it, "done" is a list of binary checks
that a `/goal` loop, a reviewer and CI can all run.

The method combines two sources: the goal-engine flow (interview, research
best-practice criteria, versioned contract, approval, autonomous build until the
criteria hold) and the evidence discipline of sourced legal gates (every
researched claim carries a source and a retrieval date; a missing source is
reported, never papered over).

## 2. Who does what

| Step | Thread | Why there |
|------|--------|-----------|
| Interview | coordinator, with the owner | the owner's answers are scope (`AUTO-02`) |
| Research + draft | a fresh worker thread on the `implementation_and_critical_review` model | research pages never enter the coordinator's context |
| Lint | the drafting thread, then the coordinator | `contract_tool.py lint` must be clean before the owner sees it |
| Approval | owner only (`ROLE-03`) | acceptance criteria are product scope |
| Logging | coordinator: D-number for the approval | `KB-01` |
| Execution | implementation threads, optionally via `/goal` | plans cite criterion ids (`PLAN-04`) |
| Verification | review threads (`REV-03`), CI | claimed criteria are re-run, not believed |

The drafting thread hands back one file and a three-line summary (criteria
count by priority, open assumptions, sources used). The coordinator never needs
the research itself.

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
   D-number) and logs the D-entry.
7. **Freeze and execute.** From now on criteria change only by a new version
   (section 6). Implementation plans cite the ids they cover. A thread working
   in Claude Code can run the loop with the line printed by
   `python3 tools/contract_tool.py goal <contract> [--ids AC-3,AC-4] [--turns N]`.

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

Go through each category that applies and note which ones you skipped and why.
This is where the hidden criteria live.

| Category | Typical criteria |
|----------|------------------|
| Happy path | the core flow end to end, with real-looking data |
| Input validation | empty, too long, wrong type, wrong encoding, duplicates |
| Error states | network down, disk full, permission denied, partial failure; message names the cause and the fix |
| Data and persistence | survives restart, migration forward and back, backup/restore, concurrent writes |
| Security and privacy | authN/authZ if more than one user, secrets never logged, OWASP items relevant to the surface, no telemetry (`INV-03`) |
| Accessibility | keyboard-only use, contrast, screen-reader names (WCAG 2.2 AA where a UI exists) |
| Performance budgets | explicit numbers on named hardware or the CI runner |
| Platform | each target platform in `project_profile.target_platforms` |
| Operability | logs, exit codes, `--help`, config errors, upgrade path |
| Licences and dependencies | `INV-01`; new dependencies named in the contract if the milestone needs them |

## 6. Changing an approved contract

Approved criteria are frozen (`PLAN-03`). If one turns out wrong:

1. The thread that found it stops work on that criterion and reports it with
   evidence (why it is wrong or impossible).
2. The coordinator drafts version N+1: copy the file, bump `contract.version`,
   set `status: draft`, record the change in `changes`.
3. Owner approval and a new D-number, exactly as in step 6. The old version
   gets `status: superseded`.

Never edit an approved file in place; a criterion that silently changes after
review is the failure this whole method exists to prevent.

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
