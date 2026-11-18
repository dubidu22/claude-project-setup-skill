---
name: project-governance-init
description: >
  Set up or audit governance for a project run by several Claude threads (a coordinator
  chat plus implementation, review, KB and audit threads working through lanes, PR review
  rounds and a decision log). Use it whenever the user wants to bootstrap a new multi-thread
  Claude project, write or regenerate `claude-project-rules.yaml` / `project-state.yaml`,
  pick a token-economy profile (frugal / balanced / max_velocity), route models to roles,
  define execution lanes and `lane:*` labels, set autonomy limits and owner sign-off gates,
  draft coordinator project instructions, or scaffold plans/, kb/, ledgers and labels.
  Also use it to draft, research, lint or change a milestone's acceptance contract
  (researched, sourced acceptance criteria with verify steps, owner approval, /goal line).
  Also use it to audit, lint, clean up or find contradictions in an existing project
  ruleset, rules YAML or CLAUDE.md governance section, or when threads waste tokens on
  stale rules. Trigger even for short asks like "set up the coordinator", "new project
  rules", "governance for my repo" or "check my project rules".
---

# Project governance: initialize or audit

This skill produces and checks the two files that every thread of a
multi-thread Claude project reads: the static ruleset
`claude-project-rules.yaml` and the volatile `project-state.yaml`. Rendering is
done by scripts so that the output never drifts in syntax between projects;
your job is the conversation that fills in the config, and the judgement in an
audit. `references/governance-model.md` explains the system itself (roles,
lanes, criticality, replacement, why model routing and token economy are
separate); read it when you need to explain a trade-off or justify a default.

## Pick the mode

- **Mode A, new project** (default): the user wants rules for a project that
  has none, or wants to regenerate them from scratch.
- **Mode B, audit**: there is already a `claude-project-rules.yaml` (or rules
  living in `CLAUDE.md` / project instructions) and the user wants it checked
  for contradictions, stale state or token bloat.
- **Mode C, acceptance contract**: a milestone or feature needs its definition
  of done: interview, researched criteria, owner approval, frozen contract.
- **Regenerate**: a `governance-config.json` exists and the user wants a
  setting changed. Edit the JSON, re-run the generator, and run the audit
  script on the result. No walkthrough needed.

## Mode A: the walkthrough

### Before stage 1: look at the repository

If a repo or workspace is reachable, read `pyproject.toml` / `package.json` /
`Cargo.toml`, the top-level layout, and `.github/workflows/*.yml` first. From
that, pre-fill: stack preset, fast checks (the linters and test commands the
project already runs), target platforms (the CI matrix), and candidate lanes
(top-level packages or apps). Say what you detected and where. A recommendation
grounded in the repo is worth far more than a generic default.

### Pace: one stage at a time, with a recommendation

Present each stage as: what it decides, the trade-off in two or three
sentences, your recommendation with the values filled in, and the question.
Then wait. The owner is making decisions that will bind many future threads;
walking them through six stages in one message makes them rubber-stamp it.

**Fast path.** If the user has already supplied the answers, says "use your
defaults", or cannot reply in this session, do not stall: collapse the stages
into one summary table of every value you intend to use, state which were
given, detected or defaulted, and proceed to generation. The one-stage-at-a-time
rule exists to get real decisions, not to block when there is nobody to decide.

### The stages

1. **Identity and environment**: project name, `owner/repo`, public or private
   (public repos get free Actions minutes, which makes CI offloading cheap),
   owner name, GitHub handle, IANA timezone, local OS/shell and clone path,
   stack preset (`python_cli_or_service`, `fullstack_web`, `custom`), target CI
   platforms, and the **workspace root**: `/mnt/project-files` when the
   coordinator lives in a claude.ai Project, or a folder like `./governance`
   when everything lives in the repo and threads run in Claude Code.
2. **Model routing and token economy, decoupled**: three model slots
   (coordinator; implementation and critical review; standard review, audit
   and KB) and, separately, a token profile. Recommend `balanced`; offer
   `frugal` for solo or long-horizon projects and `max_velocity` when the
   owner is watching closely. Any single number may be overridden. The
   profile table is in the reference file, section 5.
3. **Autonomy and owner gates**: how far the coordinator may run on its own
   ("until v1.0", "per milestone"), the round-4 hard stop on critical PRs
   (recommend on), the physical/account steps only the owner can do, and the
   events that should ping the owner in chat.
4. **Execution lanes and file ownership**: concurrent lanes versus `lane:*`
   labels, the mapping note, confirmation that `lane:infra` is the lock for
   core and that docs need no lock, and whether a release-branch thread may
   run alongside the app/release lane.
5. **Quality gates and invariants**: zero-telemetry / `127.0.0.1` binding,
   banned licences (default AGPL, SSPL, non-commercial, unclear), and the
   project's own hard rules (layer order, determinism, schema compatibility).
   Phrase each invariant as a testable sentence; vague ones are ignored later.
   Also ask whether milestones need an owner-approved acceptance contract
   (`acceptance_contracts`, recommend yes; it adds `PLAN-03`, `PLAN-04`,
   `REV-03` and scaffolds the template and `tools/contract_tool.py`).
6. **Generate and scaffold** (below).

### Stage 6: generate, check, scaffold

1. Get the config shape with `python3 scripts/generate_project_rules.py
   --dump-schema`, then write the JSON with the agreed values. Only include
   keys you are setting; unknown keys are ignored with a warning.
2. Render:
   ```bash
   python3 scripts/generate_project_rules.py --from-json <config.json> --out-dir <workspace_root>
   ```
   This writes `claude-project-rules.yaml`, `project-state.yaml` and the
   normalized `governance-config.json` (keep it; it is how the rules get
   regenerated later).
3. Self-check the output before showing it:
   ```bash
   python3 scripts/audit_rules.py <workspace_root>/claude-project-rules.yaml --state <workspace_root>/project-state.yaml
   ```
   A fresh generation should come back clean. If it does not, fix the config,
   not the YAML.
4. Scaffold the workspace the rules point at (plans, KB with a D-001 entry,
   ledgers, coordinator instructions; `--github` adds `.github/lanes.yml` label
   definitions):
   ```bash
   python3 scripts/scaffold_workspace.py --from-json <workspace_root>/governance-config.json --out-dir <workspace_root> --github
   ```
   Existing files are kept unless `--force` is given.
5. Close with a short summary: where each file is, which values were
   detected versus defaulted, and the two things the owner must do by hand
   (paste `project_instructions.md` into the coordinator chat; create the
   labels from `lanes.yml`).

## Mode B: the audit

1. Run the mechanical pass first and read its output:
   ```bash
   python3 scripts/audit_rules.py <rules.yaml> [--state <state.yaml>] [--json]
   ```
   It finds duplicate ids, missing `applies_to`, undeclared labels, state
   leaking into rules, dead history, implausible thresholds and the common
   contradiction patterns. Exit code 1 means at least one error.
2. Read `references/audit-checklist.md` and work through the semantic checks
   it lists: the contradiction pairs, scope correctness, token bloat. Also
   read the repo's `CLAUDE.md` and recent decision-log entries, because rules
   most often contradict those rather than each other.
3. Write the report in the exact format the checklist gives (Verdict, Must
   fix, Should fix, Token savings, Mechanical findings, Next step). Quote the
   rule ids on both sides of every contradiction and propose replacement text,
   not just the complaint.
4. If `governance-config.json` is present, offer to fix by editing the config
   and regenerating rather than hand-editing YAML.

## Mode C: acceptance contract

Read `references/acceptance-contracts.md` first; it holds the method, the
criterion rules and the research categories. In short:

1. **Interview** the owner one question at a time, each with your
   recommendation: who uses it, what must be better than today, how it is
   reached, hard constraints, out of scope. Skip what the repo already answers.
   If nobody can answer in this session, take the fast path: mark those
   criteria `source.kind: assumption` and list them at the top of your reply.
2. **Research** best-practice criteria per category. Open the pages you use and
   record each URL with its retrieval date; no network means saying so, never
   filling the gap from memory.
3. **Draft** `plans/contract-<NNN>-<slug>.yaml` from
   `assets/templates/plans/contract-template.yaml`: binary criteria, a verify
   step each, a core probe. Keep `status: draft`.
4. **Pareto cut**: `must` / `should` / `could`; `could` items leave the
   contract and become issues before approval.
5. **Lint** until there are no errors:
   ```bash
   python3 scripts/contract_tool.py lint plans/contract-<NNN>-<slug>.yaml
   ```
6. **Hand back**, not approve: give the output of `contract_tool.py summary`,
   the assumptions and the cut items. Only the owner's own message approves
   (`ROLE-03`); then set `status: approved`, fill `approval` with the D-number,
   and print the loop line for implementation threads:
   ```bash
   python3 scripts/contract_tool.py goal plans/contract-<NNN>-<slug>.yaml --turns 30
   ```

Inside a multi-thread project, the drafting runs in a fresh worker thread
(`PLAN-03`) and the workspace copy `tools/contract_tool.py` is used instead of
`scripts/`. To change an approved contract, write a new version; never edit it
in place.

## Things that are easy to get wrong

- Lanes are concurrency slots; labels are file ownership. Do not generate one
  label per lane and call it done; the mapping note is where the thinking goes.
- Rules bind threads; state describes today. If a value will change before
  the next milestone, it belongs in `project-state.yaml`.
- Keep personal details (owner name, timezone, clone path) in the config, not
  in rule prose you write by hand; the generator places them where threads
  expect them.
- A contract you drafted is never approved by you, the coordinator or the
  review thread. Leave `status: draft` until the owner says so.
- Modifying the ruleset later is itself critical (`META-01`). Mention this
  when handing over, so the owner knows why threads will refuse to edit it.
