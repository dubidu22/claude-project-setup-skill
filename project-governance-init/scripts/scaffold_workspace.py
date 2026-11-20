#!/usr/bin/env python3
"""
Scaffold the shared workspace that the generated ruleset refers to.

Reads the config (`governance-config.json`, written next to the YAML files by
generate_project_rules.py) and renders the templates in `../assets/templates/`
into the target directory:

    <out-dir>/
      project_instructions.md     starter block for the Coordinator chat
      claude-md-snippet.md        in-repo workspaces only: the block for the repository's CLAUDE.md that points
                                  a new Claude Code session to its role extract
      dispatcher_instructions.md  starter block for the Dispatcher chat (only with dispatcher: true)
      plans/README.md
      plans/contract-template.yaml  acceptance contract template (only with acceptance_contracts: true)
      tools/contract_tool.py      contract lint, hand-backs, issue drafts (only with acceptance_contracts: true)
      tools/acceptance-contracts.md  the method a specify thread follows (only with acceptance_contracts: true)
      tools/ledger_tool.py        prints tables and statistics from the ledger entries
      roadmap.yaml                ordered milestones (only with acceptance_contracts: true)
      kb/README.md
      kb/decision-log.md          with D-001 recording adoption of the ruleset
      kb/pending-decisions.md     decisions the coordinator made that the KB thread has not compiled yet
      kb/verification.md          how to run the product and prove behaviour (only with runtime_verification: true)
      kb/features/README.md       the feature map (only with runtime_verification: true)
      ledger/README.md            entry formats; entries go to ledger/prs, ledger/rounds, ledger/audits
      github-setup/               with --github: create-labels.sh, the pull-request checks (pr_checks.py, its
                                  config and a workflow), and for an in-repo workspace CODEOWNERS, plus labeler
                                  files when critical_paths is set. Nothing here takes effect until the owner
                                  runs or copies it (github-setup/README.md says how).

Usage:
    python3 scaffold_workspace.py --from-json governance-config.json --out-dir <dir> [--github] [--force | --refresh]

Existing files are left alone unless --force is given, so re-running on a live
workspace never clobbers plans or ledger entries. --refresh overwrites only the
files that are generated from the config and never edited by threads.

Templates use `{{key}}` for any config key (lists are joined with commas,
`token_cfg.<name>` for token numbers) and whole-line markers for optional
parts: `<!-- if:flag -->` ... `<!-- endif -->` and `<!-- if:!flag -->`. Flags:
acceptance_contracts, dispatcher, compaction, in_repo, escalation, contracts_in_repo, runtime_verification.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_project_rules as gen  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"
SCRIPT_DIR = Path(__file__).resolve().parent
CONTRACT_METHOD = SCRIPT_DIR.parent / "references" / "acceptance-contracts.md"
# Templates that are only scaffolded when a feature is on: relative path -> flag.
OPTIONAL_TEMPLATES = {
    "plans/contract-template.yaml": "acceptance_contracts",
    "dispatcher_instructions.md": "dispatcher",
    "kb/verification.md": "runtime_verification",
    "kb/features/README.md": "runtime_verification",
    "claude-md-snippet.md": "in_repo",
}
# Generated from the config and never edited by threads: safe to overwrite on --refresh.
REFRESHABLE = {"project_instructions.md", "dispatcher_instructions.md", "plans/README.md",
               "plans/contract-template.yaml", "kb/README.md", "ledger/README.md", "claude-md-snippet.md"}
LEFTOVERS = {
    "ledger/implementation.md": "an older ledger table; history only, new entries go to ledger/prs/",
    "ledger/review.md": "an older ledger table; history only, new entries go to ledger/rounds/",
    ".github/lanes.yml": "an older label list no tool reads; use github-setup/create-labels.sh (--github)",
}

LABEL_COLOURS = {"lane:core": "B60205", "lane:infra": "D93F0B", "lane:docs": "0E8A16"}
RISK_LABELS = [
    ("risk:high", "B60205", "Critical change: plan approval, strong-model review, full CI matrix"),
    ("risk:low", "C2E0C6", "Routine change within lane ownership"),
    ("full-ci", "1D76DB", "Dispatch the full target_platforms matrix on this PR"),
    ("deferred", "FBCA04", "Review finding deferred from a PR round"),
    ("backlog", "D4C5F9", "Idea cut from an acceptance contract; run specify before building it"),
    ("flaky-test", "E99695", "Quarantined test; fix before release"),
]


def load_config(path: Path) -> dict[str, Any]:
    """Read and normalize the config, so a file from an older generator still renders."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}")
    try:
        return gen.normalize_config(raw)
    except gen.ConfigError as exc:
        raise SystemExit("error: the config is not valid; nothing was written.\n" + "\n".join(f"  - {l}" for l in str(exc).splitlines()))


def mechanics(cfg: dict[str, Any]) -> str:
    ws = cfg["workspace_root"]
    if cfg["environment"] == "claude_code":
        start = (
            "- **Starting a thread (`THR-10`).** If you have a tool that starts a session or subagent, use it and set "
            "the model from `execution_profile.model_routing` there. If you have none, or it cannot set the model, "
            "write a starter block (role, model, the extract to read, the first task) and ask the owner to start a "
            "Claude Code session in the repo on that model (in the CLI: `claude --model <name>`) and paste it. Do not "
            "assume a thread exists or which model it runs on until its first line says so."
        )
        files = (
            f"- **Shared files (`THR-13`, `THR-14`).** Working files live on branch `{cfg['governance_branch']}`: each "
            "thread commits the files it owns there, rebasing before each push, never force-pushing, never on a "
            "product branch. A thread that works on a product branch needs a second worktree for this; put the "
            f"command into every starter block: `git worktree add ../<repo>-{cfg['governance_branch']} "
            f"{cfg['governance_branch']}`. The ruleset, the config, "
            f"{'acceptance contracts, the roadmap ' if cfg['acceptance_contracts'] else ''}and the decision log change on "
            f"`{cfg['default_branch']}` by pull request only, and the copy there is the one that counts. After such a "
            f"merge, merge `{cfg['default_branch']}` into `{cfg['governance_branch']}` so every thread sees it; that "
            f"merge is the {'Dispatcher' if cfg['dispatcher'] else 'Coordinator'}'s job."
        )
    else:
        start = (
            "- **Starting a thread (`THR-10`).** If you have a tool that opens a chat or session in this Project, use "
            "it and set the model from `execution_profile.model_routing` there. If you have none, or it cannot set the "
            "model, write a starter block (role, model, the extract to read, the first task) and ask the owner to open "
            "a new chat in this Project on that model and paste it. Do not assume a thread exists or which model it "
            "runs on until its first line says so."
        )
        files = (
            f"- **Shared files.** Threads share `{ws}`. Every file has one writer (`THR-04`). If a thread turns out "
            "not to be able to read or write there, stop and tell the owner; do not work around it."
        )
    return "\n".join([
        start,
        files,
        "- **Watchdog (`THR-03`).** Nothing wakes you by itself. Run the check every time you are active: take the "
        "time from a tool, never from memory, and compare each waiting thread's newest commit or file change with "
        "`watchdog_interval_minutes`. If the owner wants checks while nobody is active, they set up a scheduled task "
        "that sends you \"watchdog check\"; without one the interval is a lower bound, not a guarantee.",
        "- **Replacement (`THR-02`).** Count a worker's PRs from the ledger entries "
        "(`python3 tools/ledger_tool.py stats`). A compression a thread reports about itself is a second signal, not "
        "the main one.",
    ])


def template_values(cfg: dict[str, Any]) -> tuple[dict[str, str], dict[str, bool]]:
    disp, contracts = bool(cfg["dispatcher"]), bool(cfg["acceptance_contracts"])
    in_repo = cfg["environment"] == "claude_code"
    every = int(cfg["coordinator_compact_every_batches"]) if in_repo else 0
    esc = gen.effective_escalation(cfg)
    values: dict[str, str] = {}
    for k, v in cfg.items():
        if isinstance(v, list):
            values[k] = ", ".join(str(x) for x in v)
        elif isinstance(v, dict):
            for sk, sv in v.items():
                values[f"{k}.{sk}"] = str(sv)
        else:
            values[k] = str(v)
    values.update({
        "today": gen.today_iso(),
        "first_label": cfg["ownership_labels"][0],
        "thread_ops_line": (
            "Hand each batch to the Dispatcher thread, which starts, watches and replaces worker threads; "
            "read its one report per batch and the ledger entries, not worker messages."
            if disp
            else "Start, fitness-check and replace threads per `threads_and_watchdog`; read ledger entries, round "
            "reports and PR state at hand-offs instead of relaying messages between threads."
        ),
        "merge_go_line": (
            "grant merge go for critical PRs (the Dispatcher grants it for PRs the review thread confirmed non-critical)"
            if disp
            else "grant merge go (only with no open must-fix finding in the latest round, `MRG-01`)"
        ),
        "contract_line": (
            "New features and plan changes reach you as an owner-approved acceptance contract from a specify "
            "thread. Pick one up only when the owner's message names its hash (\"pick up C-002 3fa9c1d2e4b7\"); if "
            "it does not, ask for the hash from their approval. Then run `python3 tools/contract_tool.py pickup "
            "<contract> --hash <that hash> --decision D-<n>`. It checks the contract against that hash"
            + (" and against the copy on the default branch" if in_repo else "") + " and prints the line to record; "
            "if it refuses, record nothing and tell the owner. Put the printed line into `approved_contracts` of the "
            "state file and into `kb/pending-decisions.md` with the owner's message, mirror the roadmap's active "
            "milestones, then batch the work packages by lane (`PLAN-03`). Never edit a contract. If the owner "
            "brings you a feature idea directly, point them to specify; a change in how something is built stays "
            "with you."
            if contracts
            else "Keep milestone goals in `project-state.yaml` current."
        ),
        "or_contract": " or an approved acceptance contract" if contracts else "",
        "state_contract_items": ", picked-up contracts" if contracts else "",
        "plan_contract_clause": "the contract criterion ids it covers, " if contracts else "",
        "never_contract": "acceptance contracts, " if contracts else "",
        "or_criterion": " or an acceptance criterion" if contracts else "",
        "compact_when": "a batch" if every == 1 else f"every {every}th batch",
        "mechanics_block": mechanics(cfg),
        "escalation_line": (
            f"- Escalate by model (`REV-04`): a non-critical PR with must-fix findings after round {esc} goes to a "
            f"fresh implementation thread on {cfg['critical_model']}, started from the round reports; it gets "
            f"{cfg['rounds_after_escalation']} more round(s), then the PR stops for the Coordinator."
            if esc
            else "- A non-critical PR whose rounds are used up with must-fix findings open stops for the Coordinator "
            "(`REV-01`); must-fix findings are never deferred to issues."
        ),
    })
    flags = {"acceptance_contracts": contracts, "dispatcher": disp, "compaction": every > 0,
             "in_repo": in_repo, "escalation": bool(esc), "contracts_in_repo": contracts and in_repo,
             "runtime_verification": bool(cfg["runtime_verification"])}
    return values, flags


def render(text: str, values: dict[str, str], flags: dict[str, bool], name: str = "") -> str:
    out_lines: list[str] = []
    keep = True
    for line in text.splitlines():
        m = re.fullmatch(r"\s*<!--\s*if:(!?)([\w]+)\s*-->\s*", line)
        if m:
            if m.group(2) not in flags:
                raise SystemExit(f"error: template {name} uses unknown flag '{m.group(2)}'")
            keep = flags[m.group(2)] != bool(m.group(1))
            continue
        if re.fullmatch(r"\s*<!--\s*endif\s*-->\s*", line):
            keep = True
            continue
        if keep:
            out_lines.append(line)
    missing: set[str] = set()

    def sub(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key in values:
            return values[key]
        missing.add(key)
        return m.group(0)

    out = re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub, "\n".join(out_lines) + "\n")
    if missing:
        print(f"warning: unfilled placeholders in {name}: {', '.join(sorted(missing))}", file=sys.stderr)
    return out


def sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def labels_script(cfg: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"# {gen.one_line(cfg['project_name'])}: creates the GitHub labels the ruleset refers to. Safe to run again (--force updates).",
        "# Needs the GitHub CLI, signed in with access to the repository. Run it yourself: threads do not change",
        "# repository settings (ROLE-14).",
        "set -eu",
        f"REPO=${{1:-{sh_quote(cfg['repo_slug'])}}}",
        "",
    ]
    for label in cfg["ownership_labels"]:
        colour = LABEL_COLOURS.get(label, "5319E7")
        if label == "lane:core":
            desc = "Shared core files: critical, requires lane:infra, single-thread lock"
        elif label == "lane:infra":
            desc = "Cross-cutting/infra changes; the lock for touching core"
        elif label == "lane:docs":
            desc = "Documentation; any lane may edit"
        else:
            desc = f"File ownership for the {label.split(':', 1)[-1]} area"
        lines.append(f"gh label create {sh_quote(label)} --repo \"$REPO\" --color {colour} --description {sh_quote(desc)} --force")
    for name, colour, desc in RISK_LABELS:
        lines.append(f"gh label create {sh_quote(name)} --repo \"$REPO\" --color {colour} --description {sh_quote(desc)} --force")
    lines += ["", "# Execution lanes (one concurrent implementation thread each): " + ", ".join(cfg["execution_lanes"]),
              "# " + gen.one_line(cfg["lane_mapping_note"])]
    return "\n".join(lines) + "\n"


def repo_path(cfg: dict[str, Any]) -> str:
    """The workspace folder as a path from the repository root, for CODEOWNERS ('' when it is the root)."""
    ws = cfg["workspace_root"].replace("\\", "/")
    ws = re.sub(r"^\./", "", ws).strip("/")
    return "" if ws in ("", ".") else ws


def codeowners(cfg: dict[str, Any]) -> str:
    base = "/" + repo_path(cfg) + "/" if repo_path(cfg) else "/"
    owner = "@" + cfg["owner_gh"].lstrip("@")
    paths = [base + "claude-project-rules.yaml", base + "governance-config.json", base + "rules/"]
    # the pull-request checks, their config and their exemptions: a thread must not be able to change what is checked
    paths += ["/.github/governance/", "/.github/workflows/governance-pr-checks.yml"]
    if cfg["acceptance_contracts"]:
        paths += [base + "plans/contract-*", base + "roadmap.yaml"]
    width = max(len(p) for p in paths) + 2
    return "\n".join([
        "# Governance files only the owner approves. Add these lines to the repository's CODEOWNERS file",
        f"# (.github/CODEOWNERS) and require code-owner review on `{cfg['default_branch']}` in the branch protection.",
        "# Then an acceptance contract or a ruleset change reaches the default branch only through a pull request",
        "# the owner has reviewed, whatever a thread writes elsewhere.",
        *[p.ljust(width) + owner for p in paths],
    ]) + "\n"


def labeler_files(cfg: dict[str, Any]) -> dict[str, str]:
    globs = "\n".join(f"          - {gen.yaml_quote(g)}" for g in cfg["critical_paths"])
    config = (
        "# Paths whose change is critical (project_profile.critical_paths). Copy to .github/labeler.yml.\n"
        "\"risk:high\":\n"
        "  - changed-files:\n"
        "      - any-glob-to-any-file:\n" + globs + "\n"
    )
    workflow = "\n".join([
        "# Sets risk:high on pull requests that touch critical paths, so criticality does not rest on a thread's",
        "# own judgement alone (CRIT-03). Copy to .github/workflows/labeler.yml. Check the action's current",
        "# version and settings before use: https://github.com/actions/labeler",
        "name: label critical paths",
        "on:",
        "  pull_request_target:",
        "permissions:",
        "  contents: read",
        "  pull-requests: write",
        "jobs:",
        "  label:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/labeler@v5",
        "        with:",
        "          sync-labels: false",
    ]) + "\n"
    return {"labeler.yml": config, "labeler-workflow.yml": workflow}


def pr_checks_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Config for pr_checks.py: what a machine can check about a pull request."""
    labels = list(cfg["ownership_labels"])
    paths: dict[str, list[str]] = {}
    for entry in cfg["label_paths"]:
        label, _, glob = entry.partition("=")
        paths.setdefault(label, []).append(glob)
    ws = repo_path(cfg)
    return {
        "ownership_labels": labels,
        "label_paths": paths,
        "open_labels": [l for l in ("lane:docs",) if l in labels],
        "lock_label": "lane:infra" if {"lane:infra", "lane:core"} <= set(labels) else "",
        "locked_label": "lane:core" if {"lane:infra", "lane:core"} <= set(labels) else "",
        "critical_paths": list(cfg["critical_paths"]),
        "doc_paths": list(cfg["doc_paths"]),
        "governance_paths": [ws + "/**"] if cfg["environment"] == "claude_code" and ws else [],
    }


PR_CHECKS_WORKFLOW = """\
# Runs the pull-request checks a machine can do (title, closing keywords, lane label, file ownership,
# critical paths, new markdown files, narrating comments), so they are not left to a thread remembering a rule. Copy to
# .github/workflows/governance-pr-checks.yml, with pr_checks.py and pr-checks.json in .github/governance/.
# Then make this check required in the branch protection of the default branch.
# Not run by the skill's own tests: check the syntax and the action versions before relying on it.
name: governance pr checks
on:
  pull_request:
    types: [opened, edited, synchronize, reopened, labeled, unlabeled]
permissions:
  contents: read
  pull-requests: read
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check title, labels, ownership and critical paths
        env:
          PR_TITLE: ${{ github.event.pull_request.title }}
          PR_LABELS: ${{ join(github.event.pull_request.labels.*.name, ',') }}
          PR_BASE: ${{ github.event.pull_request.base.sha }}
          PR_HEAD: ${{ github.event.pull_request.head.sha }}
        run: |
          git diff --name-status "$PR_BASE...$PR_HEAD" > "$RUNNER_TEMP/changed.txt"
          git log --format=%B "$PR_BASE..$PR_HEAD" > "$RUNNER_TEMP/commits.txt"
          git diff "$PR_BASE...$PR_HEAD" > "$RUNNER_TEMP/diff.txt"
          python3 .github/governance/pr_checks.py --config .github/governance/pr-checks.json \\
            --title "$PR_TITLE" --labels "$PR_LABELS" \\
            --files "$RUNNER_TEMP/changed.txt" --commits "$RUNNER_TEMP/commits.txt" --diff "$RUNNER_TEMP/diff.txt"
"""


def github_readme(cfg: dict[str, Any], names: list[str]) -> str:
    lines = [
        "# github-setup/",
        "",
        "Files for the owner to apply to the repository. Nothing here takes effect by being in this folder, and no",
        "thread applies it: repository settings are the owner's (`ROLE-14`).",
        "",
        "- `create-labels.sh`: creates the lane and risk labels. Run `bash create-labels.sh` (GitHub CLI, signed in).",
        "- `pr_checks.py`, `pr-checks.json`, `pr-checks-workflow.yml`: the pull-request checks a machine can do "
        "(title format, no closing keywords in commits, a lane label, file ownership by path, `risk:high` on critical "
        "paths, no new markdown file outside `doc_paths`, and a warning for added comments that narrate the change, "
        "`PR-05`). Copy the first two to `.github/governance/` and the workflow to "
        "`.github/workflows/governance-pr-checks.yml`. Try it locally first: "
        "`python3 pr_checks.py --config pr-checks.json --title \"cli: add import (#12)\" --labels lane:cli "
        "--files changed.txt --commits commits.txt`."
        " `pr-check-exemptions.json` goes to `.github/governance/` too: a file that has to break a path check is "
        "listed there as `sanctioned` (permanent, with a reason) or `debt` (with a reason and the issue that removes "
        "it); nothing else lets a PR past a check (`PR-04`). The format is in the header of `pr_checks.py`. "
        "Known gaps, on purpose: the checks stop accidents, not intent. They are only as strong as the branch "
        "protection that requires them and the owner review of `.github/governance/`."
        + ("" if cfg["label_paths"] else " File ownership is not checked yet: set `label_paths` in the governance "
           "config (for example `lane:cli=src/cli/**`) and scaffold again."),
    ]
    if "CODEOWNERS" in names:
        lines.append(f"- `CODEOWNERS`: add its lines to `.github/CODEOWNERS` and require code-owner review on "
                     f"`{cfg['default_branch']}`. This is what makes contract approval and ruleset changes the owner's own review.")
    if "labeler.yml" in names:
        lines.append("- `labeler.yml` and `labeler-workflow.yml`: copy to `.github/labeler.yml` and "
                     "`.github/workflows/labeler.yml`. CI then sets `risk:high` on PRs that touch `critical_paths`.")
    lines += [
        "",
        "## Branch protection on `" + cfg["default_branch"] + "`",
        "",
        "These rules have no script, because only the repository's settings can enforce them. Set them once; they",
        "replace rule prose that a thread would otherwise have to remember:",
        "",
        "- Require a pull request before merging (no direct pushes): `ROLE-06`.",
        "- Block force pushes: `PR-03`, `MRG-01`.",
        "- Require status checks to pass: your CI and `governance pr checks`: `PR-02`, `CI-01`.",
    ]
    if "CODEOWNERS" in names:
        lines.append("- Require review from Code Owners: contract approval and ruleset changes.")
    return "\n".join(lines) + "\n"


def roadmap_yml(cfg: dict[str, Any]) -> str:
    lines = [
        f"# {gen.one_line(cfg['project_name'])}: roadmap. Order is priority. The owner decides it; a specify thread is its",
        "# only writer; the coordinator mirrors `active` milestones into project-state.yaml.",
        "# Check: python3 tools/contract_tool.py roadmap roadmap.yaml --plans plans",
        "# status: planned | active | done | dropped. A milestone turns active only with an approved contract.",
        "milestones:",
    ]
    for name in cfg["active_milestones"] or ["v0.1"]:
        lines += [f"  - name: {gen.yaml_quote(name)}", "    goal: \"\"", "    status: planned", "    contract: \"\""]
    return "\n".join(lines) + "\n"


def write(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return f"kept     {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote    {path}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold the shared governance workspace from a config JSON")
    ap.add_argument("--from-json", type=Path, required=True, help="governance-config.json written by the generator")
    ap.add_argument("--out-dir", type=Path, default=Path("."), help="workspace directory to scaffold into")
    ap.add_argument("--github", action="store_true",
                    help="also write github-setup/: a label script, and for an in-repo workspace a CODEOWNERS snippet and labeler files")
    ap.add_argument("--force", action="store_true", help="overwrite files that already exist")
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="overwrite only the files generated from the config (instructions, READMEs, the contract template, "
        "tools/); ledger entries, the decision log, the roadmap and github-setup/ are left alone",
    )
    args = ap.parse_args()

    if not TEMPLATE_DIR.is_dir():
        print(f"error: template directory not found at {TEMPLATE_DIR}", file=sys.stderr)
        return 2
    cfg = load_config(args.from_json)
    values, flags = template_values(cfg)
    out = args.out_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for tpl in sorted(TEMPLATE_DIR.rglob("*")):
        if not tpl.is_file():
            continue
        rel = tpl.relative_to(TEMPLATE_DIR)
        needs = OPTIONAL_TEMPLATES.get(rel.as_posix())
        if needs and not flags[needs]:
            continue
        results.append(write(out / rel, render(tpl.read_text(encoding="utf-8"), values, flags, rel.as_posix()),
                             args.force or (args.refresh and rel.as_posix() in REFRESHABLE)))
    tool_force = args.force or args.refresh
    results.append(write(out / "tools" / "ledger_tool.py", (SCRIPT_DIR / "ledger_tool.py").read_text(encoding="utf-8"), tool_force))
    if flags["acceptance_contracts"]:
        results.append(write(out / "tools" / "contract_tool.py", (SCRIPT_DIR / "contract_tool.py").read_text(encoding="utf-8"), tool_force))
        results.append(write(out / "tools" / "acceptance-contracts.md", CONTRACT_METHOD.read_text(encoding="utf-8"), tool_force))
        results.append(write(out / "roadmap.yaml", roadmap_yml(cfg), args.force))
    if args.github:
        files = {
            "create-labels.sh": labels_script(cfg),
            "pr_checks.py": (SCRIPT_DIR / "pr_checks.py").read_text(encoding="utf-8"),
            "pr-checks.json": json.dumps(pr_checks_config(cfg), indent=2) + "\n",
            "pr-checks-workflow.yml": PR_CHECKS_WORKFLOW,
        }
        # exemptions are the project's own record: created empty once, never overwritten, not even with --force
        exemptions = out / "github-setup" / "pr-check-exemptions.json"
        if not exemptions.exists():
            results.append(write(exemptions, "[]\n", False))
        else:
            results.append(f"kept     {exemptions}")
        if flags["in_repo"]:
            files["CODEOWNERS"] = codeowners(cfg)
            if cfg["critical_paths"]:
                files.update(labeler_files(cfg))
        files["README.md"] = github_readme(cfg, list(files))
        for name, content in files.items():
            results.append(write(out / "github-setup" / name, content, args.force))

    if not flags["dispatcher"] and (out / "dispatcher_instructions.md").exists():
        results.append("note     dispatcher_instructions.md is left over from a setup with a dispatcher; it is no longer used")
    if not flags["acceptance_contracts"]:
        for rel in ("plans/contract-template.yaml", "tools/contract_tool.py", "roadmap.yaml"):
            if (out / rel).exists():
                results.append(f"note     {rel} is left over from a setup with acceptance contracts; it is no longer used")
    for rel, why in LEFTOVERS.items():
        if (out / rel).exists():
            results.append(f"note     {rel} is {why}")
    print("\n".join(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
