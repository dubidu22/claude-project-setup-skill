# The multi-thread governance model

Read this when you need to explain a stage's trade-offs, answer "why is it set
up like this?", or judge whether a rule in an existing ruleset still makes sense.
It describes the system the generator encodes, not the generator itself.

## Contents
1. Threads and roles
2. Lanes versus file-ownership labels
3. Criticality and review rounds
4. Context compression, replacement and the watchdog
5. Model routing versus token economy (why they are decoupled)
6. The five architectural invariants ("D-703")
7. What the generated files contain (rule catalog)
8. Acceptance contracts, issues and the roadmap
9. Cache-aware habits
10. Operating mechanics: starting threads, shared files, the watchdog
11. Authority order, and what is enforced by what
12. What the rules rest on: checks before prose

---

## 1. Threads and roles

A project runs as several Claude chats ("threads") in one claude.ai Project or
one repo, each with a role and a narrow remit:

| Role | Does | Never does |
|------|------|------------|
| **owner** (human) | sets goals, scope, milestones; performs hand steps (publishing, hardware tests, repo settings); gives sign-off | — |
| **coordinator** (lives for the whole project, never replaced) | splits work into lane batches, starts/replaces threads (or hands that to the dispatcher), approves plans, grants merge go, logs D-numbers, is the only writer of the state file; reads ledger entries and PR state instead of relaying messages | writes product code; approves scope changes or acceptance contracts |
| **dispatcher** (default on) | runs one batch at a time: starts, watches and replaces worker threads, keeps `batch-<NNN>.md` current, reads the ledger entries, grants merge go for PRs the review thread confirmed non-critical | approves plans, critical PRs or anything touching scope; decides criticality; writes ledger entries |
| **specify** (with acceptance contracts) | in its own chat: interviews the owner about a feature idea or plan change, researches and drafts the acceptance contract, groups work packages, updates the roadmap; shows the owner every criterion and verify step; records approval only on the owner's message that quotes the contract hash; creates issues on the owner's yes | approves anything itself; edits an approved contract; touches rules, state, code or D-numbers |
| **advisor** (default off) | a fresh, read-only session on a strong model, asked by the coordinator about one decision it would otherwise put to the owner, or a real open choice in a critical plan; answers with one recommendation and its reasons (`ROLE-18`) | decides anything; changes files; starts threads; is asked about routine plans, merges or verdicts |
| **assist** | walks the owner through one hand step (accounts, hosting, keys, repository settings) in its own thread, checks the result, reports the step done to the coordinator | has a secret pasted into chat; decides anything; writes the state file |
| **implementation** | reads KB + plan, states in the plan whether the work is critical, writes tests then code inside its lane, opens PRs, writes the PR's ledger entry, answers findings with exact fix lists | merges, pushes to the default branch, force-pushes |
| **review** | reviews a batch's PRs in rounds, decides in round 1 from the diff whether the PR is critical, writes round reports and round ledger entries, checks CI, squash-merges on go when no must-fix finding is open | authors the PR it reviews |
| **kb** | compiles decisions into the decision-log PR on the configured cadence and self-merges it | reviews code |
| **audit** | after a merged batch, scans the combined diff for cross-PR inconsistencies and contract touches | blocks merges |

Only the owner's own messages count as owner approval. Another thread's output
never does, which is why `ROLE-03` exists: without it a coordinator can talk
itself into "the review thread said it was fine".

Every rule has an `applies_to` scope from this list (or `all`). A rule without
a scope binds nobody. The generator writes one extract per thread type,
`rules/<role>.yaml`, with the project and execution profile and only the rules
scoped to that role or to `all`. A thread reads its extract at its start and
after a compression, not the whole ruleset: a KB or audit thread is bound by
about a quarter of the rules. The full file wins if the two ever differ, and
the audit checks that they do not (A12).

**Coordinator load.** The coordinator's own work is per batch (milestones, plan
approval, D-numbers, the owner); everything per PR is traffic. Two things keep
it small. First, by default: fix lists travel through round reports, threads
post one line per hand-off, and the coordinator reads ledger entries and PR state
instead of messages (`ROLE-04`, `THR-04`). Second, opt-in with `dispatcher:
true`: a dispatcher takes the per-PR operations (`ROLE-11`, `LANE-02`,
`THR-01`, `THR-03`). Because all of its state is in `batch-<NNN>.md`, it is
replaced after one batch or at its first compression (`THR-05`). The
dispatcher is on by default; turn it off only for a small project with one or
two lanes.

**Owner-facing work leaves the coordinator too.** The coordinator answers
short questions itself, but a hand step the owner wants to carry out (account,
hosting, SSH or repository settings, a deploy checklist) becomes an assist
thread (`ROLE-12`, `ROLE-13`): the walkthrough, the troubleshooting and the
screenshots would otherwise sit in the coordinator's context for the rest of
the project. Open hand steps are kept as titles in `owner_open_steps` in the
state file; the coordinator is that file's only writer, so the assist thread
reports a finished step and the coordinator removes it. Because work now starts in threads the owner may not be looking
at, the coordinator announces every thread the owner has to see or answer in,
and says when one is waiting for them (`THR-12`).

**Settings outside the files belong to the owner.** No thread changes the
Claude app, the project, the account, the repository or the hosting (default
model, a chat's model, permissions, secrets, branch protection): it names the
exact change and the owner makes it (`ROLE-14`). Model routing lives in the
rules file; which model a given chat runs on is switched by the owner.

**The coordinator is the one thread that is never replaced** (`THR-02`,
`THR-06`). It lives for the whole project and stays small: it reads summaries, ledger entries and state files only, hands every
lookup to a worker, and writes state to `project-state.yaml` and new decisions to
`kb/pending-decisions.md` at each hand-off, so that a compression, if one happens anyway,
loses nothing. Every other thread is disposable by design.

## 2. Lanes versus file-ownership labels

Two different things that are easy to conflate:

- **Execution lanes** are concurrency slots: `core_pipeline`, `app_cli`,
  `docs_release`. At most one implementation thread per lane at a time, and at
  most `max_concurrent_lanes` overall. They answer "how many threads can run?".
- **File-ownership labels** (`lane:core`, `lane:cli`, `lane:docs`, ...) are
  GitHub labels on PRs that say which files a PR may touch. They answer "may
  this PR edit that directory?". Several labels can map to one lane.

The `lane_mapping_note` records the mapping in prose so a new thread can
reason about it.

Two labels are special where a project has them (the presets do; `LANE-03` is
written from the labels that exist, so a project without them gets a plain
"one PR at a time for shared files" rule instead):
- `lane:core` marks shared, cross-cutting files. Touching them is critical and
  requires `lane:infra`, which acts as a single-thread lock: while an infra PR
  is open, no other lane touches core.
- `lane:docs` may be added by any lane without taking the lock, so that
  documentation never queues behind infrastructure.

## 3. Criticality and review rounds

A change is **critical** when it touches one of the project's
`critical_areas` or carries `risk:high` (`CRIT-01`). The default areas are
generic: layer contracts, core data structures, KB process/architecture docs,
packaging/release/CI, safety mechanisms, licences, network calls. A project
adds its own (golden files, deletion paths, a payment module).
Critical work gets: coordinator plan approval before coding, implementation
and review on the stronger model, exact fix lists, issues for every deferred
finding, and the full multi-platform CI matrix on its final round.

**Who decides.** The author states it in the plan. The review thread decides
it again in round 1, from the diff and whatever the plan says, and records
`critical: yes|no` in the round report and the round's ledger entry
(`CRIT-03`); in doubt it is critical. A PR found critical without an approved
plan stops for the coordinator. Where `critical_paths` is set, CI labels PRs
touching those paths `risk:high` and no thread removes that label. This
matters most with a dispatcher: it runs on the cheapest model and grants
merge go only for PRs the review thread confirmed non-critical, so the
classification never rests on the dispatcher or on the author alone.

Reviews run in **rounds**. Each round produces a report (head SHA, verdict,
numbered findings B/M must-fix, S should-fix, N note), and the author answers
each finding as fixed-with-proof, deferred-with-issue, or declined-with-reason.

**What happens when the rounds run out** (`REV-01`, `REV-04`, `MRG-01`):

- Nothing merges with an open must-fix finding. Merge go requires the latest
  round to show none.
- A non-critical PR runs up to `non_critical_max_review_rounds`. Should-fix
  leftovers are then deferred to issues. Must-fix findings are never deferred.
- If routine implementation runs on a weaker model than critical work,
  `REV-04` comes first: a PR with must-fix findings after
  `escalate_after_round` goes to a fresh thread on the critical-work model
  and gets `rounds_after_escalation` more rounds. Still open after that, or
  no escalation configured: the PR stops for the coordinator.
- A critical PR runs up to `critical_max_review_rounds` (4 by default), then
  stops and **waits for the owner**: that many rounds without convergence
  means the thread pair is stuck, and burning more tokens on it is the one
  thing that will not help. The round is a setting; the stop is not.

## 4. Context compression, replacement and the watchdog

Long chats get compressed; after compression a thread remembers less than it
thinks it does, and it does not reliably know how often it was compressed.
Replacement therefore rests on what the files show (`THR-02`): a worker
thread is retired once it has handled `replace_after_prs` PRs, counted from
its ledger entries (`ledger_tool.py stats`). `replace_at_compressions` stays
as a second trigger for a thread that does notice a compression. The
replacement happens **at the next hand-off**, after the current atomic step
(a review round, a fix commit, a KB PR) completes. Replacing mid-step loses the
step's working state and produces half-written reports or orphaned branches.

The **watchdog** (`THR-03`) is a check, not a timer: no thread is woken by a
clock. Each time the dispatcher (or the coordinator, without one) is active,
it takes the time from a tool and looks at the newest commit or file change
of every thread that owes output. Only when nothing moved for
`watchdog_interval_minutes` does it act: a nudge while the cache is warm, a
fresh thread from the files once it is not; after `watchdog_max_nudges`
without progress it replaces the thread or escalates. If stalled threads
should be noticed while nobody is active, the owner sets up a scheduled task
that sends "watchdog check"; without one the interval is a lower bound.
Shorter intervals cost tokens; longer ones cost wall-clock time.

**Fitness check** (`THR-01`): before a thread receives a second batch it
states its current plan and open items from memory, and the answer is
compared with its plan file and ledger entries. A mismatch means replacement.

## 5. Model routing versus token economy

These are configured separately because they answer different questions:

- **Model routing** is about judgement: which model runs each kind of thread.
  Changing it changes *quality*.
- **Token economy** is about spend and pace: concurrency, replacement
  threshold, watchdog cadence, review-round caps, audit depth, KB cadence,
  reporting verbosity, CI offloading. Changing it changes *cost and speed*.

The owner picks the models at setup. Six slots, because they need different
strengths:

| Slot | Runs | What it needs |
|---|---|---|
| `coordinator` | the one long-lived chat | judgement in few, short turns |
| `specify` | interview, research, acceptance criteria | the strongest reasoning: every thread builds on its output |
| `critical_work` | implementation and review of critical PRs, escalations | strong; a critical reviewer is never weaker than the author |
| `implementation` | routine implementation | can be cheaper: frozen criteria, verify steps, CI and review catch its misses |
| `review_kb_audit` | routine review, KB, audit | can be cheaper |
| `operations` | assist | mechanical work; the cheapest that follows instructions |

The **dispatcher** has no slot to choose. It runs on the strongest model among
the threads it starts (critical work, implementation, review), shown as the
`dispatcher` line in `model_routing`, because a session can start sessions
only on its own model or a cheaper one. This was found in a live project: a
Sonnet dispatcher could not start Opus workers, and the owner had to paste a
starter block for each. A dispatcher on the workers' model still saves: its
context lasts one batch, while the coordinator's lasts the project.
`dispatcher_model` may name a stronger model; the generator refuses a weaker
one and the audit flags an older ruleset where it is weaker (A18).

**Planner and router on different models.** By default the coordinator is
the strongest judgment in the project. A project that wants its strongest
model for judgment only, and not for the turns that route work, can run the
coordinator one tier lower and turn on the **advisor** (`advisor: true`,
`advisor_model`, default the critical-work model). The coordinator then asks
the advisor in a fresh session about the few decisions that need it
(`ROLE-18`), with a brief of the question, the options and the evidence, and
records the answer in `kb/pending-decisions.md`. The specify and
critical-work slots already put the strongest model on planning and hard
reviews; the advisor covers the ad-hoc decision in between. It is not worth
having on the coordinator's own model, and the generator refuses that. Put
together with the dispatcher on the workers' model, the strongest model
then spends its tokens on plans, contracts, critical work and a handful of
decisions per batch.

Presets (`economy`, `balanced`, `max`) fill the slots and every slot can be
changed; names carry no version numbers so they do not go stale. A cheaper
routine model is a bet that it does not need more review rounds; rounds per
PR (`ledger_tool.py stats`) is the number to watch. When routine implementation is
weaker than critical work, `REV-04` moves a PR that still has must-fix
findings after `escalate_after_round` rounds to a fresh thread on the
critical-work model. Models are never switched inside a thread (`THR-09`).

Coupling them ("frugal means cheaper models") is the usual mistake. A frugal
profile with strong models on critical paths is cheaper *and* safer than a
velocity profile with weak models, because review rounds on critical PRs are
where bad models cost the most.

| Profile | lanes | replace after PRs / compressions | watchdog | NC rounds | audit | KB PRs | verbosity |
|---------|-------|----------|----------|-----------|-------|--------|-----------|
| frugal | 2 | 2 / 1 | 120 min | 2 | critical_only | per milestone/batch | ultra_terse |
| balanced | 3 | 3 / 2 | 60 min | 2 | light_every_batch | daily | terse_batched |
| max_velocity | 3 | 4 / 2 | 30 min | 2 | full_every_batch | daily | standard |

`goal_turn_cap` (20 / 30 / 40) bounds a `/goal` loop on contract criteria.
`cache_ttl_minutes` (60 or 5) is not part of a profile; it follows from how
the owner pays (section 9).

No profile goes below two review rounds for routine PRs: with one round
nobody confirms that the fix worked, and review and verification are where
tokens pay off (section 12). The profiles save on coordination instead.

Pick **frugal** for solo side projects, long autonomy horizons, or private
repos paying for Actions minutes. Pick **balanced** by default. Pick
**max_velocity** when the owner is actively watching and wants the fastest
feedback. Any single number can be overridden.

## 6. The five architectural invariants ("D-703")

The original project that this skill was distilled from recorded these in its
decision log as entry D-703. The number is just that project's label; in a new
project they become part of the generated rules and get the new project's
D-001. The invariants are the things that, when violated, caused real damage:

1. **Lane separation.** Lanes are concurrency slots; labels are ownership.
   Core changes require `lane:infra` and lock other lanes out of core; docs
   never need the lock. (Rules `LANE-02`, `LANE-03`.)
2. **Release CI precedence.** A branch-level CI trigger (for example
   Linux-only on `release/**` to save minutes) never overrides the critical PR
   rule: a critical PR into a release branch still runs the full matrix on its
   final round, by dispatch or label. (`CI-01`, `CRIT-02`.)
3. **KB criticality scope.** KB process, contract and architecture documents
   are critical and go through review. The routine decision-log batch PRs the
   KB thread writes are exempt, or the KB thread could never self-merge and the
   log would rot. (`CRIT-01`, `ROLE-08`.)
4. **Atomic thread replacement.** A thread that hits `replace_at_compressions`
   finishes its current atomic step and is replaced at the next hand-off,
   never mid-step. This includes the KB thread. (`THR-02`.)
5. **Hard stop at the last critical round.** A critical PR that has not
   converged after `critical_max_review_rounds` (round 4 by default) stops and
   waits for owner sign-off; the coordinator may not approve it alone. The
   round can be set; the stop cannot be switched off, and the audit reports a
   ruleset without it. (`REV-01`, `AUTO-01/02`.)

## 7. What the generated files contain

`claude-project-rules.yaml` (static, changes only by owner-approved PR):

| Section | Ids | Holds |
|---------|-----|-------|
| header | — | `version` (minor number goes up whenever a regeneration changes the content), `date` (of the last generation), project, repository, owner, timezone, `authority` precedence list (section 11) |
| `project_profile` | — | stack preset, environment, target platforms, fast checks, local env, lanes, labels, mapping note, `critical_paths`, `doc_paths`, `workspace_root`, `state_file`, `plans_dir`, `rules_by_role`, and for an in-repo workspace `default_branch` and `governance_branch` |
| `execution_profile` | — | `model_routing` (6 slots) and `token_economy` (profile name plus numbers and enums) |
| `meta` | META-01..03 | ruleset edits are critical; state lives elsewhere; a correction given twice becomes a check, not a rule |
| `roles` | ROLE-01..14 | one rule per role, plus owner hand steps and the approval rule; ROLE-10 (specify) and ROLE-11 (dispatcher) only when enabled |
| `autonomy` | AUTO-01..03 | horizon, what waits for the owner, working ahead |
| `lanes` | LANE-01..04 | batching, concurrency cap, ownership (written from the labels that exist), release-branch exception |
| `threads_and_watchdog` | THR-01..14 | onboarding from the extract + fitness check, replacement, watchdog, one writer per file, how threads are started (THR-10, coordinator and dispatcher), planned compaction (THR-11, Claude Code only), the governance branch and its worktree (THR-13) and the default branch as the copy that counts (THR-14), both in-repo only |
| `plans_and_criticality` | PLAN-01..05, CRIT-01..03 | plan-before-code, acceptance contracts (PLAN-03..05, when `acceptance_contracts` is on), what is critical, what critical requires, who decides it |
| `pull_requests_and_reviews` | PR-01..05, REV-01..06, MRG-01..02 | title format, CI-before-review, branch freeze, round caps and the hard stop, report format, criterion proof (REV-03), escalation by model (REV-04), fixes at the root and finding kinds (REV-05), merge protocol with "no open must-fix finding" and the ledger gate |
| `testing_and_ci` | TST-01..02, VER-01, CI-01 | tests first, never weaken tests, proof by running the product as a user would (VER-01, with `runtime_verification`), fast vs full matrix |
| `github_kb_and_release` | GH-01, KB-01, REL-01 | issues same day, decision logging with the owner's message quoted, release branching |
| `hard_invariants_and_owner_prefs` | INV-01.., PREF-01 | licence gate; then, each only if configured: layer-boundary check, telemetry ban, custom invariants; each says what enforces it ("Enforced by: ..."); owner timezone and formatting wishes |

Nothing project-specific is built in. What used to be written into every
ruleset is now an option: `owner_prefs` (formatting wishes), `critical_areas`
(what counts as critical), `local_ui_loopback_only`, `github_rest_only`,
`layer_boundary_check`.

`rules/<role>.yaml`: one extract per thread type (section 1), regenerated
with the ruleset and never edited.

`project-state.yaml` (volatile; the coordinator is its only writer):
`active_now` (autonomy horizon, paused / slow_down / thread_freeze flags,
active milestones, owner autonomy message ids, open hand steps),
`approved_contracts` (one line per picked-up contract version with its
D-number and hash) and `closed_milestones`, `notifications_pending`, and a
`control_commands_reference` listing the phrases the owner can type.

`governance-config.json` is the normalized input. Re-running the generator on
it reproduces the ruleset byte for byte except for `date`, which is always
the day of the run, and `version`, which goes up when the content changed.
That is how an audit can diff "what the generator would emit" against "what
is there now". Every value in it is type-checked, every free-text value is
quoted in the YAML, and the generator parses its own output before saving it.

## 8. Acceptance contracts, issues and the roadmap

A plan says how a thread will build something; an acceptance contract says when
the milestone is done, in terms the owner approved before any code exists. With
`acceptance_contracts` on (the default), work enters the project through one
door: the owner gives a specify thread a feature idea or a plan change, and it
returns a contract version, work packages (one GitHub issue each, generated
from the contract) and a roadmap update (`ROLE-10`). Only the owner approves,
after seeing every criterion and verify step, by quoting the contract's hash.
The coordinator picks the contract up, records its id, version, D-number and
hash in the state file and batches the packages (`PLAN-03`). From then on
`contract_tool.py` compares the contract with that record, so an edit after
approval is caught even if the hash inside the contract was recomputed
(section 11 says what this does and does not guarantee). Plans and PRs cite
criterion ids with proof (`PLAN-04`); reviewers confirm the claims, reading the
diff and the contract before the author's framing (`REV-03`); the coordinator
closes the milestone when every must criterion and the core probe pass
and winds down work that a plan change removed (`PLAN-05`).

Criteria are written in exactly one place, the contract. Issues cite them;
`roadmap.yaml` orders the milestones; `project-state.yaml` mirrors what is
active. A change in *what done means* goes back through specify; a change in
*how* something is built stays a coordinator decision with a D-number
(`PLAN-01`). Method and details: `references/acceptance-contracts.md`.

## 9. Cache-aware habits

Usage is driven by cache misses, not by how much text exists. While a thread
is active, its history is re-read from the prompt cache at a small fraction of
the input price. Once the cache has expired (60 minutes on a Pro/Max
subscription, 5 on an API key or usage credits: `cache_ttl_minutes`), the next
message writes the whole history again. Fewer raw tokens is therefore not the
same as less usage, and the size of a file matters less than how often it is
re-sent uncached.

**Where a coordinator's tokens go.** A turn costs roughly the size of the
context it re-reads. A coordinator lives long, so its context is the largest
in the project, and each extra turn costs more than the one before. Ten
one-line wake-ups for watches and merges cost far more than one report per
batch. In an excerpt from a running project (about ten coordinator turns
for two merges, a plan approval and a review verdict), the turns came from
background commands the coordinator had started itself, from relaying merge
go and merge recorded as separate turns, and from repeating the same list
of open items in six replies. Hence, in this order: the dispatcher, on the
workers' model so it can start them, takes all per-PR traffic (`ROLE-11`); the coordinator acts on
the few events of `ROLE-17` and does no hands-on work (`ROLE-05`); the thread
that merges also watches the run on the default branch (`ROLE-07`); and
what is open is printed by `ledger_tool.py status`, not carried in chat. The
audit warns when the dispatcher is off while three or more lanes run (A17).

Evidence: [claude-code-usage-analysis](https://github.com/inevolin/claude-code-usage-analysis)
(live runs on the Claude Code CLI, Opus 5.5, 5-minute cache).

| Finding | Measured | What the ruleset does with it |
|---|---|---|
| Resuming a 97k-token session after the cache expired | about 10x a fresh session (1.5x while warm); break-even near 10k tokens of history | Workers are not woken after the gap; a fresh thread starts from a three-line handoff (`THR-07`, `THR-03`) |
| Compacting after the break instead of before | 9.7x vs 2.5x | Handoffs are written before a wait, not reconstructed after it (`THR-07`) |
| Small related fixes in one warm session vs a new session each | 28% less (n=1) | Related fixes go back to back to the warm thread (`THR-08`) |
| A test log left in the chat | +15% (750 tokens) to +64% (5,000) over the next six turns | Tool output stays out of the chat (`THR-09`) |
| Turning off a tool mid-session; switching model (from the docs) | 22x a normal turn; full re-read | One model and tool set per thread (`THR-09`) |
| Scheduled runs that resume an old session | about 3x a fresh session each run (estimate) | Threads are disposable and state lives in files (`THR-02`, `THR-05`) |
| Claude Desktop Code tab vs the CLI for the same fix | at least 1.80x (n=1) | Not a rule; prefer the CLI for Claude Code worker threads where there is a choice |

Limits to keep in mind when explaining this: small samples, one model, the
5-minute cache only (the 60-minute numbers are estimates), Claude Code only
(claude.ai chats were not measured), and subscription limits use weights that
are not published. The study's compaction-threshold settings did not hold up
against its own live runs and are deliberately not adopted here.

**Task size.** The same mechanism sets the right size for a piece of work.
Each new thread pays a fixed start-up cost, so many tiny tasks in fresh
threads are wasteful (`THR-08` gives related small fixes to a warm thread). A
long task costs more than proportionally: every turn re-reads a growing
history, a compaction or a wait past the cache lifetime becomes likelier, and
the diff takes more review rounds. The unit to aim for is a work package: one
thread, one PR, one review round (`PLAN-04`), about six criteria at most as a
starting point. The study did not measure task size; the ledger does (`ledger_tool.py stats`), through
compactions per PR and review rounds per PR.

**The coordinator is the exception that pays.** It is never replaced, so every
wake-up after the cache lifetime re-sends its whole context. That cost grows
with its context and with the number of wake-ups, which is why `THR-06` keeps
it small and why decisions for the owner and reports from the dispatcher are
batched. In Claude Code it also compacts on purpose rather than by accident:
at a pause and at the end of every batch
(`coordinator_compact_every_batches`, default 1; 0 turns this off) it writes
state and hands the owner the `/compact Keep: ...` line to paste while the
cache is still warm (`THR-11`). The trigger is the batch end, which the batch
file shows, not the coordinator's own estimate of its context size, which it
cannot measure. Compacting before a wait cost 2.5x a fresh session in the
study, after it 9.7x. The owner types the command; nothing documented lets
the coordinator run it itself. `/compact` exists in Claude Code only, so a
project whose coordinator lives in a claude.ai Project gets no `THR-11`;
there the coordinator stays small by `THR-06` alone. As a safety net,
Claude Code's `idleCompaction` setting can compact a long idle conversation on
the one-hour cache shortly before the cache expires; per the study it only
applies above 200,000 tokens of context, so a small coordinator will not
trigger it.

## 10. Operating mechanics: starting threads, shared files, the watchdog

Rules only work if a thread can actually do and see what they ask. This
section says what each mechanism rests on. It differs by `environment`.

**Starting a thread and setting its model (`THR-10`).** A thread that has a
tool for opening another thread or session uses it and sets the model there.
A thread that has no such tool, or whose tool cannot set the model, writes a
starter block (role, model from `model_routing`, the extract to read, the
first task) and the owner opens the chat on that model and pastes it. Which of
the two applies depends on the tools the thread was given, not on the
ruleset, so the rule covers both. A new thread's first line names its role
and, if it can see it, its model; nobody assumes a model that was not
confirmed.

| | `claude_ai_project` (workspace `/mnt/project-files`) | `claude_code` (workspace in the repo) |
|---|---|---|
| Thread | a chat in the Project | a Claude Code session or subagent |
| Model | chosen in the chat's model picker, by whoever opens the chat | set when the session starts (in the CLI: `claude --model <name>`) or by the tool that starts it |
| Shared files | the Project's files; one writer per file | a git branch (below) |
| Planned compaction | not available: no `THR-11` | `/compact`, typed by the owner (`THR-11`) |

**Shared files (`THR-04`, `THR-13`).** Every file has one writer. A thread
writes its own plan, its own round reports and its own ledger entries; the
state file and `kb/pending-decisions.md` are the coordinator's; the decision
log is the KB thread's, compiled from the pending file (`ROLE-08`); the
roadmap and contracts are specify's; the batch file is the dispatcher's once
the coordinator has composed it. Because the ledger is one small file per PR
and per round (`ledger/prs/`, `ledger/rounds/`) instead of shared tables, two
threads never edit the same file, and `ledger_tool.py` prints the tables.

In a repo the files also need a place in git, since implementation threads
may not push to the default branch:

- Working files (plans, round reports, ledger entries, batch files, the state
  file, the pending decisions) are committed on `governance_branch` by their
  writer: rebase before each push; never force-push; never on a product
  branch (`THR-13`). One writer per file means these pushes do not conflict
  in content. An implementation thread sits on a product branch, so it keeps
  a second worktree for the governance branch (`git worktree add
  ../<repo>-governance governance`); the command is part of every starter
  block (`THR-10`).
- The ruleset, the config, acceptance contracts, the roadmap and the decision
  log change on the default branch by pull request only (`THR-14`). With the
  CODEOWNERS lines from `github-setup/` and code-owner review required, the
  owner's review is what lets a contract or a ruleset change in.
- After such a merge, the dispatcher (or the coordinator) merges the default
  branch into `governance_branch`, so every thread reads one consistent tree.
- The governance branch is not protected: any thread can commit to it. So
  the copy of a protected file there proves nothing. The copy on the default
  branch is the one that counts, and `contract_tool.py` compares an approved
  contract with it instead of trusting the working copy (C039). The same
  holds for the ruleset itself, its config, the extracts and the roadmap:
  the contract tool (C040) and the audit (A14) compare them too. Which
  branch is the default is taken from the remote (`origin/HEAD`), because the
  `default_branch` line in a ruleset on the governance branch could be
  edited like anything else there; a ruleset that disagrees with the remote
  is an error.

**The decision log (`ROLE-08`).** The coordinator makes decisions; the KB
thread writes the log. The hand-over between them is a file, not a chat
message: the coordinator adds each decision to `kb/pending-decisions.md`,
the KB thread compiles those entries into `kb/decision-log.md` on its
cadence, and the coordinator removes an entry once it is in the log. In a
repo the log changes by a decision-log pull request that the KB thread
merges itself; in a claude.ai Project there are no pull requests and the KB
thread writes the log file directly.

**The watchdog and the clock (`THR-03`).** See section 4: it is a check that
runs when a thread is active, with the time taken from a tool. A guaranteed
interval needs a scheduled task, which only the owner can set up.

**What a thread cannot observe, and what replaces it.**

| A thread cannot reliably know | The rules use instead |
|---|---|
| how often it was compressed | PRs handled, from ledger entries (`THR-02`) |
| how large its context is | batch ends, from the batch file (`THR-11`) |
| what time it is | a tool, commit timestamps, file dates (`THR-03`) |
| which model another thread runs on | that thread's first line; the owner's confirmation (`THR-10`) |
| whether another thread's claim is true | files: plan, round report, ledger entry, CI (`THR-01`, `REV-03`) |

## 11. Authority order, and what is enforced by what

When sources conflict, the first of these wins (`authority` in the ruleset):

1. **The owner's newest message on the point.** The owner may override any
   Claude-decided entry at any time (`ROLE-01`), so an older decision-log
   entry never outranks what the owner just said. If the message contradicts
   the ruleset or an approved acceptance contract, it is not applied
   silently: it starts the change (init for the ruleset, specify for a
   contract), because both are frozen for threads.
2. **The ruleset** and the project instructions generated from it.
3. **Approved acceptance contracts.**
4. **The decision log**, newest entry first. Decision-log PRs are merged by
   the KB thread without review, so an entry that records an owner decision
   must quote the owner's message and its date (`KB-01`); without the quote
   it ranks as a Claude decision.
5. Decisions made in session that are not yet in a KB PR.
6. Project memory, then the repository's `CLAUDE.md`.

Be exact, when explaining the system, about which guarantees are enforced by
a tool and which rest on threads following the rules:

| Guarantee | Enforced by |
|---|---|
| Config values have the right type; the YAML parses | the generator (refuses, exit 2 or 3) |
| A fresh ruleset is consistent; the hard stop exists; extracts match | `audit_rules.py` |
| The ruleset, config, extracts and roadmap a thread reads are the reviewed ones | in a repo: `audit_rules.py` (A14) and `contract_tool.py` (C040) compare them with the remote's default branch. Elsewhere: not enforced |
| An approved contract was not edited afterwards | `contract_tool.py lint`, `goal` and `pickup`: the contract's hash, the owner's quoted message and the coordinator's pickup record must agree; at pickup the content must match the hash the owner names; in a repo it must also match the copy on the default branch |
| Only the owner approves a contract or a ruleset change | in a repo: CODEOWNERS plus required code-owner review on the default branch, once the owner has set them up. Elsewhere: by rule only (`ROLE-03`) |
| Labels and milestones exist before issues are created; no duplicate issues | `contract_tool.py issues --preflight` and `record-issue` |
| No merge with an open must-fix finding; criticality confirmed by the reviewer | `ledger_tool.py gate <N>` before the merge (it reads the entries the review thread wrote, so it is as true as they are); visible afterwards with `ledger_tool.py check` |
| PR title format, no closing keywords in commits, a lane label, file ownership by path, `risk:high` on critical paths | `pr_checks.py` in CI, once the owner has copied the workflow and made it a required check. Until then: by rule |
| No force push, no direct push to the default branch, CI green before merge | branch protection, once the owner has set it. Until then: by rule |
| Invariants | whatever each names after "Enforced by:"; the audit lists those that name nothing (A15) |
| Round caps, the hard stop, replacement, the watchdog | by rule; visible afterwards in round reports and ledger entries |

What remains open: in a claude.ai Project nothing technical stops a thread
from writing any file, so a thread that edits a contract, its hash, the
quoted owner message and the pickup record together, after pickup, is caught
only by whoever reads the files. In a repo this is closed by the comparison
with the default branch, provided the owner has set up CODEOWNERS and
required review there, the checkout is fetched, and it records the remote's
default branch (`git remote set-head origin --auto`; a normal clone does).
Where it does not, `goal` and `pickup` refuse rather than trust the ruleset. The design makes a silent change take several
coordinated edits in files owned by other roles; it does not make it
impossible. The audit exists to look.

## 12. What the rules rest on: checks before prose

This skill produces rules, and rules are the weakest way to make a thread do
the right thing. A thread follows a rule when it has read it, remembers it
and judges that it applies. A check does not depend on any of that. The
order below is the order of trust, most reliable first (the ordering follows
Lauren Tan's talk "All Code Is Slop (Except Mine)", AI Engineer, 2026):

1. **The product's own code.** A design that makes the mistake impossible
   beats every check: an API that cannot be misused, a folder structure that
   says what may import what. Threads copy what they find, good or bad, so a
   workaround left in place becomes the pattern the next thread follows.
2. **Deterministic checks.** Lint rules, types, tests, CI checks, branch
   protection. They fire every time and say exactly what is wrong; a lint
   message that names the root cause teaches the next thread for free.
3. **Verification.** Running the product as a user would and keeping the
   evidence; where it pays, property tests or formal models of important
   flows. This is also where most tokens are well spent.
4. **Prose.** Rules, instructions, notes, comments: needed for what takes
   judgement, and nothing else.

How the generated setup applies this:

- **A correction given twice becomes a check** (`META-03`, `REV-05`). The
  review thread names the kind of each finding in its ledger entry, and
  `ledger_tool.py stats` lists kinds seen in more than one PR. Those are the
  candidates for a lint rule, a test, a CI check or a design change. Put the
  check in first, so no new cases arrive, then clean up the old ones in the
  same batch; what stays in the code keeps being copied. Adding a rule to
  the ruleset is the last resort and needs the owner.
- **A comment is not a fix** (`REV-05`). A code comment, a document or a note
  that explains why a workaround is fine leaves the finding open. Comments
  are not enforceable, go stale, and give the next thread a ready excuse.
- **Comments say why, and only why** (`PR-05`). Threads comment far more
  than people do: they restate the code, describe the change ("now uses a
  set instead of a list") and record who asked for it. All of that is stale
  the moment the PR merges, and the next thread reads it as fact or copies
  the habit. A comment earns its place when it gives a reason the code
  cannot show: a constraint, a trap, a link to the issue. The rule covers
  new and changed lines; old comments are cleaned up in a PR of their own,
  not mixed into feature work. `pr_checks.py --diff` lists added comments
  that match a word list of narration phrases, and TODOs without an issue
  number, as a warning for the reviewer. Repeats show up in `ledger_tool.py
  stats` under the kind `narrating-comment`.
- **No file that nobody asked for** (`PR-05`). Left alone, a thread leaves
  `SUMMARY.md`, `NOTES.md` or `IMPLEMENTATION.md` behind. Nobody maintains
  them, and later threads trust them. A thread creates only files the
  rules, the approved plan or the owner named; what it wants to report goes
  in the PR body or the ledger. `pr_checks.py` fails a PR that adds a
  markdown file outside `project_profile.doc_paths` (default: `docs/**`,
  any `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `.github/**`). The
  governance workspace is not affected: plans, round reports and the KB are
  files the rules name.
- **Things that need nuance get banned, not explained.** If an API or
  pattern is misused again and again, the project forbids it in product code
  with a lint rule and allows it in one named place. Record it as an
  invariant with its check.
- **Every invariant names what enforces it.** A custom invariant is written
  as `"<sentence> [check: <lint rule, test or CI job>]"` and rendered as
  "Enforced by: ...". Without a check it says "Enforced by: review only", and
  the audit lists those (A15), because an invariant nobody checks holds only
  until a thread forgets it.
- **Pull-request rules that a machine can check are checked by a machine.**
  `github-setup/` carries `pr_checks.py` with a workflow: title format, no
  closing keywords in commits, a lane label, file ownership by path
  (`label_paths`), `risk:high` on critical paths. Branch protection covers
  force pushes, direct pushes and required checks. `ledger_tool.py gate <N>`
  answers "may this PR be merged" from the ledger entries before every merge.
- **Proof is evidence, not a claim** (`VER-01`, `REV-03`). Behaviour a user
  can see is shown by running the product along the real user path, following
  `kb/verification.md`, and the evidence is kept and named in the PR. The
  reviewer looks at the evidence. `kb/features/` gives every feature one name
  and lists all its entry points, so a proof through one convenient path is
  not mistaken for the whole feature.
- **Review rounds are not where to save.** Every profile allows at least two
  rounds for routine PRs; a single round leaves nobody to confirm the fix.
  The profiles save on coordination: fewer lanes, fewer messages, a longer
  watchdog interval.
- **The outcome is measured.** `ledger_tool.py stats` shows the share of
  merged PRs that were reverted. A cheaper model or a leaner profile is an
  improvement only if that number does not rise.

**Further up the ladder** (these five points follow the practice of the
open repository `equinai/equin`, which backs nearly every agent rule with a
check or a hook):

- **The ladder has rungs** (`META-03`). From strongest to weakest: a design
  that makes the mistake impossible; a type; a lint rule, test or CI check;
  a loud failure at runtime; prose. A repeated correction moves one rung up
  from where it is now. Another sentence in a rule file is the bottom rung
  and is chosen only when nothing above it is possible.
- **Suspect fixes** (`REV-06`). A retry, a timeout or deadline, a cache, or
  a raised limit that makes a failure go away usually hides the cause. The
  reviewer treats each as a finding until the PR names the cause it removes.
- **"Fixed" is derived, not declared** (`REV-06`). A PR that claims to
  remove a finding kind for good says so in `fixes_kinds`. `ledger_tool.py
  stats` then reports the claim as pending, holding or regressed from the
  later round entries. A regressed fix is the signal to go up a rung.
- **Exemptions are declared, labelled and visible** (`PR-04`). A file that
  has to break a pull-request check is listed in `pr-check-exemptions.json`
  as `sanctioned` (permanent, with a reason) or `debt` (with a reason and
  the issue that removes it). `pr_checks.py` prints every exemption it
  used, refuses a malformed list, and with `--open-issues` fails a debt
  entry whose issue is closed. Widening a glob or dropping a label to get a
  PR through is not an exemption, it is a hole.
- **An override is one decision, not a switch** (`MRG-02`). When the owner
  lets a PR merge against the gate, the coordinator records the reason and
  the head SHA in `ledger/overrides/pr-<N>.yaml`. `ledger_tool.py gate`
  accepts it for exactly that head, prints it in capitals, and `stats`
  counts it. A changed PR needs a new decision. Standing bypasses are not
  offered, because nobody remembers to remove them.

**Proving the checks, and what is left behind** (these points follow the
practice of the open project `Druthulu/ProjectArchitect`, a plan-and-task
loop for Claude Code that benchmarks its own agents):

- **Verify the verifier** (`VER-02`). A check that has never failed proves
  nothing: it may read the wrong input, or not run at all. Each check is
  shown to fail once on a case known to be wrong. For the pull-request
  checks this is built in: `pr_checks.py --self-test` runs every configured
  check against a known-bad pull request and reports `ok`, `off` (not
  configured) or `DEAD`; the scaffolded workflow runs it before the real
  checks. For an invariant's own check, record where it was proved in the
  config, `[check: ci:lint-imports (proved: PR #12)]`; the audit lists
  checks without that note (A16).
- **Too good is suspicious, and a summary is a claim** (`VER-02`). A result
  that looks better than expected is treated as a measurement error first. What
  another thread, a tool or an older note reports is checked against the
  file, the diff or the output before a decision rests on it.
- **A closed list of reasons to stop** (`THR-15`). A worker's report starts
  with one word: `done`, `question`, `blocked`, `review` or `handoff`.
  `blocked` and `question` carry the evidence and one recommended action,
  and are recorded in the PR's ledger entry, where they stop the merge gate
  until settled. The coordinator routes on the word instead of reading a
  free-text escalation.
- **Nothing is left behind without a decision** (`THR-16`). A should-fix
  finding that survives the merge, or a point a thread set aside, becomes an
  entry in `ledger/deferred/`. `ledger_tool.py triage` refuses a new batch
  while one is open. Each ends as planned (an issue), postponed (a reason
  and until when) or dropped (the owner's word). Deferred work that nobody
  decided on is how a backlog rots.
- **An audit in two halves** (`ROLE-15`). The script half is `ledger_tool.py
  flags`: one line per thing worth judging, derived from the entries. The
  judgment half is the audit thread, which gives each flag one of five
  verdicts: check, rule, split, owner or leave. It proposes and builds
  nothing, so an audit cannot quietly rewrite the tooling it audits.
- **Seam audits: files that work together are read together** (`ROLE-16`,
  only when `seam_groups` is set). A review round reads one PR's diff and a
  batch audit reads what a batch changed. Neither reads two neighbouring
  files side by side as they are now, which is where contracts between
  files break. Every `seam_audit_every_prs` merged PRs (default 15), or
  when a milestone closes, a fresh read-only session takes the brief from
  `seam_audit.py brief` and checks four things only, per group: error and
  status mapping between a module's errors and the handlers that receive
  them; a caller that reads another module's internal state and then calls
  a mutator; the same low-level helper written twice in sibling modules;
  a comment that cites a decision or an issue for an invariant the code no
  longer keeps. The script does the mechanical part of the last one: it
  lists every `D-` number and issue number cited in the group and marks a
  superseded decision, a decision that is not in the log and a closed
  issue. The report holds at most ten findings, each with a kind, a
  `ROLE-15` verdict and the lines read; `seam_audit.py check` refuses a
  report outside that shape. `ledger_tool.py stats` says when the audit is
  due, counted from the merge entries. A session fresh to the code matters:
  a thread that reviewed those PRs is anchored by what it approved.
- **A reading list per role.** Each role extract starts with `start_reading`
  and `leave_unread`. What a thread does not load is the cheapest saving
  there is, and it also keeps a reviewer from being anchored by the
  implementer's reasoning.
- **Work at the size asked** (`PR-06`). A feature, option or abstraction the
  plan does not name is a finding. A new dependency needs three lines: what
  it does, what the project already has, and the difference.
- **What was ruled out travels with the handoff** (`THR-07`). The next thread
  reads what was tried and failed, with the evidence, and does not try it
  again.

**Known gaps, on purpose.** The checks stop accidents, not a thread that is
determined to get around them, and none of them is a security boundary:

- `pr_checks.py` judges the labels and file list it is given. It is as
  strong as the branch protection that requires it and the owner review
  (CODEOWNERS) of `.github/governance/` and its workflow.
- File ownership is by path. A file moved into another lane's folder
  belongs to that lane from then on.
- The ledger lives on the governance branch, which is not protected. A
  round entry or an override file is a record, not proof. The merge itself
  needs the go named in `MRG-01`, and an override needs the owner's own
  message.
- The comment check is a word list over added lines that begin with a
  comment marker. It misses a great deal and flags some honest comments, so
  it only warns. The new-docs check sees markdown only.
- The self-test proves that a check can fail, on one built-in case. It does
  not prove the check catches every wrong pull request, and it runs without
  the exemptions, so an over-broad exemption is not caught by it.
- A seam audit's first three checks are a model's judgment. The script
  fixes the questions, the groups, the size and the shape of the report,
  and finds the cited decisions; it cannot tell whether a finding is true.
  A group is only audited if someone named it.
- `triage` counts leftovers by number, not by content: three entries for a
  PR with three should-fix findings satisfy it whatever they say.
- A hand-back is recorded by the thread that hands back. A thread that does
  not record it is not stopped by the gate.
- The regressed marker goes by dates and PR numbers, not by which commits a
  branch contains. It can flag a PR that branched before the fix.
- The comparison with the default branch (`THR-14`) needs a git checkout
  with the remote; where it cannot run it says so and refuses, it does not
  pass.

**Foundations first.** All of this assumes the repository can tell a thread
that its change is wrong. `scripts/repo_readiness.py` reports whether CI,
tests, a linter, a type checker and a documented way to run the product
exist. Where they do not, more lanes only produce more unchecked changes:
start with one lane, a short autonomy horizon, and make the missing
foundations the first work package.
