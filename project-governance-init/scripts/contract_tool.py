#!/usr/bin/env python3
"""
Check and use acceptance contracts (plans/contract-<NNN>-<slug>.yaml).

The method is in references/acceptance-contracts.md (rules PLAN-03, PLAN-04,
REV-03). This script does the parts a machine can do reliably: required fields,
id format, verify steps, sourced research, untestable wording, the Pareto cut,
and the approval record. Whether a criterion is the *right* one stays a human
and reviewer judgement.

Usage:
    python3 contract_tool.py lint contract.yaml [--json] [--strict]
    python3 contract_tool.py summary contract.yaml
    python3 contract_tool.py goal contract.yaml [--ids AC-3,AC-4] [--turns 30] [--allow-draft]

lint exit code: 0 clean or only WARN/INFO, 1 when any ERROR (or WARN with
--strict), 2 when the file cannot be read or parsed.
goal exit code: 1 when the contract is not approved (unless --allow-draft) or
has lint errors.

Reads .json with the standard library and .yaml/.yml with PyYAML.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

STATUSES = {"draft", "approved", "superseded"}
PRIORITIES = {"must", "should", "could"}
VERIFY_TYPES = {"test", "command", "inspection", "manual"}
SOURCE_KINDS = {"owner", "research", "repo", "assumption"}
CATEGORIES = {
    "happy_path", "input_validation", "error_states", "data_persistence",
    "security_privacy", "accessibility", "performance", "platform",
    "operability", "licences_dependencies",
}
VAGUE_WORDS = [
    "fast", "quick", "quickly", "easy", "easily", "simple", "intuitive", "user-friendly",
    "user friendly", "robust", "secure", "securely", "safe", "safely", "clean", "nice",
    "good", "properly", "proper", "appropriate", "appropriately", "reasonable",
    "reasonably", "seamless", "seamlessly", "modern", "efficient", "efficiently",
    "scalable", "reliable", "reliably", "as expected", "works", "correctly",
]
VAGUE_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in VAGUE_WORDS) + r")\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"<[^<>]{2,}>")
ID_RE = re.compile(r"^AC-\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DECISION_RE = re.compile(r"^D-\d+$")
LONG_CRITERION = 220
MANY_MUST = 40
MANUAL_SHARE = 1 / 3


@dataclass
class Finding:
    code: str
    severity: str  # ERROR | WARN | INFO
    message: str
    where: str = ""


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------

def load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit("error: reading YAML needs PyYAML (pip install pyyaml), or save the contract as .json")
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("the contract must be a mapping at the top level")
    return data


def s(v: Any) -> str:
    """Normalise a scalar to a stripped string (YAML may give dates or numbers)."""
    if v is None:
        return ""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    return str(v).strip()


def is_placeholder(v: Any) -> bool:
    t = s(v)
    return not t or bool(PLACEHOLDER_RE.search(t))


# ----------------------------------------------------------------------------
# Lint
# ----------------------------------------------------------------------------

def lint(data: dict[str, Any]) -> list[Finding]:
    f: list[Finding] = []

    def add(code: str, sev: str, msg: str, where: str = "") -> None:
        f.append(Finding(code, sev, msg, where))

    meta = data.get("contract") or {}
    if not isinstance(meta, dict):
        meta = {}
    for key in ("id", "title"):
        if is_placeholder(meta.get(key)):
            add("C001", "ERROR", f"contract.{key} is missing or still a placeholder", "contract")
    version = meta.get("version")
    if not isinstance(version, int) or version < 1:
        add("C001", "ERROR", "contract.version must be an integer >= 1", "contract")
        version = 1
    status = s(meta.get("status")).lower()
    if status not in STATUSES:
        add("C001", "ERROR", f"contract.status must be one of {sorted(STATUSES)}, got '{status}'", "contract")

    if is_placeholder(data.get("goal")):
        add("C002", "ERROR", "goal is missing or still a placeholder; write one sentence a stranger could check", "goal")
    if is_placeholder(data.get("core_probe")):
        add("C003", "ERROR", "core_probe is missing; name the one end-to-end check that proves the goal", "core_probe")
    for key in ("users", "access"):
        if is_placeholder(data.get(key)):
            add("C004", "WARN", f"{key} is not filled in; it decides login, privacy and platform criteria", key)

    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        add("C005", "ERROR", "criteria must be a non-empty list", "criteria")
        return f

    seen: set[str] = set()
    counts = {"must": 0, "should": 0, "could": 0}
    manual = 0
    research_sources = 0
    assumptions: list[str] = []
    could_ids: list[str] = []
    today = datetime.date.today()

    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            add("C010", "ERROR", "criterion is not a mapping", f"criteria[{i}]")
            continue
        cid = s(c.get("id"))
        where = cid or f"criteria[{i}]"
        if not ID_RE.match(cid):
            add("C010", "ERROR", f"id '{cid}' must look like AC-<number>", where)
        elif cid in seen:
            add("C011", "ERROR", f"duplicate id {cid}", where)
        seen.add(cid)

        text = s(c.get("text"))
        if is_placeholder(text):
            add("C012", "ERROR", "text is missing or still a placeholder", where)
        else:
            m = VAGUE_RE.search(text)
            if m and not re.search(r"\d", text):
                add("C017", "WARN", f"'{m.group(0)}' is not testable without a number or concrete condition: \"{text}\"", where)
            if len(text) > LONG_CRITERION:
                add("C018", "WARN", f"{len(text)} characters; probably more than one check, split it", where)

        prio = s(c.get("priority")).lower()
        if prio not in PRIORITIES:
            add("C013", "ERROR", f"priority must be must | should | could, got '{prio}'", where)
        else:
            counts[prio] += 1
            if prio == "could":
                could_ids.append(cid)

        cat = s(c.get("category"))
        if cat and cat not in CATEGORIES:
            add("C019", "INFO", f"category '{cat}' is not one of the standard categories", where)

        verify = c.get("verify")
        if not isinstance(verify, dict):
            add("C014", "ERROR", "verify step missing (type + how)", where)
        else:
            vtype = s(verify.get("type")).lower()
            if vtype not in VERIFY_TYPES:
                add("C014", "ERROR", f"verify.type must be one of {sorted(VERIFY_TYPES)}, got '{vtype}'", where)
            if is_placeholder(verify.get("how")):
                add("C014", "ERROR", "verify.how is missing or still a placeholder", where)
            if vtype == "manual":
                manual += 1

        src = c.get("source")
        if not isinstance(src, dict):
            add("C015", "ERROR", "source missing (kind + ref)", where)
            continue
        kind = s(src.get("kind")).lower()
        if kind not in SOURCE_KINDS:
            add("C015", "ERROR", f"source.kind must be one of {sorted(SOURCE_KINDS)}, got '{kind}'", where)
        if kind == "assumption":
            assumptions.append(cid)
        elif is_placeholder(src.get("ref")):
            add("C015", "ERROR", f"source.ref is empty for a '{kind}' source", where)
        if kind == "research":
            research_sources += 1
            ref = s(src.get("ref"))
            if urlparse(ref).scheme not in ("http", "https"):
                add("C016", "ERROR", "a research source needs a URL in source.ref (the page the criterion came from)", where)
            retrieved = s(src.get("retrieved"))
            if not DATE_RE.match(retrieved):
                add("C016", "ERROR", "a research source needs source.retrieved as YYYY-MM-DD", where)
            else:
                try:
                    if datetime.date.fromisoformat(retrieved) > today:
                        add("C016", "WARN", f"source.retrieved {retrieved} is in the future", where)
                except ValueError:
                    add("C016", "ERROR", f"source.retrieved {retrieved} is not a valid date", where)

    total = sum(counts.values())
    if counts["must"] == 0:
        add("C006", "ERROR", "no 'must' criterion: nothing defines done", "criteria")
    if counts["must"] > MANY_MUST:
        add("C021", "WARN", f"{counts['must']} must criteria; do the Pareto cut (move some to should/could)", "criteria")
    if total and manual / total > MANUAL_SHARE:
        add("C020", "WARN", f"{manual} of {total} criteria are manual; they become owner hand steps, automate some", "criteria")
    if research_sources == 0 and is_placeholder((data.get("research") or {}).get("notes") if isinstance(data.get("research"), dict) else None):
        add("C026", "WARN", "no researched criteria and no research.notes saying why; run step 2 or record the reason", "research")

    if status == "approved":
        approval = data.get("approval") or {}
        if not isinstance(approval, dict):
            approval = {}
        if s(approval.get("by")).lower() != "owner":
            add("C023", "ERROR", "status is approved but approval.by is not 'owner' (ROLE-03: only the owner approves)", "approval")
        if not DATE_RE.match(s(approval.get("date"))):
            add("C023", "ERROR", "status is approved but approval.date is not YYYY-MM-DD", "approval")
        if not DECISION_RE.match(s(approval.get("decision"))):
            add("C023", "ERROR", "status is approved but approval.decision has no D-number", "approval")
        if could_ids:
            add("C022", "ERROR", f"approved contract still holds could items {', '.join(could_ids)}; they belong in GitHub issues", "criteria")
        if assumptions:
            add("C024", "WARN", f"approved with unresolved assumptions: {', '.join(assumptions)}", "criteria")
    else:
        if could_ids:
            add("C022", "WARN", f"could items {', '.join(could_ids)} must leave the contract (as issues) before approval", "criteria")
        if assumptions:
            add("C025", "INFO", f"assumptions for the owner to confirm: {', '.join(assumptions)}", "criteria")

    if version > 1 and not data.get("changes"):
        add("C028", "WARN", f"version {version} but 'changes' is empty; record what changed and the D-number", "changes")
    return f


def render_markdown(path: Path, findings: list[Finding]) -> str:
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    n = {k: sum(1 for x in findings if x.severity == k) for k in order}
    lines = [f"# Contract lint: {path.name}", "",
             f"Findings: {n['ERROR']} error, {n['WARN']} warn, {n['INFO']} info.", ""]
    if not findings:
        lines.append("No mechanical findings. Judge the criteria themselves next: are they the right ones?")
    for x in sorted(findings, key=lambda x: (order[x.severity], x.code, x.where)):
        lines.append(f"- **{x.severity} {x.code}** [{x.where}] {x.message}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Summary and /goal
# ----------------------------------------------------------------------------

def summary(path: Path, data: dict[str, Any]) -> str:
    crit = [c for c in data.get("criteria") or [] if isinstance(c, dict)]
    counts = {p: sum(1 for c in crit if s(c.get("priority")).lower() == p) for p in ("must", "should", "could")}
    assumptions = [s(c.get("id")) for c in crit if isinstance(c.get("source"), dict) and s(c["source"].get("kind")) == "assumption"]
    domains = sorted({urlparse(s(c["source"].get("ref"))).netloc for c in crit
                      if isinstance(c.get("source"), dict) and s(c["source"].get("kind")) == "research"} - {""})
    meta = data.get("contract") or {}
    skipped = (data.get("research") or {}).get("categories_skipped") or [] if isinstance(data.get("research"), dict) else []
    return "\n".join([
        f"{s(meta.get('id'))} v{s(meta.get('version'))} ({s(meta.get('status'))}): {s(data.get('goal'))}",
        f"Criteria: {counts['must']} must, {counts['should']} should, {counts['could']} could.",
        f"Assumptions to confirm: {', '.join(assumptions) or 'none'}.",
        f"Sources: {', '.join(domains) or 'none'}. Skipped categories: {', '.join(map(str, skipped)) or 'none'}.",
    ]) + "\n"


def goal_line(path: Path, data: dict[str, Any], ids: list[str] | None, turns: int) -> str:
    crit = [c for c in data.get("criteria") or [] if isinstance(c, dict)]
    known = {s(c.get("id")) for c in crit}
    if ids:
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise SystemExit(f"error: unknown criterion ids: {', '.join(unknown)}")
        chosen = ids
        probe = ""
    else:
        chosen = [s(c.get("id")) for c in crit if s(c.get("priority")).lower() == "must"]
        probe = f", and the core probe passes ({s(data.get('core_probe'))})"
    meta = data.get("contract") or {}
    return (f"/goal Every criterion {', '.join(chosen)} in {path.as_posix()} "
            f"(v{s(meta.get('version'))}) is shown true by running its verify step in this session{probe}. "
            f"Do not edit the contract. Stop after {turns} turns and list the criteria still open.")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Lint acceptance contracts and print /goal lines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_lint = sub.add_parser("lint", help="check a contract")
    p_lint.add_argument("contract", type=Path)
    p_lint.add_argument("--json", action="store_true")
    p_lint.add_argument("--strict", action="store_true", help="exit 1 on WARN too")
    p_sum = sub.add_parser("summary", help="three-line hand-back for the coordinator")
    p_sum.add_argument("contract", type=Path)
    p_goal = sub.add_parser("goal", help="print a /goal line for Claude Code")
    p_goal.add_argument("contract", type=Path)
    p_goal.add_argument("--ids", help="comma-separated criterion ids (default: all must criteria + core probe)")
    p_goal.add_argument("--turns", type=int, default=30)
    p_goal.add_argument("--allow-draft", action="store_true")
    args = ap.parse_args()

    try:
        data = load(args.contract)
    except (OSError, ValueError) as e:
        print(f"error: cannot read {args.contract}: {e}", file=sys.stderr)
        return 2

    if args.cmd == "summary":
        print(summary(args.contract, data), end="")
        return 0

    findings = lint(data)
    errors = [x for x in findings if x.severity == "ERROR"]

    if args.cmd == "lint":
        if args.json:
            print(json.dumps([asdict(x) for x in findings], indent=2))
        else:
            print(render_markdown(args.contract, findings), end="")
        if errors or (args.strict and any(x.severity == "WARN" for x in findings)):
            return 1
        return 0

    # goal
    status = s((data.get("contract") or {}).get("status")).lower()
    if status != "approved" and not args.allow_draft:
        print(f"error: contract status is '{status}'; /goal runs only on an owner-approved contract (PLAN-03)", file=sys.stderr)
        return 1
    if errors:
        print(f"error: {len(errors)} lint error(s); run `contract_tool.py lint` first", file=sys.stderr)
        return 1
    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    print(goal_line(args.contract, data, ids, args.turns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
