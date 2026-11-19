# How to run {{project_name}} and prove that it works

Status: **draft**. Nothing below has been executed yet.

This is the runbook a thread follows to prove behaviour a user can see
(`VER-01`): start the product, use it the way a user would, keep the
evidence, clean up. It is written for a thread that reads it cold, in the
middle of a task. The first implementation thread whose work has
user-visible behaviour fills it in from the repository, runs it once from
start to finish, and only then changes the status line to
"proven on <date> by <PR>". Until that run has happened this file is a
draft and no proof may rest on it.

Fill every section from what the repository actually contains: its scripts,
its ports, its selectors. Ask the owner only for what cannot be read from
the code (accounts, seed data, licences). If the checkout does not build or
start, fix that first or report it; do not write the runbook around it.

## Surface

What a user touches: web UI, command line, desktop app, API, mobile app or
library. Name the main one and list the others.

## Start

- The exact command that starts or builds it, and how long it takes.
- The signal that it is ready (a line in the output, a port that answers,
  an exit code).
- It must reach a usable state from an empty data folder: migrations, seed
  data and sign-in included.
- Whether two copies can run side by side. If not, say so here, because two
  lanes will try.

## Health check

A read-only check that the running copy is worth using before any journey
starts: the process is the one this run started, the version is the one
under test, the port belongs to it, sign-in works.

## Drive

How to act as a user. Use what the repository already has before anything
generic: its end-to-end tests, its helper scripts, a debug port, endpoints
that can be called. Prefer stable handles (labels, test ids, routes,
prompts) over coordinates and tab order. If a helper script is added, it is
executable and its exact call is shown here.

## Evidence

What to capture, and where it is kept so that it survives cleanup
(`{{workspace_root}}/plans/evidence/pr<N>/`).

What counts as proof:

- The real path a user takes. No internal setter, no test-only endpoint, no
  direct write to the database to get past a step.
- The actions and the state that results from them: a screenshot or
  recording, a terminal transcript, a response body, a log line, an exit
  code, a row in the database.
- Side effects are checked where they land (the file exists, the mail was
  queued, the row changed), not assumed from a success message.
- Mocks only at boundaries the product already has in production.
- A "dry run" mode is checked by looking at what it did (files, network,
  git refs), not trusted by its name.

## Cleanup

Stop only what this run started, by its process id or handle, never by
process name. Remove the copies and scratch data of this run. Keep the
evidence. Cleanup also runs after a failed attempt.

## What is not proven here

Anything shown only in a stand-in environment (a local database instead of
the hosted one, a fake payment provider): list the steps the real target
will not repeat. Those stay unproven until someone runs them there.
