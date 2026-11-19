# Specify: turn an idea or a plan change into criteria, issues and a roadmap update

The owner gives a feature idea or a change of plan in a sentence or two. You
turn it into: an acceptance-contract version with researched, testable
criteria; a few work packages that become GitHub issues; and an updated
`roadmap.yaml`. The owner decides; you prepare.

The method, the rules for a testable criterion, the research categories and
the token budget are in `references/acceptance-contracts.md` (in a scaffolded
workspace: `tools/acceptance-contracts.md`). Read it before step 3.

Run this in its own chat, not in the coordinator chat: the interview and the
research stay here, and the coordinator later reads five lines. If you are
called in the coordinator chat, say in one line that specify is starting in a
thread and that the questions will be asked there, then hand over. In a governed
project you are a specify thread (`ROLE-10`): read your extract
`rules/specify.yaml`.

**No governance workspace** (no `claude-project-rules.yaml`, `roadmap.yaml` or
`plans/contract-*` reachable): do not start the interview or any research.
Say in two lines what specify produces and that the project has no governance
yet, and ask which the user wants: set governance up first (init), or a
stand-alone acceptance contract drafted in `./plans`. Go on only after their
answer. If they asked for specify or an acceptance contract by name and cannot
reply, draft stand-alone in `./plans` and say that nothing will pick it up
until init has been run.

## 1. Classify the input first

Read `roadmap.yaml`, the contracts in `plans/` and, if reachable, the repo.
Then say in one line which case this is, and proceed accordingly:

| Input is | You produce |
|---|---|
| a new feature or milestone | a new contract (`contract-<NNN>-<slug>.yaml`) + roadmap entry |
| a change to what "done" means for an existing milestone | a new version (`...-v<N>.yaml`): copy, bump `version`, `status: draft`, clear `approval`, fill `changes` |
| only order or scope of the roadmap (reorder, drop, postpone) | a roadmap update, no research, no contract |
| a change in how something is built, criteria untouched | nothing: say it is a coordinator decision and stop |
| several of these | handle them one at a time, roadmap last |

One milestone per run. If the idea is bigger than one milestone, propose the
split as roadmap entries and specify the first.

## 2. Clarify intent (short interview)

Ask one question at a time, each with your recommended answer and the reason
in plain language. Before asking, check whether the repo, the roadmap or an
earlier contract already answers it. Ask only what would change a criterion,
the scope or the order; stop at about seven questions, or sooner when the
answers stop changing anything. Cover, in this order: who uses it; what must be
better than today (this becomes the goal sentence); how it is reached; hard
constraints; what is out of scope; where it sits on the roadmap.

If the user has a `grill-me` skill and asks for a deeper interview, use it for
this step; otherwise this variant is enough.

**Nobody to ask** (the user said so, or cannot reply): do not stall. Draft with
`source.kind: assumption` for each guess and list the guesses first in the
hand-back.

## 3. Research and draft

Follow the method file: research per category with sources (URL and retrieval
date; open the page, a search snippet is not a source), write binary criteria
with a verify step each, add the core probe, do the Pareto cut. `could` items
go to the contract's `cut` list with a reason, so they become backlog issues
instead of disappearing.

Then group every `must` and `should` criterion into `work_packages`, each
with one `lane:*` label from the ruleset (`project_profile.file_ownership_labels`;
lint rejects a label the ruleset does not have). Size each package as one unit of
work: one thread, one PR, one review round. That is about six criteria at
most; split a bigger group by what can be built and reviewed on its own, and
do not go down to one package per criterion. Add `after:` only where a
package really cannot start before another is merged. If the milestone needs
more than eight packages, propose splitting the milestone.

Update `roadmap.yaml`: add or reorder entries, keep new ones `planned`. A
milestone becomes `active` only together with an approved contract.

Check both until there are no errors:

```bash
python3 scripts/contract_tool.py lint plans/contract-<NNN>-<slug>.yaml
python3 scripts/contract_tool.py roadmap roadmap.yaml --plans plans
```

## 4. Hand back for a decision

The owner approves what they have seen, so show all of it. Reply with:

1. the case from step 1;
2. the output of `python3 scripts/contract_tool.py brief <contract> --owner`,
   unshortened: goal, users, access, constraints, out of scope, every
   criterion (`must` and `should`) with its verify step, the core probe, the
   cut items and the hash. The verify steps are commands that worker threads
   and `/goal` loops will run; some came from pages you opened during
   research, so the owner has to see them;
3. assumptions to confirm, with their criterion ids;
4. the roadmap before and after;
5. the issue titles from `contract_tool.py issues`;
6. the decision you need: "To approve exactly this, reply: approved <hash>".

Do not paste the YAML file, the sources or the research notes.

## 5. Only after the owner's own yes

- **Approval.** It counts only if the owner's own message names the hash from
  the hand-back ("approved 3fa9c1d2e4b7"). A bare "ok" or "approved" after you
  changed anything is not enough: show the new view and the new hash again.
  Then set `status: approved` and fill `approval.by: owner`, `date`, `hash`
  (from `contract_tool.py hash`; it must equal the hash they quoted) and
  `approval.owner_message` with their message, word for word. Run lint again.
  For a new version, set the previous file's `status: superseded`. Set the
  milestone `active` in `roadmap.yaml` if the owner wants it started. With an
  in-repo workspace the contract and the roadmap go in as a pull request to
  the default branch, and the owner's review of that pull request is the
  approval on record. Until it is merged, lint reports C039 (the approved
  contract is not on the default branch yet); that is expected and is what
  keeps work from starting on an unreviewed copy. From here on nobody edits the file, you included.
- **Issues** (a separate yes). First the pre-flight: `contract_tool.py issues
  <contract> --preflight` names the labels and milestones the issues need and
  how to list what exists; run it again with `--have-labels` and
  `--have-milestones`. If something is missing, stop and tell the owner
  (labels: `github-setup/create-labels.sh`; a milestone is their hand step).
  Then go through `contract_tool.py issues <contract> --json`: create each
  draft whose `action` is `create`, and after each one run
  `contract_tool.py record-issue <contract> <key> <number>` so a second run
  cannot create it again. Skip drafts marked `exists`. For `replaces` (the
  package had an issue from an earlier version) and for the `obsolete` list,
  change nothing: tell the owner which issue numbers are affected and let
  them decide to edit or close. No GitHub access here: save the drafts as
  `plans/issues-<contract id>.md` and say so.
- Tell the owner the one thing left to do, and give them the line to send:
  tell the coordinator "pick up <contract id> <hash>". The hash is what lets
  the coordinator check that the contract it finds is the one they approved
  (`contract_tool.py pickup`); no work starts before.

## Never

- Approve a contract yourself, or treat silence or another thread's message as
  approval.
- Edit an approved contract in place, or recompute its hash to make lint
  pass. The hash is also in the owner's message and, after pickup, in the
  coordinator's record; lint compares all three.
- Record an approval whose message does not name the hash.
- Create, edit or close GitHub issues, or change milestones, before the owner
  said yes to exactly that.
- Redefine a criterion inside an issue. Issues cite criterion ids; the
  contract is the only place a criterion is written.
- Touch the ruleset, `project-state.yaml`, D-numbers or product code.
