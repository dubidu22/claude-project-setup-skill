#!/usr/bin/env python3
"""
Read the ledger: one small file per PR and per review round (ledger/README.md).

    python3 ledger_tool.py table [--ledger DIR]   # PRs and rounds as markdown tables
    python3 ledger_tool.py stats [--ledger DIR]   # rounds per PR, compactions per PR, PRs per thread
    python3 ledger_tool.py check [--ledger DIR]   # entries with missing or malformed fields (exit 1 if any)

The ledger directory defaults to `../ledger` next to this script's folder (the
scaffolded `tools/`), or `./ledger`. This tool only reads. Entries are flat
`key: value` files, so it needs nothing beyond the standard library.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PR_KEYS = ("pr", "opened", "thread", "lane", "labels", "critical", "compactions")
ROUND_KEYS = ("pr", "round", "date", "thread", "head", "verdict", "must_fix", "should_fix", "report")
INT_KEYS = {"pr", "round", "compactions", "must_fix", "should_fix"}


def read_entry(path: Path) -> dict[str, str]:
    """Flat `key: value` lines; a '#' outside quotes starts a comment."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line, quote = [], ""
        for i, ch in enumerate(raw):
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
                break
            line.append(ch)
        text = "".join(line).strip()
        m = re.match(r"([A-Za-z_][\w-]*):\s*(.*)$", text)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def load(ledger: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    prs = [dict(read_entry(p), _file=p.name) for p in sorted((ledger / "prs").glob("*.yaml"))]
    rounds = [dict(read_entry(p), _file=p.name) for p in sorted((ledger / "rounds").glob("*.yaml"))]
    return prs, rounds


def num(v: str | None, default: int = 0) -> int:
    return int(v) if v is not None and re.fullmatch(r"\d+", v) else default


def problems(prs: list[dict[str, str]], rounds: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for kind, entries, keys in (("prs", prs, PR_KEYS), ("rounds", rounds, ROUND_KEYS)):
        seen: set[tuple[str, str]] = set()
        for e in entries:
            where = f"{kind}/{e['_file']}"
            for k in keys:
                if k not in e or e[k] == "":
                    out.append(f"{where}: `{k}` is missing")
                elif k in INT_KEYS and not re.fullmatch(r"\d+", e[k]):
                    out.append(f"{where}: `{k}` must be a whole number, got '{e[k]}'")
            ident = (e.get("pr", ""), e.get("round", ""))
            if ident in seen:
                out.append(f"{where}: a second entry for the same PR{' and round' if kind == 'rounds' else ''}")
            seen.add(ident)
            if e.get("critical", "no") not in ("yes", "no") and (kind == "prs" or e.get("round") == "1"):
                out.append(f"{where}: `critical` must be yes or no")
            if kind == "rounds" and e.get("verdict") not in (None, "", "approved", "changes_requested"):
                out.append(f"{where}: `verdict` must be approved or changes_requested")
    by_pr = {e.get("pr") for e in prs}
    for e in rounds:
        if e.get("pr") not in by_pr:
            out.append(f"rounds/{e['_file']}: no prs/pr-{e.get('pr')}.yaml for this PR")
        if e.get("round") == "1" and "critical" not in e:
            out.append(f"rounds/{e['_file']}: round 1 must record the reviewer's `critical: yes|no` (CRIT-03)")
        if e.get("merged") and num(e.get("must_fix"), -1) != 0:
            out.append(f"rounds/{e['_file']}: merged with open must-fix findings (MRG-01)")
    return out


def status_of(pr: str, rounds: list[dict[str, str]]) -> tuple[str, int, str]:
    mine = sorted((r for r in rounds if r.get("pr") == pr), key=lambda r: num(r.get("round")))
    if not mine:
        return "open, not reviewed", 0, "-"
    last = mine[-1]
    confirmed = next((r.get("critical", "-") for r in mine if r.get("round") == "1"), "-")
    if last.get("merged"):
        return f"merged {last['merged'][:9]}", len(mine), confirmed
    return f"round {last.get('round')}: {last.get('verdict', '?')}, {num(last.get('must_fix'))} must-fix", len(mine), confirmed


def table(prs: list[dict[str, str]], rounds: list[dict[str, str]]) -> str:
    lines = ["## PRs", "", "| PR | Opened | Thread | Lane | Labels | Package | Critical (author / reviewer) | Compactions | Rounds | Status |",
             "|----|--------|--------|------|--------|---------|------------------------------|-------------|--------|--------|"]
    for e in sorted(prs, key=lambda e: num(e.get("pr"))):
        status, n, confirmed = status_of(e.get("pr", ""), rounds)
        lines.append(f"| #{e.get('pr', '?')} | {e.get('opened', '')} | {e.get('thread', '')} | {e.get('lane', '')} | {e.get('labels', '')} | "
                     f"{e.get('package', '-') or '-'} | {e.get('critical', '-')} / {confirmed} | {e.get('compactions', '0')} | {n} | {status} |")
    lines += ["", "## Review rounds", "", "| PR | Round | Date | Thread | Head | Verdict | Must-fix | Should-fix | Report |",
              "|----|-------|------|--------|------|---------|----------|------------|--------|"]
    for e in sorted(rounds, key=lambda e: (num(e.get("pr")), num(e.get("round")))):
        lines.append(f"| #{e.get('pr', '?')} | {e.get('round', '')} | {e.get('date', '')} | {e.get('thread', '')} | {e.get('head', '')} | "
                     f"{e.get('verdict', '')} | {e.get('must_fix', '')} | {e.get('should_fix', '')} | {e.get('report', '')} |")
    return "\n".join(lines) + "\n"


def stats(prs: list[dict[str, str]], rounds: list[dict[str, str]]) -> str:
    if not prs:
        return "No PR entries yet.\n"
    per_pr = {e.get("pr", ""): len([r for r in rounds if r.get("pr") == e.get("pr")]) for e in prs}
    reviewed = [n for n in per_pr.values() if n]
    comp = [num(e.get("compactions")) for e in prs]
    lines = [
        f"PRs: {len(prs)}; reviewed: {len(reviewed)}; merged: {sum(1 for r in rounds if r.get('merged'))}.",
        f"Review rounds per reviewed PR: {sum(reviewed) / len(reviewed):.1f} on average, {max(reviewed)} at most." if reviewed else "No review rounds yet.",
        f"PRs with three or more rounds: {', '.join('#' + p for p, n in per_pr.items() if n >= 3) or 'none'}.",
        f"Compactions per PR: {sum(comp) / len(comp):.1f} on average; PRs with one or more: {', '.join('#' + e.get('pr', '?') for e in prs if num(e.get('compactions'))) or 'none'}.",
        "PRs per thread (compare with replace_after_prs, THR-02):",
    ]
    threads: dict[str, int] = {}
    for e in prs:
        threads[e.get("thread") or "(no thread name)"] = threads.get(e.get("thread") or "(no thread name)", 0) + 1
    for e in rounds:
        key = (e.get("thread") or "(no thread name)") + " [review]"
        threads.setdefault(key, 0)
    for name in list(threads):
        if name.endswith(" [review]"):
            threads[name] = len({r.get("pr") for r in rounds if (r.get("thread") or "(no thread name)") + " [review]" == name})
    lines += [f"  {name}: {n}" for name, n in sorted(threads.items())]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Read the per-PR and per-round ledger entries")
    ap.add_argument("cmd", choices=["table", "stats", "check"])
    ap.add_argument("--ledger", type=Path, help="ledger directory (default: ../ledger next to this script, or ./ledger)")
    args = ap.parse_args()
    here = Path(__file__).resolve().parent.parent / "ledger"
    ledger = args.ledger or (here if here.is_dir() else Path("ledger"))
    if not ledger.is_dir():
        print(f"error: no ledger directory at {ledger}", file=sys.stderr)
        return 2
    prs, rounds = load(ledger)
    if args.cmd == "table":
        print(table(prs, rounds), end="")
        return 0
    if args.cmd == "stats":
        print(stats(prs, rounds), end="")
        return 0
    found = problems(prs, rounds)
    print("\n".join(found) if found else f"{len(prs)} PR entries and {len(rounds)} round entries, no problems.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
