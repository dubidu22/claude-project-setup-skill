# kb/ — knowledge base for ledgerlite

Durable project knowledge that every new thread reads before acting:

- `decision-log.md` — every decision, owner or Claude, newest first (critical
  only for process/architecture changes; routine batch entries are exempt).
- `architecture.md` — layer order, contracts, invariants (critical).
- `process.md` — how batches, reviews and releases run here (critical).

The KB thread compiles pending decisions into a decision-log PR on the cadence
set by `execution_profile.token_economy.kb_pr_cadence` and self-merges it.
Changes to the other KB documents are critical and go through normal review.
