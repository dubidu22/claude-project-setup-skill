# Init: set up or regenerate a project's governance

Produces the files every thread of a multi-thread Claude project reads: the
static ruleset `claude-project-rules.yaml`, the volatile `project-state.yaml`,
and the shared workspace around them. Rendering is done by scripts so the
output never drifts between projects; your job is the conversation that fills
in the config. `references/governance-model.md` explains the system (roles,
lanes, criticality, coordinator load, acceptance contracts); read it when you
need to explain a trade-off or justify a default.

**Regenerating.** If a `governance-config.json` already exists and the owner
wants a setting changed, skip the walkthrough: edit the JSON, run step 2 to 4
of stage 6 on it, and say what changed. Changing a live ruleset needs the
owner's approval (`META-01`).

## Before stage 1: look at the repository

If a repo or workspace is reachable, read `pyproject.toml` / `package.json` /
`Cargo.toml`, the top-level layout, and `.github/workflows/*.yml` first. From
that, pre-fill: stack preset, fast checks (the linters and test commands the
project already runs), target platforms (the CI matrix), and candidate lanes
(top-level packages or apps). Say what you detected and where. A recommendation
grounded in the repo is worth far more than a generic default.

## Pace: one stage at a time, with a recommendation

Present each stage as: what it decides, the trade-off in two or three
sentences, your recommendation with the values filled in, and the question.
Then wait. The owner is making decisions that will bind many future threads;
walking them through six stages in one message makes them rubber-stamp it.

**Fast path.** If the user has already supplied the answers, says "use your
defaults", or cannot reply in this session, do not stall: collapse the stages
into one summary table of every value you intend to use, state which were
given, detected or defaulted, and proceed to generation. The one-stage-at-a-time
rule exists to get real decisions, not to block when there is nobody to decide.

## The stages

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
   profile table is in the reference file, section 5. Also ask how the owner
   pays, because it sets `cache_ttl_minutes`: 60 on a Pro/Max subscription
   (recommend, and assume it on the fast path), 5 on an API key or usage
   credits. The cache-aware rules (`THR-07` to `THR-11`) depend on it
   (reference file, section 9). `coordinator_compact_at_tokens` (default
   50000, 0 = never) is the coordinator size above which it suggests a
   planned `/compact` at a pause or batch end.
3. **Autonomy and owner gates**: how far the coordinator may run on its own
   ("until v1.0", "per milestone"), the round-4 hard stop on critical PRs
   (recommend on), the physical/account steps only the owner can do, and the
   events that should ping the owner in chat.
4. **Execution lanes and file ownership**: concurrent lanes versus `lane:*`
   labels, the mapping note, confirmation that `lane:infra` is the lock for
   core and that docs need no lock, and whether a release-branch thread may
   run alongside the app/release lane. Also `dispatcher`: a second, disposable
   thread for per-PR operations. Recommend on: the coordinator lives for the
   whole project and should never compress, and the dispatcher is what keeps
   per-PR traffic out of it. Off only for a small project with one or two
   lanes (reference file, section 1).
5. **Quality gates and invariants**: zero-telemetry / `127.0.0.1` binding,
   banned licences (default AGPL, SSPL, non-commercial, unclear), and the
   project's own hard rules (layer order, determinism, schema compatibility).
   Phrase each invariant as a testable sentence; vague ones are ignored later.
   Also ask whether milestones need an owner-approved acceptance contract
   (`acceptance_contracts`, recommend yes; it adds `ROLE-10`, `PLAN-03` to
   `PLAN-06`, `REV-03` and scaffolds the roadmap, the template and
   `tools/contract_tool.py`).
6. **Generate and scaffold** (below).

## Stage 6: generate, check, scaffold

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
   (paste `project_instructions.md` into the coordinator chat, and
   `dispatcher_instructions.md` into the dispatcher chat if there is one;
   create the labels from `lanes.yml`).

## After generation: how work gets in

With `acceptance_contracts` on, the scaffold puts `roadmap.yaml`, the method
(`tools/acceptance-contracts.md`), the template
(`plans/contract-template.yaml`) and the checker (`tools/contract_tool.py`)
into the workspace. Say in the hand-over how the owner starts and changes
work: open a new chat and specify the first milestone ("specify: <idea>");
approve the contract there; tell the coordinator to pick it up. Plan changes
go the same way. Do not write criteria or roadmap goals as part of init.

Tell the owner that walkthroughs for their own hand steps (accounts, hosting,
keys, repository settings) open in an assist thread, and that the coordinator
says so when it starts one.

Also pass on three owner habits that save the most (reference file, section
9): do not poke a thread that has been silent for longer than the cache
lifetime, tell the coordinator once and let it start a fresh one; send the
coordinator one message with everything rather than several across the day;
and run Claude Code worker threads in the CLI rather than the Desktop Code tab
where there is a choice.

## Things that are easy to get wrong

- Lanes are concurrency slots; labels are file ownership. Do not generate one
  label per lane and call it done; the mapping note is where the thinking goes.
- Rules bind threads; state describes today. If a value will change before
  the next milestone, it belongs in `project-state.yaml`.
- Keep personal details (owner name, timezone, clone path) in the config, not
  in rule prose you write by hand; the generator places them where threads
  expect them.
- One duty, one role. With a dispatcher, per-PR operations are the
  dispatcher's and nothing critical is; do not leave a duty with both.
- Modifying the ruleset later is itself critical (`META-01`). Mention this
  when handing over, so the owner knows why threads will refuse to edit it.
