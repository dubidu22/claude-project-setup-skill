#!/usr/bin/env python3
"""
Deterministic checks for a pull request, so the rules that a machine can check are not left to prose.

    python3 pr_checks.py --config pr-checks.json --title "<PR title>" --labels "lane:cli,risk:low" \
        --files changed.txt --commits commits.txt [--json]

    changed.txt   output of `git diff --name-status <base>...<head>` (plain paths, one per line, also work)
    commits.txt   output of `git log --format=%B <base>..<head>`

What it checks (rule ids of the generated ruleset):
    title        PR-01   '<area>: <outcome> (#N)'
    commits      PR-01   no closing keyword (Closes #N, Fixes #N, ...) in a commit message
    lane label   LANE-03 the PR carries at least one file-ownership label
    ownership    LANE-03 every changed file that a label owns is owned by one of the PR's labels
                         (a docs label is open to every lane; core files need the lock label)
    critical     CRIT-01 a PR that touches a critical path carries risk:high
    tests        TST-02  deleted test files are listed as a warning for the reviewer

A pull request that only changes governance files (the workspace folder) is exempt from the title, label
and ownership checks: decision-log and contract pull requests follow other rules.

Exit code: 0 no failure, 1 at least one failure, 2 bad arguments or config. Reads only; standard library only.
The config is written by scaffold_workspace.py --github from governance-config.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TITLE_RE = re.compile(r"^[^\s:][^:]*: \S.* \(#\d+\)$")
CLOSING_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#\d+", re.IGNORECASE)
TEST_FILE_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|[._-](test|spec)\.[A-Za-z]+$|_test\.[A-Za-z]+$")


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Path glob from the repository root: `**` crosses folders, `*` and `?` stay inside one path segment."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, globs: list[str]) -> bool:
    return any(glob_to_regex(g).match(path) for g in globs)


def read_changes(text: str) -> list[tuple[str, str]]:
    """(status, path) per changed file. Renames count as the new path; plain path lines get status 'M'."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and re.fullmatch(r"[ACDMRTUXB]\d*", parts[0]):
            out.append((parts[0][0], parts[-1].strip()))
        else:
            out.append(("M", line.strip()))
    return out


def run_checks(cfg: dict, title: str, labels: list[str], changes: list[tuple[str, str]], commits: str) -> list[dict]:
    results: list[dict] = []

    def add(check: str, status: str, message: str) -> None:
        results.append({"check": check, "status": status, "message": message})

    paths = [p for _, p in changes]
    governance = cfg.get("governance_paths") or []
    governance_only = bool(paths) and bool(governance) and all(matches(p, governance) for p in paths)
    ownership = cfg.get("ownership_labels") or []
    label_paths: dict[str, list[str]] = cfg.get("label_paths") or {}
    mine = [l for l in labels if l in ownership]

    # commits: never exempt, a closing keyword closes an issue whatever the pull request is about
    hits = sorted({m.group(0) for m in CLOSING_RE.finditer(commits)})
    if hits:
        add("commits", "FAIL", f"closing keyword in a commit message ({', '.join(hits)}); closing keywords belong in the PR body only (PR-01)")
    else:
        add("commits", "ok", "no closing keyword in commit messages")

    if governance_only:
        add("scope", "ok", "only governance files changed: title, lane label and ownership checks do not apply")
    else:
        if TITLE_RE.match(title.strip()):
            add("title", "ok", "title has the form '<area>: <outcome> (#N)'")
        else:
            add("title", "FAIL", f"title '{title.strip()}' does not have the form '<area>: <outcome> (#N)' (PR-01)")

        if ownership:
            if mine:
                add("lane label", "ok", f"file-ownership label(s): {', '.join(mine)}")
            else:
                add("lane label", "FAIL", f"the PR carries none of the file-ownership labels ({', '.join(ownership)}) (LANE-03)")

        if label_paths:
            open_labels = [l for l in cfg.get("open_labels") or [] if l in label_paths]
            lock, locked = cfg.get("lock_label") or "", cfg.get("locked_label") or ""
            foreign, unowned, unlocked = [], [], []
            for path in paths:
                if governance and matches(path, governance):
                    continue
                owners = [l for l, globs in label_paths.items() if matches(path, globs)]
                if not owners:
                    unowned.append(path)
                    continue
                if lock and locked and locked in owners and lock in ownership and lock not in labels:
                    unlocked.append(path)
                if not (set(owners) & set(mine)) and not (set(owners) & set(open_labels)):
                    foreign.append(f"{path} ({', '.join(owners)})")
            if foreign:
                add("ownership", "FAIL", f"files outside the PR's labels ({', '.join(mine) or 'none'}): {'; '.join(foreign)} (LANE-03)")
            else:
                add("ownership", "ok", "every owned file belongs to one of the PR's labels")
            if unlocked:
                add("lock", "FAIL", f"files owned by {locked} changed without the {lock} label: {', '.join(unlocked)} (LANE-03)")
            if unowned:
                add("unowned", "WARN", f"files no label owns (one PR at a time, with plan approval): {', '.join(unowned)}")

    critical = [p for p in paths if matches(p, cfg.get("critical_paths") or [])]
    if critical:
        if "risk:high" in labels:
            add("critical", "ok", f"critical paths touched and risk:high is set: {', '.join(critical)}")
        else:
            add("critical", "FAIL", f"critical paths touched without the risk:high label: {', '.join(critical)} (CRIT-01)")

    deleted = [p for status, p in changes if status == "D" and TEST_FILE_RE.search(p)]
    if deleted:
        add("tests", "WARN", f"test files deleted: {', '.join(deleted)}. The reviewer confirms none was removed to turn CI green (TST-02)")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic pull-request checks for a governed repository")
    ap.add_argument("--config", type=Path, required=True, help="pr-checks.json written by scaffold_workspace.py --github")
    ap.add_argument("--title", required=True)
    ap.add_argument("--labels", default="", help="comma-separated labels on the pull request")
    ap.add_argument("--files", type=Path, required=True, help="file with `git diff --name-status` output")
    ap.add_argument("--commits", type=Path, required=True, help="file with the commit messages of the pull request")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        changes = read_changes(args.files.read_text(encoding="utf-8"))
        commits = args.commits.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(cfg, dict):
        print("error: the config must be a JSON object", file=sys.stderr)
        return 2
    labels = [l.strip() for l in args.labels.split(",") if l.strip()]
    results = run_checks(cfg, args.title, labels, changes, commits)
    failed = [r for r in results if r["status"] == "FAIL"]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{r['status']:<4} {r['check']}: {r['message']}")
        print(f"\n{len(failed)} failure(s)." if failed else "\nAll checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
