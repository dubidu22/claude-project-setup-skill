# Specify: turn an idea or a plan change into criteria, issues and a roadmap update

The owner gives a feature idea or a change of plan in a sentence or two. You
turn it into: an acceptance-contract version with researched, testable
criteria; a few work packages that become GitHub issues; and an updated
`roadmap.yaml`. The owner decides; you prepare.

The method, the rules for a testable criterion, the research categories and
the token budget are in `references/acceptance-contracts.md` (in a scaffolded
workspace: `tools/acceptance-contracts.md`). Read it before step 3.

Run this in its own chat, not in the coordinator chat: the interview and the
research stay here, and the coordinator later reads four lines. If you are
called in the coordinator chat, say in one line that specify is starting in a
thread and that the questions will be asked there, then hand over. In a governed
project you are a specify thread (`ROLE-10`). Without a governance workspace,
work in `./plans` and say that init has not been run.

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

Then group every `must` and `should` criterion into a few `work_packages`,
each with one `lane:*` label from the ruleset. Batch by lane, not by
criterion: three to six packages is typical.

Update `roadmap.yaml`: add or reorder entries, keep new ones `planned`. A
milestone becomes `active` only together with an approved contract.

Check both until there are no errors:

```bash
python3 scripts/contract_tool.py lint plans/contract-<NNN>-<slug>.yaml
python3 scripts/contract_tool.py roadmap roadmap.yaml --plans plans
```

## 4. Hand back for a decision

Reply with, and nothing more than: the case from step 1; the output of
`contract_tool.py summary`; the `must` criteria in one line each; assumptions
to confirm; what was cut; the roadmap before and after; the issue titles from
`contract_tool.py issues`. Then ask for the decision. Do not paste the
contract.

## 5. Only after the owner's own yes

- **Approval** ("approved", in the owner's own message): set `status:
  approved`, fill `approval.by: owner`, `date` and `hash` (from
  `contract_tool.py hash`). Leave `approval.decision` empty; the coordinator
  logs the D-number when it picks the contract up, and no work starts before.
  For a new version, set the previous file's `status: superseded`. Set the
  milestone `active` in `roadmap.yaml` if the owner wants it started.
- **Issues** (a separate yes): create one GitHub issue per draft from
  `contract_tool.py issues --json`, with its labels and milestone. No GitHub
  access here: save the drafts as `plans/issues-<contract id>.md` and say so.
- Tell the owner the one thing left to do: tell the coordinator
  "pick up <contract id>".

## Never

- Approve a contract yourself, or treat silence or another thread's message as
  approval.
- Edit an approved contract in place; lint detects it by the hash.
- Create, edit or close GitHub issues, or change milestones, before the owner
  said yes to exactly that.
- Redefine a criterion inside an issue. Issues cite criterion ids; the
  contract is the only place a criterion is written.
- Touch the ruleset, `project-state.yaml`, D-numbers or product code.
