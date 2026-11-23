# claude-project-setup-skill

A Claude Code plugin with one skill, `project-setup`. It sets a repository up so that Claude Code runs it as a small team: a **lead** session that coordinates, **worker** subagents that implement one issue each, and a **reviewer** subagent that did not write the code and cannot edit it. Work starts only from GitHub issues with acceptance criteria the owner approved.

It is for personal and non-commercial projects, in two sizes: a small private project, and a larger public open-source one.

## Install

In a Claude Code session (v2.1.275 or later):

```
/plugin install project-setup --marketplace dubidu22/claude-project-setup-skill
```

Or from your shell, then start a new session:

```
claude plugin marketplace add dubidu22/claude-project-setup-skill
claude plugin install project-setup@claude-project-setup-skill
```

Run the setup in Claude Code on your own computer: cloud sessions (claude.ai/code) do not load installed plugins. The files it writes into your repository work in cloud sessions too.

Without the plugin, copy `skills/project-setup/` into `~/.claude/skills/`, or zip that folder and upload it as a skill on claude.ai. Python 3.10 or later and git must be installed where it runs.

## Use

In the repository you want to set up:

```
/project-setup
```

It looks at the repository, shows one table of what it will write, and asks you to correct it. You make three choices:

| Choice | Options | Decides |
|---|---|---|
| `size` | `solo`, `open-source` | which modules are written |
| `autonomy` | `supervised`, `guided`, `autonomous` | who approves plans and who merges |
| `economy` | `frugal`, `balanced`, `thorough` | models, review rounds, workers in parallel |

Later: `/project-setup change <what you want>` shows the effect and waits for your yes, and `/project-setup check` reports drift and mistakes and changes nothing. The full tables are in [`skills/project-setup/SKILL.md`](skills/project-setup/SKILL.md).

## What it writes into your repository

About a dozen small files (under 16 KB in total), all plain text you can read:

| File | What it is |
|---|---|
| `.claude/project-setup.json` | your settings; the only file you change |
| `CLAUDE.md` (one marked block) | the eleven or twelve rules every session follows |
| `.claude/agents/lead.md`, `worker.md`, `reviewer.md` | the three roles, with their models and tool limits |
| `.claude/rules/critical.md`, `licences.md` | rules that load only when a matching file is touched |
| `.claude/skills/specify/SKILL.md` | `/specify <idea>`: idea to issues with acceptance criteria |
| `.claude/settings.json` | deny rules for force pushes; ask-before-merge when supervised |
| `.github/labeler.yml`, `.github/workflows/labels.yml`, `CONTRIBUTING.md` block | open-source size only |
| `.claude/rules/project.md`, `docs/decisions.md`, `.github/pull_request_template.md` | written once, then yours |

There is no state file: the milestone, issues, pull requests and labels on GitHub are the state.

One step stays yours: protect the default branch on GitHub (require a pull request, block force pushes). The files ask; only GitHub enforces.

## Version 1

Version 1 (`project-governance-init`: a generated YAML ruleset, eight thread roles, acceptance contracts frozen by hash, a ledger) is the last commit on `main` before this version. Version 2 does not migrate a version-1 workspace; a project running on it can stay there.

## Development

```bash
pip install pytest
python3 -m pytest tests -q
```

The tests cover the script: every setting changes what it says it changes, render keeps files that are not its own, and bad configs are refused. How the skill behaves in a live session is covered by the four cases in `evals/`:

```bash
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```

No eval run has been recorded for version 2 yet.

## Licences

This repository: MIT. The label workflow it can write into a project uses [`actions/labeler`](https://github.com/actions/labeler) (MIT), pinned to a commit.
