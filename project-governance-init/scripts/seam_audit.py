#!/usr/bin/env python3
"""
Seam audit: read files that work together, together.

A review round reads one pull request's diff. A batch audit reads what a batch changed. Neither reads two
neighbouring files side by side as they are now, and that is where contracts between files break: the
exception one module raises and the status another maps it to, the state a caller inspects before it calls
a mutator, the helper that exists twice, the comment that cites a decision the code has since left.

    python3 seam_audit.py brief [--closed-issues "12,15"]   # the brief for the audit session; paste it as the prompt
    python3 seam_audit.py refs  [--closed-issues "12,15"]   # only the D-numbers and issue numbers cited in the groups
    python3 seam_audit.py check <ledger/audits/seam-YYYY-MM-DD.md>   # is the report in the agreed shape?

The groups come from `seam_groups` in governance-config.json (`<name>=<path>,<path>`, globs allowed), read
from the workspace this script sits in (`<workspace>/tools/`) or from --workspace. The repository root is the
nearest folder with `.git` above the workspace, or --repo.

The brief is fixed text plus the files of each group, so every seam audit asks the same four questions:

    parity      error and status mapping: every domain error a module raises is mapped by the handlers that
                call it (API status, CLI exit code, user message), and to the same thing in each of them
    state       state boundary: a caller reads another module's internal state (a flag, a lock, a cache) and
                then calls a mutator, instead of asking the module to do both
    duplicate   the same low-level helper written twice in sibling modules
    drift       a comment cites a decision (D-012) or an issue (#31) for an invariant the code no longer keeps

`refs` does the mechanical part of the fourth question: it lists every D-number and issue number cited in
the grouped files and marks a decision that the decision log says was superseded, a decision that is not in
the log, and an issue named in --closed-issues. Whether the code still keeps the invariant is the session's
call; the list only says where to look.

The report is at most ten findings, most harmful first, one per line under `## Findings`:

    <n>. <kind> | <verdict> | <group> | <what is wrong, in one sentence> | <file>:<line>, <file>:<line>

kind is one of the four above; verdict is one of ROLE-15 (check, rule, split, owner, leave). `check` refuses
a report with more than ten findings, a kind outside the four, a file that is not in the named group, or a
configured group that was neither read nor listed as skipped with a reason. The session edits no file; each
finding becomes an issue or an entry in ledger/deferred/, where `ledger_tool.py triage` asks for a decision.

This script writes no file. Exit code: 0 ok, 1 findings (`check`), 2 bad input.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

KINDS = {
    "parity": "Error and status mapping. List the domain errors each module raises or returns. For each, find every handler "
              "in the group that can receive it (API route, CLI command, job runner) and what it maps it to. Report an error "
              "that a handler does not map, and one that two handlers map to different things.",
    "state": "State boundary. Find a caller that reads another module's internal state (a flag, a lock, a cache, a status "
             "field) and then calls a function that changes it. Between the read and the call the state can change. Report "
             "the pair; the fix is one function in the owning module that does both.",
    "duplicate": "Duplicated helpers. Find the same low-level helper written in two sibling modules (a decoder, a converter, "
                 "a path or retry helper). Report both places and which one the other should call.",
    "drift": "Comment drift. For each D-number or issue number listed below, read the comment and the code it sits on. "
             "Report a comment that states an invariant the code no longer keeps. A superseded decision or a closed "
             "issue is where to look first, not proof.",
}
VERDICTS = ("check", "rule", "split", "owner", "leave")
MAX_FINDINGS = 10
MAX_FILE_BYTES = 1_000_000
D_REF = re.compile(r"\bD-(\d{1,4})\b")
ISSUE_REF = re.compile(r"(?:^|[\s(\[,;:])#(\d{1,5})\b")


class BadInput(Exception):
    pass


def find_workspace(arg: Path | None) -> Path:
    ws = arg or Path(__file__).resolve().parent.parent
    if not (ws / "governance-config.json").is_file():
        raise BadInput(f"{ws} has no governance-config.json; pass --workspace <the governance folder>")
    return ws


def find_repo(arg: Path | None, ws: Path) -> Path:
    if arg:
        if not arg.is_dir():
            raise BadInput(f"--repo {arg} is not a folder")
        return arg
    for folder in [ws, *ws.resolve().parents]:
        if (folder / ".git").exists():
            return folder
    raise BadInput("no git checkout above the workspace; pass --repo <the repository checkout>")


def load_groups(ws: Path) -> dict[str, list[str]]:
    try:
        cfg = json.loads((ws / "governance-config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BadInput(f"cannot read {ws / 'governance-config.json'}: {exc}") from exc
    groups: dict[str, list[str]] = {}
    for entry in cfg.get("seam_groups") or []:
        name, _, rest = str(entry).partition("=")
        paths = [x.strip() for x in rest.split(",") if x.strip()]
        if name.strip() and paths:
            groups[name.strip()] = paths
    if not groups:
        raise BadInput("no seam_groups in the config. Name the files that work together, e.g. "
                       "--set 'seam_groups=[\"web=web/api.py,web/jobs.py\"]' through \"Changing settings\"; they are not guessed")
    return groups


def in_group(path: str, globs: list[str]) -> bool:
    return any(path == g or fnmatch.fnmatchcase(path, g) for g in globs)


def resolve(repo: Path, globs: list[str]) -> tuple[list[str], list[str]]:
    """(files of the group that exist, entries that match nothing), paths relative to the repository root."""
    found: list[str] = []
    missing: list[str] = []
    for g in globs:
        hits = sorted(p.relative_to(repo).as_posix() for p in repo.glob(g) if p.is_file() and ".git/" not in p.as_posix()) \
            if any(c in g for c in "*?[") else ([g] if (repo / g).is_file() else [])
        if not hits:
            missing.append(g)
        found += [h for h in hits if h not in found]
    return found, missing


def decisions(ws: Path) -> tuple[set[str], dict[str, str]]:
    """(D-numbers the decision log has, superseded D-number -> the one that superseded it)."""
    log = ws / "kb" / "decision-log.md"
    known: set[str] = set()
    superseded: dict[str, str] = {}
    if not log.is_file():
        return known, superseded
    current = ""
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^#{1,4}\s+D-(\d{1,4})\b", line)
        if m:
            current = f"D-{int(m.group(1)):03d}"
            known.add(current)
            continue
        if current and re.search(r"\bsupersed", line, re.IGNORECASE):
            for n in D_REF.findall(line):
                old = f"D-{int(n):03d}"
                if old != current:
                    superseded.setdefault(old, current)
    return known, superseded


def refs_in(repo: Path, files: list[str], known: set[str], superseded: dict[str, str], closed: set[int] | None) -> list[str]:
    out: list[str] = []
    for rel in files:
        p = repo / rel
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                out.append(f"{rel}: too large to scan ({p.stat().st_size} bytes)")
                continue
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for n in D_REF.findall(line):
                d = f"D-{int(n):03d}"
                note = f"SUPERSEDED by {superseded[d]}" if d in superseded else ("" if d in known or not known else "NOT IN THE DECISION LOG")
                out.append(f"{rel}:{i}: {d}" + (f"  <- {note}" if note else ""))
            for n in ISSUE_REF.findall(line):
                note = "CLOSED" if closed is not None and int(n) in closed else ""
                out.append(f"{rel}:{i}: #{n}" + (f"  <- {note}" if note else ""))
    return out


def brief(ws: Path, repo: Path, groups: dict[str, list[str]], closed: set[int] | None) -> str:
    known, superseded = decisions(ws)
    lines = [
        "You are an audit thread doing a seam audit. This session is read-only: you open files and write one report. You "
        "change no code, no test and no governance file, and you open no pull request.",
        "",
        "Read each group below as a whole: open all its files before you judge any of them. Do not read files outside the "
        "groups unless a finding cannot be confirmed without one, and then only that file.",
        "",
        "Check these four things and nothing else. Anything else you notice stays out of the report.",
        "",
    ]
    lines += [f"{i}. {kind}: {text}" for i, (kind, text) in enumerate(KINDS.items(), 1)]
    lines += ["", "Groups:"]
    for name, globs in groups.items():
        files, missing = resolve(repo, globs)
        lines.append(f"\n  {name}:")
        lines += [f"    {f}" for f in files]
        lines += [f"    (no file matches {m}: say so under `Groups skipped` if nothing is left to read)" for m in missing]
        refs = refs_in(repo, files, known, superseded, closed)
        if refs:
            lines.append("    cited decisions and issues (for check 4):")
            lines += [f"      {r}" for r in refs]
    today_file = f"{ws.name}/ledger/audits/seam-<YYYY-MM-DD>.md"
    lines += [
        "",
        f"Write the report to {today_file} in exactly this shape:",
        "",
        "    # Seam audit <YYYY-MM-DD>",
        "    Groups read: <name>, <name>",
        "    Groups skipped: <name> (<reason>)        <- only if one was skipped",
        "",
        "    ## Findings",
        "    1. <kind> | <verdict> | <group> | <what is wrong, in one sentence> | <file>:<line>, <file>:<line>",
        "",
        f"kind: {', '.join(KINDS)}. verdict: {', '.join(VERDICTS)} (ROLE-15). At most {MAX_FINDINGS} findings, the most harmful "
        "first; if there are more, keep the ten that matter and say how many you left out in a last line `Left out: <n>`. "
        "If you find nothing, write `none` under `## Findings`. Every finding names the lines you read, and you have read "
        "them: a finding from memory of a similar codebase is not a finding.",
        "",
        f"Then run: python3 {ws.name}/tools/seam_audit.py check <the report>. Hand the report to the coordinator; each "
        "finding becomes an issue or an entry in ledger/deferred/.",
    ]
    return "\n".join(lines) + "\n"


def check_report(path: Path, groups: dict[str, list[str]] | None) -> list[str]:
    out: list[str] = []
    if not re.fullmatch(r"seam-\d{4}-\d{2}-\d{2}(-\d+)?\.md", path.name):
        out.append(f"the file name must be seam-<YYYY-MM-DD>.md, got {path.name}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BadInput(f"cannot read {path}: {exc}") from exc
    read = re.search(r"^Groups read:\s*(.*)$", text, re.MULTILINE)
    skipped = re.search(r"^Groups skipped:\s*(.*)$", text, re.MULTILINE)
    read_names = [x.strip() for x in read.group(1).split(",") if x.strip()] if read else []
    skipped_names = [x.split("(")[0].strip() for x in re.split(r",(?![^(]*\))", skipped.group(1)) if x.strip()] if skipped else []
    if not read:
        out.append("no `Groups read:` line")
    if skipped and not all("(" in x and x.rstrip().endswith(")") for x in re.split(r",(?![^(]*\))", skipped.group(1)) if x.strip()):
        out.append("each skipped group gives its reason in brackets: `Groups skipped: web (files were deleted in #40)`")
    if groups is not None:
        unknown = [n for n in read_names + skipped_names if n not in groups]
        if unknown:
            out.append(f"unknown group(s): {', '.join(unknown)}; the configured groups are {', '.join(groups)}")
        untouched = [n for n in groups if n not in read_names and n not in skipped_names]
        if untouched:
            out.append(f"group(s) neither read nor skipped: {', '.join(untouched)}")
    if "## Findings" not in text:
        return out + ["no `## Findings` section"]
    section = re.split(r"^#{1,6}\s", text.split("## Findings", 1)[1], maxsplit=1, flags=re.MULTILINE)[0]
    body = [l.strip() for l in section.splitlines() if l.strip()]
    findings = [l for l in body if re.match(r"^\d+\.\s", l)]
    other = [l for l in body if not re.match(r"^\d+\.\s", l) and l.lower() != "none" and not l.startswith("Left out:")]
    if other:
        out.append(f"lines under `## Findings` that are not findings: {other[0][:80]!r}" + (f" and {len(other) - 1} more" if len(other) > 1 else ""))
    if not findings and "none" not in [l.lower() for l in body]:
        out.append("no finding and no `none`: write `none` when the groups are clean")
    if len(findings) > MAX_FINDINGS:
        out.append(f"{len(findings)} findings; a seam audit reports at most {MAX_FINDINGS}. Keep the most harmful and add `Left out: <n>`")
    for line in findings:
        n = line.split(".", 1)[0]
        parts = [x.strip() for x in line.split(".", 1)[1].split("|")]
        if len(parts) != 5:
            out.append(f"finding {n}: needs five parts `kind | verdict | group | what | where`, has {len(parts)}")
            continue
        kind, verdict, group, what, where = parts
        if kind not in KINDS:
            out.append(f"finding {n}: kind '{kind}' is not one of {', '.join(KINDS)}; a seam audit checks these four things only")
        if verdict not in VERDICTS:
            out.append(f"finding {n}: verdict '{verdict}' is not one of {', '.join(VERDICTS)}")
        if len(what) < 15:
            out.append(f"finding {n}: say what is wrong in a sentence")
        places = [x.strip() for x in where.split(",") if x.strip()]
        bad = [x for x in places if not re.fullmatch(r"[^\s:]+:\d+(-\d+)?", x)]
        if not places or bad:
            out.append(f"finding {n}: `where` lists <file>:<line> places" + (f", got {bad[0]!r}" if bad else ""))
        elif kind in ("parity", "state", "duplicate") and len({x.rsplit(":", 1)[0] for x in places}) < 2:
            out.append(f"finding {n}: a {kind} finding is between files; name the place in each of them")
        if groups is not None and group in groups:
            outside = [x.rsplit(":", 1)[0] for x in places if re.fullmatch(r"[^\s:]+:\d+(-\d+)?", x)
                       and not in_group(x.rsplit(":", 1)[0], groups[group])]
            if outside:
                out.append(f"finding {n}: {', '.join(sorted(set(outside)))} is not in the group '{group}'")
        elif groups is not None:
            out.append(f"finding {n}: unknown group '{group}'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Seam audit: the brief, the cited decisions and issues, and the report check")
    ap.add_argument("cmd", choices=["brief", "refs", "check"])
    ap.add_argument("report", nargs="?", type=Path, help="check: the report file")
    ap.add_argument("--workspace", type=Path, help="the governance folder (default: the folder above this script's)")
    ap.add_argument("--repo", type=Path, help="the repository checkout (default: the nearest .git above the workspace)")
    ap.add_argument("--closed-issues", help="comma-separated numbers of closed issues, to mark them in the list")
    args = ap.parse_args()
    try:
        closed = None
        if args.closed_issues is not None:
            closed = {int(n.strip().lstrip("#")) for n in args.closed_issues.split(",") if n.strip()}
        if args.cmd == "check":
            if not args.report:
                raise BadInput("check needs the report file")
            try:
                groups = load_groups(find_workspace(args.workspace))
            except BadInput:
                groups = None  # a report can still be checked for its shape without the config
            found = check_report(args.report, groups)
            print("\n".join(found) if found else f"{args.report.name}: in shape." + ("" if groups is not None else
                  " (No config found: groups and file membership were not checked.)"))
            return 1 if found else 0
        ws = find_workspace(args.workspace)
        groups = load_groups(ws)
        repo = find_repo(args.repo, ws)
        if args.cmd == "brief":
            print(brief(ws, repo, groups, closed), end="")
            return 0
        known, superseded = decisions(ws)
        for name, globs in groups.items():
            files, missing = resolve(repo, globs)
            refs = refs_in(repo, files, known, superseded, closed)
            print(f"{name}: {len(files)} file(s)" + (f", nothing matches {', '.join(missing)}" if missing else ""))
            print("\n".join(f"  {r}" for r in refs) if refs else "  no decision or issue is cited")
        return 0
    except (BadInput, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
