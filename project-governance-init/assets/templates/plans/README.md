# plans/

Working documents shared between threads. One file per unit of work, numbered
so that order is obvious at a glance.

| File | Written by | When |
|------|-----------|------|
| `plan-<NNN>-<lane>-<slug>.md` | implementation thread | before writing tests or code |
| `review-pr<N>-round<K>.md` | review thread | end of every review round |
| `batch-<NNN>.md` | coordinator | when a batch is composed |

A plan states: goal, lane and labels, files it expects to touch, tests it will
add first, open questions. A round report states: head SHA, verdict, verified
checks, numbered findings (B/M must-fix, S should-fix, N note) and, on the next
round, how each finding was answered (fixed with test proof, deferred with issue
link, or declined with reason).

Re-read a file right before writing to it; several threads share this folder.
