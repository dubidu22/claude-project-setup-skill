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

---

## 1. Threads and roles

A project runs as several Claude chats ("threads") in one claude.ai Project or
one repo, each with a role and a narrow remit:

| Role | Does | Never does |
|------|------|------------|
| **owner** (human) | sets goals, scope, milestones; performs hand steps (publishing, hardware tests, repo settings); gives sign-off | — |
| **coordinator** | splits work into lane batches, spawns/replaces threads, approves plans, grants merge go, logs D-numbers; reads ledgers and PR state instead of relaying messages | writes product code; approves scope changes or acceptance contracts |
| **dispatcher** (optional) | runs one batch at a time: spawns, watches and replaces worker threads, keeps `batch-<NNN>.md` and ledgers current, grants merge go for non-critical PRs | approves plans, critical PRs or anything touching scope |
| **specify** (with acceptance contracts) | in its own chat: interviews the owner about a feature idea or plan change, researches and drafts the acceptance contract, groups work packages, updates the roadmap; records approval and creates issues on the owner's own yes | approves anything itself; touches rules, state, code or D-numbers |
| **implementation** | reads KB + plan, writes tests then code inside its lane, opens PRs, answers findings with exact fix lists | merges, pushes to main, force-pushes |
| **review** | reviews a batch's PRs in rounds, writes round reports, checks CI, squash-merges on coordinator go | authors the PR it reviews |
| **kb** | compiles decisions into the decision-log PR on the configured cadence and self-merges it | reviews code |
| **audit** | after a merged batch, scans the combined diff for cross-PR inconsistencies and contract touches | blocks merges |

Only the owner's own messages count as owner approval. Another thread's output
never does, which is why `ROLE-03` exists: without it a coordinator can talk
itself into "the review thread said it was fine".

Every rule has an `applies_to` scope from this list (or `all`) so a thread can
filter the ruleset to what binds it. A rule without a scope binds nobody.

**Coordinator load.** The coordinator's own work is per batch (milestones, plan
approval, D-numbers, the owner); everything per PR is traffic. Two things keep
it small. First, by default: fix lists travel through round reports, threads
post one line per hand-off, and the coordinator reads ledgers and PR state
instead of messages (`ROLE-04`, `THR-04`). Second, opt-in with `dispatcher:
true`: a dispatcher takes the per-PR operations (`ROLE-11`, `LANE-02`,
`THR-01`, `THR-03`). Because all of its state is in `batch-<NNN>.md` and the
ledgers, it is replaced at its first compression (`THR-05`), while the
coordinator, now receiving one report per batch, stays long-lived. Turn it on
with three or more concurrent lanes, or when the coordinator compresses more
than once per batch.

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

Two labels are special:
- `lane:core` marks shared, cross-cutting files. Touching them is critical and
  requires `lane:infra`, which acts as a single-thread lock: while an infra PR
  is open, no other lane touches core.
- `lane:docs` may be added by any lane without taking the lock, so that
  documentation never queues behind infrastructure.

## 3. Criticality and review rounds

A change is **critical** when it touches layer contracts, core data structures,
KB process/architecture docs, golden files, packaging/release/CI, safety
mechanisms, licences, deletion paths or network calls, or carries `risk:high`.
Critical work gets: coordinator plan approval before coding, review on the
stronger model, exact fix lists, issues for every deferred finding, and the
full multi-platform CI matrix on its final round.

Reviews run in **rounds**. Each round produces a report (head SHA, verdict,
numbered findings B/M must-fix, S should-fix, N note), and the author answers
each finding as fixed-with-proof, deferred-with-issue, or declined-with-reason.
Non-critical PRs stop after `non_critical_max_review_rounds` and defer the
rest to issues. Critical PRs stop after round 4 and **wait for the owner**:
four rounds without convergence means the thread pair is stuck, and burning
more tokens on it is the one thing that will not help.

## 4. Context compression, replacement and the watchdog

Long chats get compressed; after compression a thread remembers less than it
thinks it does. `replace_at_compressions` says how many compressions a thread
may survive before it is retired and a fresh one is briefed from the KB. The
replacement happens **at the next hand-off**, after the current atomic step
(a review round, a fix commit, a KB PR) completes. Replacing mid-step loses the
step's working state and produces half-written reports or orphaned branches.

The **watchdog** is the coordinator's (or dispatcher's) timer: whenever a thread
owes output, it looks at the thread's last commit or file change after
`watchdog_interval_minutes` and nudges only when nothing moved; after
`watchdog_max_nudges` without progress it replaces the thread or escalates.
Shorter intervals cost coordinator tokens; longer ones cost wall-clock time.

**Fitness check**: before a thread receives a second batch it reports its
compression count, current plan and open items from memory. A thread that
cannot do this is replaced rather than trusted.

## 5. Model routing versus token economy

These are configured separately because they answer different questions:

- **Model routing** is about judgement: which model runs the coordinator, which
  runs implementation and critical review, which runs routine review, audit
  and KB. Changing it changes *quality*.
- **Token economy** is about spend and pace: concurrency, replacement
  threshold, watchdog cadence, review-round caps, audit depth, KB cadence,
  reporting verbosity, CI offloading. Changing it changes *cost and speed*.

Coupling them ("frugal means cheaper models") is the usual mistake. A frugal
profile with strong models on critical paths is cheaper *and* safer than a
velocity profile with weak models, because review rounds on critical PRs are
where bad models cost the most.

| Profile | lanes | replace@ | watchdog | NC rounds | audit | KB PRs | verbosity |
|---------|-------|----------|----------|-----------|-------|--------|-----------|
| frugal | 2 | 1 | 120 min | 1 | critical_only | per milestone/batch | ultra_terse |
| balanced | 3 | 2 | 60 min | 2 | light_every_batch | daily | terse_batched |
| max_velocity | 3 | 2 | 30 min | 2 | full_every_batch | daily | standard |

`goal_turn_cap` (20 / 30 / 40) bounds a `/goal` loop on contract criteria.

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
5. **Round-4 hard stop.** A critical PR that has not converged after round 4
   stops and waits for owner sign-off; the coordinator may not approve it
   alone. (`REV-01`, `AUTO-01/02`.)

## 7. What the generated files contain

`claude-project-rules.yaml` (static, changes only by owner-approved PR):

| Section | Ids | Holds |
|---------|-----|-------|
| header | — | version, date, project, repository, owner, timezone, `authority` precedence list |
| `project_profile` | — | stack preset, target platforms, fast checks, local env, lanes, labels, mapping note, `workspace_root`, `state_file`, `plans_dir` |
| `execution_profile` | — | `model_routing` (3 roles) and `token_economy` (profile name + 10 numbers/enums) |
| `meta` | META-01..02 | ruleset edits are critical; state lives elsewhere |
| `roles` | ROLE-01..11 | one rule per role, plus owner hand steps and the approval rule; ROLE-10 (specify) and ROLE-11 (dispatcher) only when enabled |
| `autonomy` | AUTO-01..03 | horizon, what waits for the owner, working ahead |
| `lanes` | LANE-01..04 | batching, concurrency cap, ownership + infra lock, release-branch exception |
| `threads_and_watchdog` | THR-01..05 | onboarding + fitness check, atomic replacement, watchdog, where plans/reports go |
| `plans_and_criticality` | PLAN-01..06, CRIT-01..02 | plan-before-code, acceptance contracts (PLAN-03..06, when `acceptance_contracts` is on), what is critical, what critical requires |
| `pull_requests_and_reviews` | PR-01..03, REV-01..03, MRG-01 | title format, CI-before-review, branch freeze, round caps, report format, criterion proof (REV-03), merge protocol |
| `testing_and_ci` | TST-01..02, CI-01 | tests first, never weaken tests, fast vs full matrix |
| `github_kb_and_release` | GH-01, KB-01, REL-01 | issues same day, decision logging, release branching |
| `hard_invariants_and_owner_prefs` | INV-01.., PREF-01 | licence gate, layer boundaries, telemetry ban, custom invariants, owner formatting prefs |

`project-state.yaml` (volatile, edited by the coordinator as things happen):
`active_now` (autonomy horizon, paused / slow_down / thread_freeze flags,
active milestones, owner autonomy message ids), `notifications_pending`, and a
`control_commands_reference` listing the phrases the owner can type.

`governance-config.json` is the normalized input; re-running the generator on
it reproduces both YAML files byte-for-byte (except `date`), which is how an
audit can diff "what the generator would emit" against "what is there now".

## 8. Acceptance contracts, issues and the roadmap

A plan says how a thread will build something; an acceptance contract says when
the milestone is done, in terms the owner approved before any code exists. With
`acceptance_contracts` on (the default), work enters the project through one
door: the owner gives a specify thread a feature idea or a plan change, and it
returns a contract version, work packages (one GitHub issue each, generated
from the contract) and a roadmap update (`ROLE-10`). Only the owner approves,
and `approval.hash` freezes the criteria. The coordinator picks the contract
up, logs the D-number and batches the packages (`PLAN-03`); plans and PRs cite
criterion ids with proof (`PLAN-04`); reviewers confirm the claims, reading the
diff and the contract before the author's framing (`REV-03`); the coordinator
closes the milestone when every must criterion and the core probe pass
(`PLAN-05`) and winds down work that a plan change removed (`PLAN-06`).

Criteria are written in exactly one place, the contract. Issues cite them;
`roadmap.yaml` orders the milestones; `project-state.yaml` mirrors what is
active. A change in *what done means* goes back through specify; a change in
*how* something is built stays a coordinator decision with a D-number
(`PLAN-01`). Method and details: `references/acceptance-contracts.md`.
