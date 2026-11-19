# Feature map — {{project_name}}

What the product does, seen from the user's side, with one name per feature.
Plans, acceptance criteria, review findings and the owner all use these
names, so nobody has to guess what "the thing in the left sidebar" is.

One file per user-facing feature, `<feature>.md`, with four sections:

- `## Sub-features`: the parts a user would name separately.
- `## How to get to it`: every entry point, from the user's point of view.
  A proof through one convenient entry point does not cover the others.
- `## Driving it`: the steps from `../verification.md` that exercise it, and
  the observable end state that shows it works.
- `## Gotchas`: preconditions, seed data it needs, known traps. If a journey
  cannot pass because a precondition is missing, it fails and the reason is
  written here; it is never weakened until it passes. A trap is written as
  `- <trap> (#<issue that removes it>)` or `- <trap> (stays: <why>)`. A
  gotcha list is where problems wait to be fixed in the product, not a
  place to learn to live with them: a thread that hits a trap reports it,
  it does not memorise a way around it.

Start with the three to five features users rely on most; add a file when a
PR adds a feature. The PR that adds or changes a user-facing feature updates
its file in the same change (`VER-01`).

| Feature | File | Last proven |
|---------|------|-------------|
| | | |
