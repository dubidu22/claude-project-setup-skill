---
name: specify
description: Turn a feature idea or a change of plans for {{name}} into GitHub issues with acceptance criteria the owner approves. Use only when the owner asks to specify something or asks for acceptance criteria.
argument-hint: <idea or change of plans>
---

# Specify: $ARGUMENTS

Work is started only from issues with acceptance criteria the owner approved. This turns an idea into such issues. It writes no code and changes no rules.

1. **Ask first, briefly.** At most three questions, only for what you cannot find in the repository: who it is for, what must not change, what is out of scope. Wait for the answers.
2. **Look before you write.** Read the code the idea touches and search the open issues for duplicates.
3. **Draft** one to five issues, each small enough for one PR. For each:
   - title `<area>: <outcome>`;
   - two to six acceptance criteria. Each is one observable behaviour with the step that proves it ("Given a PDF with two columns, `extract` returns the left column first; proved by `tests/test_columns.py`"). A criterion nobody can check is not one;
   - out of scope;
   - whether it touches a critical path{{#if has_lanes}} and which lane it belongs to{{/if}}.
4. **Show the owner every issue in full** and ask for a yes. Their request to specify is not the yes: they have not seen the criteria yet.
5. **Only after the yes:** create the issues in the milestone the owner names, and list their numbers. A change of plans edits the existing issue and adds a comment saying what changed and why.

Never start the work here; the lead picks the issues up.

<!-- {{mark}} -->
