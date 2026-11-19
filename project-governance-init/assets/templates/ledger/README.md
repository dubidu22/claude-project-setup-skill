# ledger/ — one small file per PR and per review round

The ledger is what the coordinator and the dispatcher read instead of chat
messages. Each entry is its own file with one writer, so two threads never
edit the same file. Nobody maintains a table by hand; print one when needed:

    python3 tools/ledger_tool.py table      # PRs and rounds as tables
    python3 tools/ledger_tool.py stats      # rounds per PR, compactions per PR, PRs per thread
    python3 tools/ledger_tool.py check      # entries with missing or malformed fields
    python3 tools/ledger_tool.py gate 12    # may PR 12 be merged? (run before every merge, MRG-01)

| File | Writer | Written |
|------|--------|---------|
| `prs/pr-<N>.yaml` | the implementation thread that opened PR N | when the PR opens; `compactions` updated at its hand-offs |
| `rounds/pr<N>-round<K>.yaml` | the review thread | at the end of round K; `merged` filled in after the merge |
| `reverts/pr-<N>.yaml` | the review thread that merges the revert | when merged PR N is reverted |
| `audits/batch-<NNN>.md` | the audit thread | after a merged batch (`ROLE-09`) |

`prs/pr-<N>.yaml`:

```yaml
pr: 12
opened: 2026-01-31
thread: impl-app_cli-2        # the name this thread was started under
lane: app_cli
labels: "lane:cli"
<!-- if:acceptance_contracts -->
package: import               # work package key from the acceptance contract
<!-- endif -->
plan: plans/plan-003-app_cli-import.md
critical: no                  # the author's statement from the plan (CRIT-01)
compactions: 0                # how often this thread's context was compacted while on this PR
```

`rounds/pr<N>-round<K>.yaml`:

```yaml
pr: 12
round: 1
date: 2026-02-01
thread: review-1
head: 3f9c2ab
critical: no                  # round 1: the reviewer's own finding from the diff (CRIT-03)
verdict: changes_requested    # approved | changes_requested
must_fix: 2                   # open B/M findings after this round
should_fix: 1
kinds: "timer-workaround, missing-test"   # a short name per kind of finding, reused across PRs (REV-05)
report: plans/review-pr12-round1.md
merged: ""                    # merge commit SHA, last round only
```

`reverts/pr-<N>.yaml`:

```yaml
pr: 12                        # the merged PR that was reverted
date: 2026-02-09
by: "#19"                     # the PR or commit that reverted it
reason: "import broke files with a BOM"
```

What the numbers are for:

- **Merge go.** A PR may be merged only when its latest round has
  `must_fix: 0` (`MRG-01`).
<!-- if:dispatcher -->
  The dispatcher grants merge go only when round 1 says `critical: no`
  (`ROLE-11`); everything else goes to the coordinator.
<!-- endif -->
- **Quality.** `stats` shows the share of merged PRs that were reverted.
  Faster or cheaper is only better if this number does not go up.
- **Repeated findings.** `stats` lists finding kinds that came up in more
  than one PR. The same correction twice means the fix belongs in a check
  (lint rule, type, test, CI check) or in the design, not in another review
  comment (`REV-05`, `META-03`).
- **Replacement.** A worker thread is replaced after `replace_after_prs` PRs
  (`THR-02`); `stats` counts them per `thread`.
- **Package size.** A work package that regularly causes a compaction or a
  third review round is too big; a run of one-line PRs from fresh threads is
  too small.
- **Model routing.** A cheaper routine model only pays off if rounds per PR
  do not go up; compare `stats` before and after a routing change.

Tables from an older setup (`implementation.md`, `review.md`) are history:
keep them, do not add to them.
