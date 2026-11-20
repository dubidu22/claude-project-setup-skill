# Eval results

The cases in `project-governance-init/evals/` test how an assistant behaves with the skill loaded. The unit
tests in `tests/` only prove that the scripts and the case files are well formed. **No eval run has been
recorded here yet**, so nothing in this repository shows how the skill behaves in a live session.

## The canary

Four cases that cover the four jobs and are cheap to run. Run these after every change to `SKILL.md`,
`init.md`, `specify.md` or `audit.md`; run all cases before a release.

| Case | What it guards |
|---|---|
| `routing-bare-invocation` | the skill offers its jobs and starts nothing |
| `init-stage-one-waits` | init asks first and does not generate on its own |
| `specify-approval-without-hash` | an approval that does not quote the contract hash is not recorded |
| `audit-asked-to-fix` | the audit reports and changes no file |

From inside `project-governance-init/` (this runs every case; pick the canary cases from the report):

```bash
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```

## Recording a run

One file per run, `eval-results/<YYYY-MM-DD>[-n].json`:

```json
{"date": "2026-11-21", "suite": "canary", "skill_commit": "abc1234", "model": "<model id>",
 "cases": [{"name": "routing-bare-invocation", "passed": true},
           {"name": "audit-asked-to-fix", "passed": false, "failure": "unclassified", "why": ""}]}
```

## Classify every failure before reading the numbers

A failed case has one of three causes, and only one of them is about the skill:

| `failure` | Meaning | What to do |
|---|---|---|
| `skill` | the assistant did the wrong thing because of what the skill says or leaves out | change the skill, rerun the case |
| `grader` | the assistant did the right thing and the grader marked it wrong | fix the grader; the result does not count against the skill |
| `harness` | the run broke: a missing tool, a timeout, a scaffold script that failed | fix the setup and rerun |

A pass rate that still contains `unclassified` failures says nothing. This order (classify first, then read
the numbers) follows the bench of the open project `Druthulu/ProjectArchitect`.
