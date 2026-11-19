# kb/ — knowledge base for {{project_name}}

Durable project knowledge that every new thread reads before acting:

- `decision-log.md` — every decision, owner or Claude, newest first (critical
  only for process/architecture changes; routine batch entries are exempt).
- `architecture.md` — layer order, contracts, invariants (critical).
- `process.md` — how batches, reviews and releases run here (critical).

- `pending-decisions.md` — decisions made but not yet in the log. The
  coordinator is its only writer.

The KB thread is the only writer of `decision-log.md`. On the cadence set by
`execution_profile.token_economy.kb_pr_cadence` it compiles the entries of
`pending-decisions.md` into the log, unchanged and in D-number order
(`ROLE-08`), and it never edits the pending file; the coordinator removes
entries from there once they are in the log.
<!-- if:in_repo -->
The log changes by a decision-log pull request to `{{default_branch}}`, which
the KB thread merges itself without code review. The pending file is a working
file on branch `{{governance_branch}}` (`THR-13`).
<!-- endif -->
<!-- if:!in_repo -->
In a claude.ai Project there are no pull requests: the KB thread writes the
log file directly, without code review.
<!-- endif -->
Changes to the other KB documents are critical and go through normal review.

An entry that records an owner decision quotes the owner's message and its
date; without the quote it ranks as a Claude decision (`KB-01`). The owner's
newest message on a point outranks older entries (`ROLE-01`).
<!-- if:acceptance_contracts -->

When the coordinator picks up an acceptance contract it records
`<contract id> v<version> D-<n> hash <hash>` in `approved_contracts` of the
state file and as a pending decision, with the owner's pick-up message.
Compile that entry unchanged: `contract_tool.py lint` compares contracts
with it.
<!-- endif -->
