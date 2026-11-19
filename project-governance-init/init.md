# Init: set up, change or migrate a project's governance

Produces the files every thread of a multi-thread Claude project reads: the
static ruleset `claude-project-rules.yaml`, a per-role extract of it for each
thread type (`rules/<role>.yaml`), the volatile `project-state.yaml`, and the
shared workspace around them. Rendering is done by scripts so the output never
drifts between projects; your job is the conversation that fills in the
config. `references/governance-model.md` explains the system (roles, lanes,
criticality, coordinator load, operating mechanics, acceptance contracts);
read it when you need to explain a trade-off or justify a default.

Pick the section by what exists:

| What exists | Section |
|---|---|
| no ruleset | the stages below |
| a `governance-config.json` | "Changing settings" |
| a ruleset but no `governance-config.json` (older or hand-edited setup) | "Migrating an existing ruleset" |

## Where to run this

Run init in its own chat, never in the coordinator chat. The coordinator
lives for the whole project and is never replaced, so a six-stage interview
held there stays in its context for good. If you are called in the
coordinator chat, say in one line that setup runs in a separate thread and
that the questions will be asked there, then hand over. A short settings
change that needs one preview and one yes may be prepared in a worker thread
the same way; the coordinator only receives the hand-over lines.

## Before stage 1: look at the repository

If a repo or workspace is reachable, read `pyproject.toml` / `package.json` /
`Cargo.toml`, the top-level layout, and `.github/workflows/*.yml` first. From
that, pre-fill: stack preset, fast checks (the linters and test commands the
project already runs), target platforms (the CI matrix), candidate lanes
(top-level packages or apps), and whether an automated layer-boundary check
exists (`layer_boundary_check`). Say what you detected and where. A
recommendation grounded in the repo is worth far more than a generic default.

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
   when everything lives in the repo and threads run in Claude Code. The root
   sets `environment` (`claude_ai_project` or `claude_code`), which decides
   how threads are started and how shared files travel (reference file,
   section 10). For an in-repo workspace also confirm `default_branch` and the
   `governance_branch` that working files are committed on (default
   `governance`).
2. **Model routing and token economy, decoupled.** The owner chooses the
   models; never fill them in silently. Show the three presets from
   `generate_project_rules.py --model-presets` (`economy`, `balanced`, `max`) as one decision card with
   your recommendation, then let the owner change any of the six slots:
   coordinator; specify; critical work; routine implementation; routine
   review, KB and audit; operations (dispatcher, assist). Ask for the names as
   the owner's model picker shows them and write them as given; preset names
   carry no version numbers on purpose, so do not invent any. Say the two
   things that matter when picking: the reviewer of critical work should not
   be weaker than its author, and a cheaper routine model only pays off if it
   does not need more review rounds (`ledger_tool.py stats` shows rounds per
   PR). If routine implementation runs on a weaker model than critical work, a PR
   with must-fix findings after `escalate_after_round` rounds (default 2,
   0 = never) moves to a fresh thread on the critical-work model and gets
   `rounds_after_escalation` more rounds (default 2) before it stops for the
   coordinator (`REV-04`).
   On the fast path use `balanced` and name it as an assumption in the
   hand-over. Separately, a token profile. Recommend `balanced`; offer
   `frugal` for solo or long-horizon projects and `max_velocity` when the
   owner is watching closely. Any single number may be overridden. The
   profile table is in the reference file, section 5. Also ask how the owner
   pays, because it sets `cache_ttl_minutes`: 60 on a Pro/Max subscription
   (recommend, and assume it on the fast path), 5 on an API key or usage
   credits. The cache-aware rules (`THR-07` to `THR-11`) depend on it
   (reference file, section 9). In Claude Code only,
   `coordinator_compact_every_batches` (default 1, 0 = never) is how often the
   coordinator hands the owner a planned `/compact` line at a batch end.
3. **Autonomy and owner gates**: how far the coordinator may run on its own
   ("until v1.0", "per milestone"), the review round at which a critical PR
   stops for the owner (`token_cfg.critical_max_review_rounds`, default 4; the
   stop itself cannot be turned off), the physical/account steps only the
   owner can do, and the events that should ping the owner in chat.
4. **Execution lanes and file ownership**: concurrent lanes versus `lane:*`
   labels and the mapping note. Recommend keeping `lane:infra` as the lock for
   shared core files and `lane:docs` so docs need no lock; the lane rule is
   written from the labels that actually exist. Whether a release-branch
   thread may run in addition to the lane threads. Also `dispatcher`: a
   second, disposable thread for per-PR operations. Recommend on: the
   coordinator lives for the whole project and should never compress, and the
   dispatcher is what keeps per-PR traffic out of it. Off only for a small
   project with one or two lanes (reference file, section 1).
5. **Quality gates and invariants**: what counts as critical here
   (`critical_areas`; the default list is generic, so add the project's own,
   for example "golden/regression files" or "user-file deletion paths") and,
   for an in-repo workspace, `critical_paths` (globs that CI labels
   `risk:high`); zero telemetry (`no_telemetry`) and, where there is a local
   web UI, `local_ui_loopback_only`; banned licences (default AGPL, SSPL,
   non-commercial, unclear); and the project's own hard rules (layer order,
   determinism, schema compatibility). Phrase each invariant as a testable
   sentence; vague ones are ignored later. Ask for standing formatting wishes
   (`owner_prefs`, a list of sentences) instead of assuming any, and set
   `github_rest_only` only if the threads' GitHub access blocks GraphQL.
   Also ask whether milestones need an owner-approved acceptance contract
   (`acceptance_contracts`, recommend yes; it adds `ROLE-10`, `PLAN-03` to
   `PLAN-05`, `REV-03` and scaffolds the roadmap, the template and
   `tools/contract_tool.py`).
6. **Generate and scaffold** (below).

## Stage 6: generate, check, scaffold

1. Get the config shape with `python3 scripts/generate_project_rules.py
   --dump-schema`, then write the JSON with the agreed values. Only include
   keys you are setting; unknown keys are ignored with a warning. Values are
   type-checked: switches are `true` / `false`, numbers are whole numbers,
   lists are JSON lists. A wrong value stops the run with exit code 2 and a
   message; nothing is written.
2. Render:
   ```bash
   python3 scripts/generate_project_rules.py --from-json <config.json> --out-dir <workspace_root>
   ```
   This writes `claude-project-rules.yaml`, `rules/<role>.yaml` (one extract
   per thread type), `project-state.yaml` and the normalized
   `governance-config.json` (keep it; it is how the rules get regenerated
   later). The generator parses its own output before saving it.
3. Self-check the output before showing it:
   ```bash
   python3 scripts/audit_rules.py <workspace_root>/claude-project-rules.yaml --state <workspace_root>/project-state.yaml
   ```
   A fresh generation should come back without errors. If it does not, fix
   the config, not the YAML. A warning about a label the mapping note
   mentions but the label list lacks means the note needs rewording.
4. Scaffold the workspace the rules point at (plans, KB with a D-001 entry,
   the ledger folder and its reader, coordinator instructions; `--github`
   adds `github-setup/` with a label script and, for an in-repo workspace, a
   CODEOWNERS snippet and labeler files):
   ```bash
   python3 scripts/scaffold_workspace.py --from-json <workspace_root>/governance-config.json --out-dir <workspace_root> --github
   ```
   Existing files are kept unless `--force` is given.
5. Close with a short summary: where each file is, which values were
   detected versus defaulted, and what the owner must do by hand. Nothing in
   this list is done for them (`ROLE-14`):
   - paste `project_instructions.md` into the coordinator chat, and
     `dispatcher_instructions.md` into the dispatcher chat if there is one,
     each started on the model its slot names;
   - run `github-setup/create-labels.sh`;
   - in-repo workspace: create the `governance_branch`, add the CODEOWNERS
     lines and require code-owner review on the default branch (this is what
     makes contract approval and ruleset changes the owner's own review), and
     copy the labeler files if `critical_paths` is set;
   - quote their go for the setup into D-001 of the decision log;
   - when a contract is approved, tell the coordinator "pick up <id> <hash>"
     with the hash they approved;
   - optional: a scheduled task that sends the dispatcher (or the
     coordinator) "watchdog check", if stalled threads should be noticed
     while nobody is active.

## After generation: how work gets in

With `acceptance_contracts` on, the scaffold puts `roadmap.yaml`, the method
(`tools/acceptance-contracts.md`), the template
(`plans/contract-template.yaml`) and the checker (`tools/contract_tool.py`)
into the workspace. Say in the hand-over how the owner starts and changes
work: open a new chat and specify the first milestone ("specify: <idea>");
read the whole contract view there and approve it by quoting its hash; tell
the coordinator to pick it up. Plan changes go the same way. Do not write
criteria or roadmap goals as part of init.

Tell the owner that walkthroughs for their own hand steps (accounts, hosting,
keys, repository settings) open in an assist thread, and that the coordinator
says so when it starts one.

Also pass on three owner habits that save the most (reference file, section
9): do not poke a thread that has been silent for longer than the cache
lifetime, tell the coordinator once and let it start a fresh one; send the
coordinator one message with everything rather than several across the day;
and run Claude Code worker threads in the CLI rather than the Desktop Code tab
where there is a choice.

## Changing settings

The owner asks for a change in plain words ("switch to the economy models",
"be more frugal", "turn the dispatcher off"). Translate it, show what it does,
wait for their yes, apply it, and say what happens next. Never edit the rules
file or an extract by hand.

**This changes files, nothing else.** A settings change rewrites
`claude-project-rules.yaml`, the extracts in `rules/`, `governance-config.json`
and the generated instruction files. It never changes anything in the Claude
app, the project or the account: not the default model, not a chat's model,
not permissions or connectors, even when a tool for that is available. "Switch
to the economy models" means the routing in the rules file, where only some
thread types move to the cheaper model; it does not mean setting the
project's default model. Which model a chat runs on is switched by the owner;
list those switches as their steps in the hand-over.

| The owner wants | `--set` |
|---|---|
| another model preset | `model_preset=economy` (or `balanced`, `max`) |
| one model changed | `coordinator_model=...`, `specify_model`, `critical_model`, `implementation_model`, `review_model`, `ops_model` |
| another token profile | `profile_key=frugal` (or `balanced`, `max_velocity`) |
| one token number | `token_cfg.max_concurrent_lanes=2`, `token_cfg.watchdog_interval_minutes=90`, `token_cfg.replace_after_prs=3`, ... |
| dispatcher on or off | `dispatcher=true` / `false` |
| escalation to the stronger model | `escalate_after_round=2` (0 = never; capped at the profile's review rounds for routine PRs), `rounds_after_escalation=2` |
| the round a critical PR stops at | `token_cfg.critical_max_review_rounds=4` (the stop itself stays) |
| cache lifetime, planned compaction | `cache_ttl_minutes=60`, `coordinator_compact_every_batches=1` (Claude Code only) |
| acceptance contracts on or off | `acceptance_contracts=true` / `false` |
| another stack preset | `stack_key=fullstack_web`: replaces lanes, labels, mapping note and checks unless set in the same call |
| a list | `'ownership_labels=["lane:app","lane:docs"]'`, `'owner_prefs=["..."]'`, `'critical_paths=["src/core/**"]'` |

Switches take exactly `true` or `false`, numbers whole numbers, lists a JSON
list; anything else is refused with exit code 2 and nothing is written.
Other keys: `--dump-schema` lists them; set them the same way.

1. **Preview.** Say in one line what you are about to change, then:
   ```bash
   python3 scripts/generate_project_rules.py --from-json <ws>/governance-config.json \
     --out-dir <ws> --set model_preset=economy --dry-run
   ```
   Show the owner the "what changed" list in plain words (settings, rules
   added or removed, rules that now bind another role). A preset, profile or
   stack replaces the stored values that depend on it; single values set in
   the same call win.
2. **Stop and wait for the owner's yes.** The request is not the go: the
   owner has not yet seen what it changes. Apply only after an explicit yes to
   the preview, or when their message already said to apply without asking.
   Then run the same command without `--dry-run`. Only the owner's own message
   counts (`META-01`, `ROLE-03`). `project-state.yaml` is kept as it is,
   because it holds live state. The ruleset's `date` is today's and its
   `version` goes up by one minor step whenever the content changed.
3. **Refresh the generated files** (never ledger entries, the decision log or
   the roadmap) and self-check:
   ```bash
   python3 scripts/scaffold_workspace.py --from-json <ws>/governance-config.json --out-dir <ws> --refresh
   python3 scripts/audit_rules.py <ws>/claude-project-rules.yaml --state <ws>/project-state.yaml
   ```
4. **Hand over what happens next**, in a few lines:
   - The generator prints a decision-log entry for the change. Give it to the
     owner for the coordinator, with the owner's yes quoted in it: a ruleset
     change is critical (`META-01`) and is logged with the next D-number
     (`KB-01`). You do not write the decision log yourself.
   - If the workspace lives in the repo, the change goes in as a PR the owner
     merges.
   - Tell the coordinator: "The ruleset changed to version <v>. Log it, then
     re-read your extract and the state file." If `project_instructions.md`
     changed, paste the new one into the coordinator's project instructions.
   - Model changes apply to threads started from now on. A running thread
     keeps its model until it is replaced at its next hand-off (`THR-09`).
     Name every switch the owner has to make themselves in the app (a new
     coordinator model in the coordinator chat, a default model if they want
     one); do not make it for them.
   - Dispatcher turned on: open a dispatcher chat with
     `dispatcher_instructions.md`. Turned off: close it after its batch.
   - A cheaper routine model is a bet: compare review rounds per PR
     (`ledger_tool.py stats`) after the next batch.

## Migrating an existing ruleset

For a project that already runs on a ruleset but has no
`governance-config.json`: an older setup, or one that was edited by hand.
Nothing live is overwritten before the owner has seen the difference.

1. **Derive the config** from what is there. This writes only the file named
   by `--out`:
   ```bash
   python3 scripts/generate_project_rules.py --derive-config <ws>/claude-project-rules.yaml \
     --state <ws>/project-state.yaml --out /tmp/derived-config.json
   ```
   It prints what it could not find (defaults were used) and every rule in
   the old file that the generator does not produce and would therefore
   drop. Go through that list with the owner: a dropped rule that still
   matters becomes a `custom_invariants` entry or one of the options
   (`owner_prefs`, `critical_areas`, `github_rest_only`,
   `local_ui_loopback_only`); the rest is dropped on purpose.
2. **Preview** against the live ruleset; nothing is written:
   ```bash
   python3 scripts/generate_project_rules.py --from-json /tmp/derived-config.json --out-dir <ws> --dry-run
   ```
   Show the owner the settings that change, the rules added and removed, and
   the rules that are reworded. Expect several reworded rules: that is where
   hand edits and newer generator text differ. Read the reworded ones the
   owner cares about side by side (old file versus a render into a scratch
   folder) before going on.
3. **Wait for the owner's yes**, then generate for real (same command without
   `--dry-run`) and scaffold without `--force`:
   ```bash
   python3 scripts/scaffold_workspace.py --from-json <ws>/governance-config.json --out-dir <ws> --refresh
   ```
   What is kept untouched: `project-state.yaml`, the decision log and its
   D-numbers, plans, round reports, contracts, the roadmap and old ledger
   tables (history; new entries go to `ledger/prs/` and `ledger/rounds/`).
   Contracts approved under the older tool keep their hash; lint reports it
   as a warning, not an error, until their next version.
4. **Audit and hand over** as in "Changing settings", steps 3 and 4. The
   decision-log entry says "migrated to generator version <v>" and lists the
   dropped rules.

## Things that are easy to get wrong

- Lanes are concurrency slots; labels are file ownership. Do not generate one
  label per lane and call it done; the mapping note is where the thinking goes.
- Rules bind threads; state describes today. If a value will change before
  the next milestone, it belongs in `project-state.yaml`.
- Keep personal details (owner name, timezone, clone path) in the config, not
  in rule prose you write by hand; the generator places them where threads
  expect them.
- One duty, one role, and one writer per file. With a dispatcher, per-PR
  operations are the dispatcher's and nothing critical is; the state file is
  the coordinator's; ledger entries belong to the thread that did the work.
- Do not carry one project's habits into another. The generic defaults are
  deliberately plain; everything project-specific is an option the owner sets.
- Modifying the ruleset later is itself critical (`META-01`). Mention this
  when handing over, so the owner knows why threads will refuse to edit it.
