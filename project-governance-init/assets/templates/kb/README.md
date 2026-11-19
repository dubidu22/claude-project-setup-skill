# kb/ — knowledge base for {{project_name}}

Durable project knowledge that every new thread reads before acting:

- `decision-log.md` — every decision, owner or Claude, newest first (critical
  only for process/architecture changes; routine batch entries are exempt).
- `architecture.md` — layer order, contracts, invariants (critical).
- `process.md` — how batches, reviews and releases run here (critical).

The KB thread is the only writer of `decision-log.md`. It compiles pending
decisions into a decision-log PR on the cadence set by
`execution_profile.token_economy.kb_pr_cadence` and self-merges it. Changes to
the other KB documents are critical and go through normal review.

An entry that records an owner decision quotes the owner's message and its
date; without the quote it ranks as a Claude decision (`KB-01`). The owner's
newest message on a point outranks older entries (`ROLE-01`).
<!-- if:acceptance_contracts -->

When the coordinator picks up an acceptance contract it records
`<contract id> v<version> D-<n> hash <hash>` in `approved_contracts` of the
state file. Copy that line and the owner's approval message into the D-entry
unchanged: `contract_tool.py lint` compares contracts with it.
<!-- endif -->
