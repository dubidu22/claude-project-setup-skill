# plans/

Working documents shared between threads. One file per unit of work, numbered
so that order is obvious at a glance.

| File | Written by | When |
|------|-----------|------|
| `contract-<NNN>-<slug>.yaml` (later versions `-v<N>`) | specify thread drafts, owner approves | before the first plan of a milestone (`PLAN-03`) |
| `plan-<NNN>-<lane>-<slug>.md` | implementation thread | before writing tests or code |
| `review-pr<N>-round<K>.md` | review thread | end of every review round |
| `batch-<NNN>.md` | coordinator composes; dispatcher (if any) keeps it current | when a batch is composed |

An acceptance contract states the milestone's goal sentence, sourced criteria
(each with a `verify` step), a core probe, work packages and the owner's approval; start from
`contract-template.yaml` and check it with `python3 tools/contract_tool.py lint`.
Approved contracts are frozen by `approval.hash`: a change is a new version with
a new D-number. Worker threads read `contract_tool.py brief`, not the whole file;
run the tool, never read its source.
Every plan and round report ends with a three-line handoff, kept current:
`Goal:` what this thread is for, `Done:` what is finished and where,
`Next:` the next step. A fresh thread starts from those three lines (`THR-07`).

A plan states: goal, the contract criterion ids it covers, lane and labels,
files it expects to touch, tests it will add first, open questions. A round report states: head SHA, verdict, verified
checks, numbered findings (B/M must-fix, S should-fix, N note) and, on the next
round, how each finding was answered (fixed with test proof, deferred with issue
link, or declined with reason).

Re-read a file right before writing to it; several threads share this folder.
