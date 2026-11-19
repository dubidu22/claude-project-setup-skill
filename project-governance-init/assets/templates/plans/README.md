# plans/

Working documents shared between threads. One file per unit of work, numbered
so that order is obvious at a glance. Every file has one writer; nobody edits
another thread's file (`THR-04`).

| File | Writer | When |
|------|--------|------|
<!-- if:acceptance_contracts -->
| `contract-<NNN>-<slug>.yaml` (later versions `-v<N>`) | specify thread drafts, owner approves | before the first plan of a milestone (`PLAN-03`) |
| `issues-<contract id>.json` | specify thread, through `contract_tool.py record-issue` | when an issue is created |
<!-- endif -->
| `plan-<NNN>-<lane>-<slug>.md` | implementation thread | before writing tests or code |
| `review-pr<N>-round<K>.md` | review thread | end of every review round |
<!-- if:dispatcher -->
| `batch-<NNN>.md` | coordinator composes it, then the dispatcher is its only writer | when a batch is composed |
<!-- endif -->
<!-- if:!dispatcher -->
| `batch-<NNN>.md` | coordinator | when a batch is composed |
<!-- endif -->
<!-- if:acceptance_contracts -->

An acceptance contract states the milestone's goal sentence, sourced criteria
(each with a `verify` step), a core probe, work packages and the owner's approval; start from
`contract-template.yaml` and check it with `python3 tools/contract_tool.py lint`.
An approved contract is frozen: its hash is in `approval.hash`, in the owner's
approval message and, after pickup, in `approved_contracts` of the state file,
and lint compares all of them. A change is a new version with a new D-number.
Worker threads read `contract_tool.py brief`, not the whole file;
run the tool, never read its source.
<!-- endif -->

Every plan and round report ends with a three-line handoff, kept current:
`Goal:` what this thread is for, `Done:` what is finished and where,
`Next:` the next step. A fresh thread starts from those three lines (`THR-07`).

A plan states: goal, {{plan_contract_clause}}lane and labels, whether the work is critical (`CRIT-01`),
files it expects to touch, tests it will add first, open questions. A round
report states: head SHA, verdict, in round 1 the reviewer's own finding on
whether the PR is critical (`CRIT-03`), verified checks, numbered findings
(B/M must-fix, S should-fix, N note) and, on the next round, how each finding
was answered (fixed with test proof, deferred with issue link, or declined
with reason). Each PR and each round also gets a ledger entry
(`../ledger/README.md`).
<!-- if:in_repo -->

These files are committed on branch `{{governance_branch}}` by their writer,
never on a product branch and never by force-push (`THR-13`). A thread that
works on a product branch keeps a second worktree for them:

    git worktree add ../<repo>-{{governance_branch}} {{governance_branch}}
<!-- endif -->
<!-- if:contracts_in_repo -->

Contracts are the exception: they change on `{{default_branch}}` by pull
request only, and the copy there is the one that counts (`THR-14`).
`contract_tool.py` compares an approved contract with `origin/{{default_branch}}`
(run `git fetch` first) and reports a copy that differs.
<!-- endif -->
