# Implementation ledger — {{project_name}}

One line per PR, appended by the implementation thread when the PR opens and
updated when it merges. Keeps the coordinator from re-deriving history.

`Package` is the work package key from the acceptance contract. `Compactions`
is how often the thread's context was compacted while it worked on this PR
(0 when none). Together with the rounds per PR in the review ledger this shows
whether work packages are sized right: a package that regularly causes a
compaction or a third review round is too big; a run of one-line PRs from
fresh threads is too small.

| Date | PR | Lane | Labels | Package | Plan | Critical | Compactions | Status |
|------|----|------|--------|---------|------|----------|-------------|--------|
