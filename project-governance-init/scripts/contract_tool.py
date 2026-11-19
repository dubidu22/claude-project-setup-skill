#!/usr/bin/env python3
"""
Check and use acceptance contracts (plans/contract-<NNN>-<slug>.yaml).

The method is in references/acceptance-contracts.md (rules PLAN-03, PLAN-04,
REV-03). This script does the parts a machine can do reliably: required fields,
id format, verify steps, sourced research, untestable wording, the Pareto cut,
the approval record and the freeze. Whether a criterion is the *right* one stays
a human and reviewer judgement.

Usage:
    python3 contract_tool.py lint contract.yaml [--json] [--strict]
    python3 contract_tool.py summary contract.yaml        # hand-back for the coordinator (with the pickup line)
    python3 contract_tool.py brief contract.yaml [--ids AC-3,AC-4]   # compact view for worker threads
    python3 contract_tool.py brief contract.yaml --owner  # everything the owner approves: scope, every criterion and verify step, hash
    python3 contract_tool.py hash contract.yaml           # value for approval.hash
    python3 contract_tool.py issues contract.yaml [--json] [--preflight]   # issue drafts, one per work package (+ backlog items)
    python3 contract_tool.py record-issue contract.yaml <package key> <issue number>   # the only command that writes a file
    python3 contract_tool.py roadmap roadmap.yaml [--plans DIR]   # check the roadmap against the contracts
    python3 contract_tool.py goal contract.yaml [--ids AC-3,AC-4] [--turns 30] [--allow-draft]

The freeze. `approval.hash` covers the goal, users, access, constraints, out of
scope, the core probe and every criterion with its verify step. A thread could
recompute it after an edit, so it is not trusted on its own: on pickup the
coordinator records "<id> v<version> D-<n> hash <hash>" in project-state.yaml
(and the KB thread copies it into the decision log). lint and goal compare the
contract with that record. They look for `../project-state.yaml`,
`../kb/decision-log.md` and `../claude-project-rules.yaml` relative to the
contract's folder; --state, --decision-log and --rules name other places.

lint exit code: 0 clean or only WARN/INFO, 1 when any ERROR (or WARN with
--strict), 2 when the file cannot be read or parsed.
goal exit code: 1 when the contract is not approved and picked up (unless
--allow-draft) or has lint errors.

Reads .json with the standard library. Reads .yaml/.yml with PyYAML when it is
installed and with a built-in reader for plain YAML (mappings, lists, quoted and
plain scalars, inline lists, | and > blocks) when it is not.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
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
CONTRACT_ID_RE = re.compile(r"^C-\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DECISION_RE = re.compile(r"^D-\d+$")
LABEL_RE = re.compile(r"^lane:[a-z0-9_-]+$")
# A number only makes a vague word testable when it is a measurement or a comparison, not "Python 3".
UNITS = (r"ms|msec|milliseconds?|s|sec|secs|seconds?|min|mins|minutes?|h|hours?|days?|%|percent|kb|mb|gb|kib|mib|gib|bytes?|"
         r"rows?|items?|entries|records?|files?|lines?|chars?|characters?|words?|px|fps|x|times?|attempts?|retries|"
         r"users?|requests?|connections?|steps?|clicks?")
MEASURE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:" + UNITS + r")(?![A-Za-z])"
    r"|(?:[<>]=?|≤|≥|\b(?:under|below|above|over|within|at most|at least|less than|more than|fewer than|no more than|up to|exactly|"
    r"exits?(?: with)?(?: code)?|exit code|status(?: code)?|returns?|code)\b)\s*\d",
    re.IGNORECASE,
)
RECORD_HASH_RE = re.compile(r"\bhash[:\s]+([0-9a-f]{12})\b")
TEMPLATE_NAME = "contract-template.yaml"
ROADMAP_STATUSES = {"planned", "active", "done", "dropped"}
LONG_CRITERION = 220
MANY_MUST = 40
MANUAL_SHARE = 1 / 3
MAX_PACKAGE_CRITERIA = 6  # rule of thumb: what one thread builds and one review round checks


@dataclass
class Finding:
    code: str
    severity: str  # ERROR | WARN | INFO
    message: str
    where: str = ""


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    quote, i = "", 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _split_outside(text: str, sep: str) -> list[str]:
    """Split on sep where it is outside quotes and brackets."""
    parts, cur, quote, depth, i = [], [], "", 0, 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _split_key(content: str) -> tuple[str, str] | None:
    """'key: rest' -> (key, rest); None when the line is not a mapping entry."""
    if not content or content[0] in "[{":
        return None
    quote, i = "", 0
    while i < len(content):
        ch = content[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'" and i == 0:
            quote = ch
        elif ch == ":" and (i + 1 == len(content) or content[i + 1] == " "):
            key = content[:i].strip()
            if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                key = key[1:-1]
            return key, content[i + 1:].strip()
        i += 1
    return None


def _scalar(text: str) -> Any:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(x) for x in _split_outside(text[1:-1], ",") if x.strip()]
    if text.startswith("{") and text.endswith("}"):
        out: dict[str, Any] = {}
        for part in _split_outside(text[1:-1], ","):
            kv = _split_key(part.strip())
            if kv:
                out[kv[0]] = _scalar(kv[1])
        return out
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body, out_s, i = text[1:-1], [], 0
        esc = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0"}
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                if nxt == "x" and i + 3 < len(body) and re.fullmatch(r"[0-9a-fA-F]{2}", body[i + 2:i + 4]):
                    out_s.append(chr(int(body[i + 2:i + 4], 16)))
                    i += 4
                    continue
                out_s.append(esc.get(nxt, nxt))
                i += 2
            else:
                out_s.append(body[i])
                i += 1
        return "".join(out_s)
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    # the same words PyYAML reads as booleans, so both readers agree
    if text in ("true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"):
        return True
    if text in ("false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"):
        return False
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    if re.fullmatch(r"[-+]?\d+\.\d+", text):
        return float(text)
    return text


def mini_yaml(text: str) -> Any:
    """Reader for plain YAML, used when PyYAML is not installed. Raises ValueError on what it does not cover."""
    raw = text.splitlines()
    rows: list[list[Any]] = []  # [indent, content or None, line number]
    for no, line in enumerate(raw, 1):
        lead = line[: len(line) - len(line.lstrip())]
        if "\t" in lead:
            raise ValueError(f"line {no}: tabs in indentation")
        body = _strip_comment(line)
        if not body.strip() or body.strip() in ("---", "..."):
            rows.append([len(lead), None, no])
        else:
            rows.append([len(body) - len(body.lstrip()), body.strip(), no])

    def skip(i: int) -> int:
        while i < len(rows) and rows[i][1] is None:
            i += 1
        return i

    def block_scalar(i: int, parent_indent: int, style: str) -> tuple[str, int]:
        lines: list[str] = []
        indent = None
        while i < len(raw):
            line = raw[i]
            if line.strip():
                cur = len(line) - len(line.lstrip())
                if cur <= parent_indent:
                    break
                if indent is None:
                    indent = cur
                lines.append(line[indent:])
            else:
                lines.append("")
            i += 1
        while lines and not lines[-1]:
            lines.pop()
        if style.startswith(">"):
            out, para = [], []
            for l in lines:
                if l:
                    para.append(l.strip())
                else:
                    out.append(" ".join(para))
                    para = []
            out.append(" ".join(para))
            value = "\n".join(out)
        else:
            value = "\n".join(lines)
        return value + ("" if style.endswith("-") else "\n"), i

    def node(i: int, indent: int) -> tuple[Any, int]:
        i = skip(i)
        if i >= len(rows) or rows[i][0] < indent:
            return None, i
        content = rows[i][1]
        if content == "-" or content.startswith("- "):
            return seq(i, rows[i][0])
        return mapping(i, rows[i][0])

    def value_after(i: int, indent: int, rest: str) -> tuple[Any, int]:
        """Value of a key or list item whose inline text is `rest`; i is the row after it."""
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            return block_scalar(i, indent, rest)
        if rest:
            j = skip(i)
            if j < len(rows) and rows[j][0] > indent and not (rest[0] in "\"'[{"):
                raise ValueError(f"line {rows[j][2]}: a plain value continued on the next line needs PyYAML (or quote it on one line)")
            return _scalar(rest), i
        j = skip(i)
        if j < len(rows) and (rows[j][0] > indent or (rows[j][0] == indent and (rows[j][1] == "-" or rows[j][1].startswith("- ")))):
            return node(j, rows[j][0])
        return None, i

    def mapping(i: int, indent: int) -> tuple[dict[str, Any], int]:
        out: dict[str, Any] = {}
        while True:
            i = skip(i)
            if i >= len(rows) or rows[i][0] < indent:
                return out, i
            if rows[i][0] > indent:
                raise ValueError(f"line {rows[i][2]}: unexpected indentation")
            kv = _split_key(rows[i][1])
            if kv is None:
                raise ValueError(f"line {rows[i][2]}: expected 'key: value', got: {rows[i][1][:40]}")
            out[kv[0]], i = value_after(i + 1, indent, kv[1])

    def seq(i: int, indent: int) -> tuple[list[Any], int]:
        out: list[Any] = []
        while True:
            i = skip(i)
            if i >= len(rows) or rows[i][0] != indent or not (rows[i][1] == "-" or rows[i][1].startswith("- ")):
                if i < len(rows) and rows[i][0] > indent:
                    raise ValueError(f"line {rows[i][2]}: unexpected indentation")
                return out, i
            rest = rows[i][1][1:].strip()
            if rest and _split_key(rest) is not None:
                # "- key: value": the item is a mapping whose keys sit two columns further in
                offset = len(rows[i][1]) - len(rows[i][1][1:].lstrip())
                rows[i][0], rows[i][1] = indent + offset, rest
                item, i = mapping(i, indent + offset)
            else:
                item, i = value_after(i + 1, indent, rest)
            out.append(item)

    start = skip(0)
    if start >= len(rows):
        return None
    value, end = node(start, rows[start][0])
    end = skip(end)
    if end < len(rows):
        raise ValueError(f"line {rows[end][2]}: could not read this line")
    return value


def load_any(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError:
        return mini_yaml(text)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(" ".join(str(exc).split())) from exc


def load(path: Path) -> dict[str, Any]:
    data = load_any(path)
    if not isinstance(data, dict):
        raise ValueError("the file must be a mapping at the top level")
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


def _criteria_payload(data: dict[str, Any]) -> list[list[str]]:
    crit = []
    for c in data.get("criteria") or []:
        if isinstance(c, dict):
            v = c.get("verify") if isinstance(c.get("verify"), dict) else {}
            crit.append([s(c.get("id")), s(c.get("text")), s(c.get("priority")).lower(), s(v.get("type")).lower(), s(v.get("how"))])
    return crit


def _digest(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _str_list(v: Any) -> list[str]:
    return [s(x) for x in v] if isinstance(v, list) else ([s(v)] if s(v) else [])


def contract_hash(data: dict[str, Any]) -> str:
    """Hash of what approval freezes: goal, users, access, constraints, out of scope, core probe, and each
    criterion's id, text, priority and verify step. Work packages, sources and the cut list are not part of it."""
    return _digest([
        "v2", s(data.get("goal")), s(data.get("users")), s(data.get("access")),
        _str_list(data.get("constraints")), _str_list(data.get("out_of_scope")),
        s(data.get("core_probe")), _criteria_payload(data),
    ])


def legacy_hash(data: dict[str, Any]) -> str:
    """The hash older versions of this tool wrote: goal, core probe and criteria only."""
    return _digest([s(data.get("goal")), s(data.get("core_probe")), _criteria_payload(data)])


def find_records(cid: str, version: str, texts: dict[str, str]) -> list[tuple[str, str, str]]:
    """Pickup records of a contract version in the state file or decision log: (source, D-number, hash)."""
    out: list[tuple[str, str, str]] = []
    if not cid or not version:
        return out
    for source, text in texts.items():
        chunks = re.split(r"(?m)^(?=## )", text) if re.search(r"(?m)^## ", text) else text.splitlines()
        by_line = chunks and not chunks[0].startswith("## ") and not re.search(r"(?m)^## ", text)
        for chunk in chunks:
            if by_line:
                chunk = _strip_comment(chunk)  # a comment is not a record, e.g. the format example in the state file
            elif chunk.lstrip().startswith("#") and not chunk.lstrip().startswith("## "):
                continue
            m = RECORD_HASH_RE.search(chunk)
            if m and re.search(rf"\b{re.escape(cid)}\b", chunk) and re.search(rf"\bv{re.escape(version)}\b", chunk):
                d = re.search(r"\bD-\d+\b", chunk)
                out.append((source, d.group(0) if d else "", m.group(1)))
    return out


def workspace_files(contract: Path, state: Path | None, decision_log: Path | None, rules: Path | None) -> tuple[dict[str, str], Path | None]:
    """Texts of the pickup-record files that exist, and the ruleset path if there is one."""
    ws = contract.resolve().parent.parent
    texts: dict[str, str] = {}
    for label, given, default in (("project-state.yaml", state, ws / "project-state.yaml"),
                                  ("decision log", decision_log, ws / "kb" / "decision-log.md")):
        path = given or default
        if path.is_file():
            texts[label] = path.read_text(encoding="utf-8")
    rules_path = rules or ws / "claude-project-rules.yaml"
    return texts, (rules_path if rules_path.is_file() else None)


def ruleset_labels(rules_path: Path | None) -> tuple[list[str] | None, str]:
    """file_ownership_labels and repository of the ruleset, or (None, '') when it cannot be read."""
    if rules_path is None:
        return None, ""
    try:
        data = load(rules_path)
    except (OSError, ValueError):
        return None, ""
    prof = data.get("project_profile") if isinstance(data.get("project_profile"), dict) else {}
    labels = prof.get("file_ownership_labels")
    return ([s(x) for x in labels] if isinstance(labels, list) else None), s(data.get("repository"))


# ----------------------------------------------------------------------------
# Lint
# ----------------------------------------------------------------------------

def lint(data: dict[str, Any], max_package_criteria: int = MAX_PACKAGE_CRITERIA, *,
         record_texts: dict[str, str] | None = None, labels: list[str] | None = None) -> list[Finding]:
    """record_texts: contents of the state file / decision log that were found (None: do not check the pickup
    record). labels: file-ownership labels of the ruleset (None: only check the label's shape)."""
    f: list[Finding] = []

    def add(code: str, sev: str, msg: str, where: str = "") -> None:
        f.append(Finding(code, sev, msg, where))

    meta = data.get("contract") or {}
    if not isinstance(meta, dict):
        meta = {}
    for key in ("id", "title"):
        if is_placeholder(meta.get(key)):
            add("C001", "ERROR", f"contract.{key} is missing or still a placeholder", "contract")
    if not is_placeholder(meta.get("id")) and not CONTRACT_ID_RE.match(s(meta.get("id"))):
        add("C001", "ERROR", f"contract.id '{s(meta.get('id'))}' must look like C-<number>", "contract")
    if is_placeholder(meta.get("milestone")):
        add("C031", "WARN", "contract.milestone is not filled in; a contract belongs to one milestone", "contract")
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

    scope_out = data.get("out_of_scope")
    if not isinstance(scope_out, list) or not scope_out or all(is_placeholder(x) for x in scope_out):
        add("C030", "WARN", "out_of_scope is empty; name what this milestone deliberately leaves out", "out_of_scope")

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
    cats_used: set[str] = set()
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
            if m and not MEASURE_RE.search(text):
                add("C017", "WARN", f"'{m.group(0)}' is not testable without a number or concrete condition: \"{text}\"", where)
            if len(text) > LONG_CRITERION:
                add("C018", "WARN", f"{len(text)} characters; probably more than one check, split it", where)
            elif re.search(r"[.;]\s+\S", text):
                add("C018", "WARN", "more than one sentence; one criterion is one check, split it", where)

        prio = s(c.get("priority")).lower()
        if prio not in PRIORITIES:
            add("C013", "ERROR", f"priority must be must | should | could, got '{prio}'", where)
        else:
            counts[prio] += 1
            if prio == "could":
                could_ids.append(cid)

        cat = s(c.get("category"))
        if not cat:
            add("C019", "WARN", "category is missing; it shows which kinds of behaviour the contract covers", where)
        elif cat not in CATEGORIES:
            add("C019", "INFO", f"category '{cat}' is not one of the standard categories", where)
        else:
            cats_used.add(cat)

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

    research = data.get("research") if isinstance(data.get("research"), dict) else {}
    skipped = {s(x).split(":", 1)[0].strip() for x in (research.get("categories_skipped") or [])}
    uncovered = sorted(CATEGORIES - cats_used - skipped)
    if uncovered:
        add("C029", "WARN", f"no criterion and no skip reason for: {', '.join(uncovered)}; add criteria or list each under research.categories_skipped as 'name: reason'", "research")

    packages = data.get("work_packages")
    in_scope = [s(c.get("id")) for c in criteria if isinstance(c, dict) and s(c.get("priority")).lower() in ("must", "should")]
    if not isinstance(packages, list) or not packages:
        add("C033", "WARN", "no work_packages; group the must and should criteria into a few packages (one issue each)", "work_packages")
    else:
        placed: dict[str, str] = {}
        keys: set[str] = set()
        for i, wp in enumerate(packages):
            if not isinstance(wp, dict):
                add("C033", "ERROR", "work package is not a mapping", f"work_packages[{i}]")
                continue
            key = s(wp.get("key")) or f"work_packages[{i}]"
            if key in keys:
                add("C033", "ERROR", f"duplicate work package key {key}", key)
            keys.add(key)
            if is_placeholder(wp.get("title")):
                add("C033", "ERROR", "work package title is missing or still a placeholder", key)
            label = s(wp.get("label"))
            if not LABEL_RE.match(label):
                add("C033", "WARN", f"label '{label}' should be one file-ownership label like lane:cli", key)
            elif labels is not None and label not in labels:
                add("C033", "ERROR", f"label '{label}' is not a file-ownership label of this project's ruleset ({', '.join(labels)})", key)
            ids = wp.get("criteria") if isinstance(wp.get("criteria"), list) else []
            if not ids:
                add("C033", "ERROR", "work package lists no criteria", key)
            for cid in map(s, ids):
                if cid not in seen:
                    add("C033", "ERROR", f"{cid} is not a criterion of this contract", key)
                elif cid in placed:
                    add("C033", "ERROR", f"{cid} is in two work packages ({placed[cid]} and {key}); one owner per criterion", key)
                else:
                    placed[cid] = key
        sizes: dict[str, int] = {}
        after_map: dict[str, list[str]] = {}
        for wp in packages:
            if not isinstance(wp, dict):
                continue
            key = s(wp.get("key"))
            sizes[key] = len(wp.get("criteria") or []) if isinstance(wp.get("criteria"), list) else 0
            after = wp.get("after") or []
            after = [s(a) for a in (after if isinstance(after, list) else [after])]
            after_map[key] = after
            for a in after:
                if a == key or a not in keys:
                    add("C036", "ERROR", f"after: '{a}' is not another work package of this contract", key)
        for key, n in sizes.items():
            if max_package_criteria > 0 and n > max_package_criteria:
                add("C035", "WARN", f"{n} criteria in one package; more than about {max_package_criteria} is usually too much for one thread and one review round (rule of thumb). Split it into slices that can each be built and reviewed on their own", key)
        singles = [k for k, n in sizes.items() if n == 1]
        if len(sizes) >= 4 and len(singles) > len(sizes) / 2:
            add("C035", "INFO", f"{len(singles)} of {len(sizes)} packages hold a single criterion; every thread start has a fixed cost, so merge related ones", "work_packages")

        def reaches(start: str, target: str, seen_keys: set[str]) -> bool:
            for nxt in after_map.get(start, []):
                if nxt == target or (nxt not in seen_keys and reaches(nxt, target, seen_keys | {nxt})):
                    return True
            return False

        cyc = sorted(k for k in after_map if k and reaches(k, k, {k}))
        if cyc:
            add("C036", "ERROR", f"work packages wait for each other in a circle: {', '.join(cyc)}", "work_packages")
        loose = [c for c in in_scope if c and c not in placed]
        if loose:
            add("C033", "ERROR", f"not in any work package: {', '.join(loose)}", "work_packages")
        if len(packages) > 8:
            add("C033", "WARN", f"{len(packages)} work packages; issues should batch by lane, not by criterion", "work_packages")
    for i, item in enumerate(data.get("cut") or []):
        if not isinstance(item, dict) or is_placeholder(item.get("text")):
            add("C034", "WARN", "cut item needs text (and a reason) so it can become a backlog issue", f"cut[{i}]")

    if status == "approved":
        approval = data.get("approval") or {}
        if not isinstance(approval, dict):
            approval = {}
        if s(approval.get("by")).lower() != "owner":
            add("C023", "ERROR", "status is approved but approval.by is not 'owner' (ROLE-03: only the owner approves)", "approval")
        if not DATE_RE.match(s(approval.get("date"))):
            add("C023", "ERROR", "status is approved but approval.date is not YYYY-MM-DD", "approval")
        stored = s(approval.get("hash"))
        current, old_style = contract_hash(data), legacy_hash(data)
        if not stored:
            add("C027", "ERROR", "status is approved but approval.hash is empty; record the output of `contract_tool.py hash`", "approval")
        elif stored == old_style and stored != current:
            add("C027", "WARN", f"approval.hash {stored} was made by an older tool version and does not cover users, access, constraints and out_of_scope; the next contract version gets the full hash ({current} for this content)", "approval")
        elif stored != current:
            add("C027", "ERROR", f"the approved contract was edited in place (approval.hash {stored}, content {current}); an approved contract changes only by a new version", "approval")
        message = s(approval.get("owner_message"))
        if not message:
            add("C038", "WARN", "approval.owner_message is empty; quote the owner's approval message, which names the contract hash, so the approval can be traced to what the owner saw", "approval")
        elif stored and stored not in message:
            add("C038", "ERROR", f"approval.owner_message does not contain the hash {stored}; the owner approves a contract by quoting its hash, and this message approves something else", "approval")
        decision = s(approval.get("decision"))
        if record_texts is not None:
            cid, ver = s(meta.get("id")), s(meta.get("version"))
            records = find_records(cid, ver, record_texts)
            if not record_texts:
                add("C037", "WARN", "no project-state.yaml or decision log found next to the contract, so the freeze cannot be checked against the pickup record (no D-number on file); pass --state or --decision-log", "approval")
            elif not records:
                add("C037", "WARN", f"approved but not picked up: no line '{cid} v{ver} D-<n> hash {stored or '<hash>'}' in approved_contracts of project-state.yaml or in the decision log; the coordinator records it on pickup, and no work starts before (PLAN-03)", "approval")
            else:
                for source, d, h in records:
                    if h not in (current, old_style):
                        add("C037", "ERROR", f"the contract differs from what was picked up ({source}: {d or 'no D-number'} hash {h}; content {current}); it was edited after approval. Restore it, or make the change a new version", "approval")
                    elif not d:
                        add("C037", "WARN", f"the pickup record in {source} has no D-number", "approval")
                    elif decision and DECISION_RE.match(decision) and d != decision:
                        add("C037", "WARN", f"approval.decision says {decision} but the pickup record in {source} says {d}", "approval")
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
        f"Pickup record (coordinator, approved_contracts in project-state.yaml): {s(meta.get('id'))} v{s(meta.get('version'))} D-<n> hash {contract_hash(data)}",
    ]) + "\n"


def brief(data: dict[str, Any], ids: list[str] | None, owner: bool = False) -> str:
    """Compact view for implementation and review threads: no sources, categories or history.
    With owner=True: everything the approval covers, for the owner to read before saying yes."""
    meta = data.get("contract") or {}
    out = [f"{s(meta.get('id'))} v{s(meta.get('version'))} ({s(meta.get('status'))}) goal: {s(data.get('goal'))}"]
    if owner:
        ids = None
        out.append(f"users: {s(data.get('users')) or '-'} | access: {s(data.get('access')) or '-'}")
        out.append("constraints: " + ("; ".join(_str_list(data.get("constraints"))) or "-"))
        out.append("out of scope: " + ("; ".join(_str_list(data.get("out_of_scope"))) or "-"))
    for c in data.get("criteria") or []:
        if not isinstance(c, dict) or (ids and s(c.get("id")) not in ids):
            continue
        v = c.get("verify") if isinstance(c.get("verify"), dict) else {}
        out.append(f"{s(c.get('id'))} [{s(c.get('priority'))}] {s(c.get('text'))} | {s(v.get('type'))}: {s(v.get('how'))}")
    if not ids:
        out.append(f"core probe: {s(data.get('core_probe'))}")
    if owner:
        cut = [s(i.get("text")) for i in data.get("cut") or [] if isinstance(i, dict) and s(i.get("text"))]
        out.append("cut (becomes backlog issues): " + ("; ".join(cut) or "-"))
        out.append(f"hash: {contract_hash(data)}")
        out.append(f"To approve exactly this, reply: approved {contract_hash(data)}")
    return "\n".join(out) + "\n"


def issue_drafts(path: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    """One draft per work package, plus one backlog draft per cut item. Criteria are cited, never redefined."""
    meta = data.get("contract") or {}
    cid, ver, ms = s(meta.get("id")), s(meta.get("version")), s(meta.get("milestone"))
    by_id = {s(c.get("id")): c for c in data.get("criteria") or [] if isinstance(c, dict)}
    ref = f"{path.as_posix()} ({cid} v{ver}, hash {contract_hash(data)})"
    drafts: list[dict[str, Any]] = []
    for wp in data.get("work_packages") or []:
        if not isinstance(wp, dict):
            continue
        rows = []
        for i in map(s, wp.get("criteria") or []):
            c = by_id.get(i)
            if c:
                v = c.get("verify") if isinstance(c.get("verify"), dict) else {}
                rows.append(f"- [ ] **{i}** ({s(c.get('priority'))}) {s(c.get('text'))}\n  Verify ({s(v.get('type'))}): `{s(v.get('how'))}`")
        after = wp.get("after") or []
        after = [s(a) for a in (after if isinstance(after, list) else [after])]
        titles = {s(w.get("key")): s(w.get("title")) for w in data.get("work_packages") or [] if isinstance(w, dict)}
        after_line = ["Start after: " + "; ".join(f"[{cid}] {titles.get(a, a)}" for a in after), ""] if after else []
        body = "\n".join([
            f"Goal of {ms or cid}: {s(data.get('goal'))}", "", *after_line,
            "## Acceptance criteria", *rows, "",
            f"Source of truth: {ref}. The criteria are frozen there; to change one, change the contract (new version, owner approval), not this issue.",
        ])
        drafts.append({"key": s(wp.get("key")), "title": f"[{cid}] {s(wp.get('title'))}",
                       "labels": [x for x in [s(wp.get("label"))] if x], "milestone": ms, "body": body})
    for n, item in enumerate(data.get("cut") or [], 1):
        if isinstance(item, dict) and not is_placeholder(item.get("text")):
            body = f"Cut from {cid} v{ver} ({ms}).\n\nReason: {s(item.get('reason')) or 'not needed for this milestone'}\n\nNot specified yet: run specify before building it."
            drafts.append({"key": f"cut-{n}", "title": f"[backlog] {s(item.get('text'))}", "labels": ["backlog"], "milestone": "", "body": body})
    return drafts


def record_path(contract: Path, data: dict[str, Any], given: Path | None = None) -> Path:
    """Where the created issue numbers of this contract (all versions) are kept."""
    cid = s((data.get("contract") or {}).get("id")) or "contract"
    return given or contract.resolve().parent / f"issues-{cid}.json"


def read_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"packages": {}}
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(rec, dict) or not isinstance(rec.get("packages"), dict):
        raise ValueError(f"{path} must be an object with a 'packages' object")
    return rec


def plan_issues(drafts: list[dict[str, Any]], record: dict[str, Any], version: str) -> list[dict[str, Any]]:
    """Mark each draft with what to do, given the issues already created, and list issues with no draft left."""
    known = record.get("packages") or {}
    for d in drafts:
        entry = known.get(d["key"])
        if not isinstance(entry, dict) or "issue" not in entry:
            d["action"] = "create"
        elif s(entry.get("version")) == version:
            d["action"], d["existing_issue"] = "exists", entry["issue"]
        else:
            d["action"], d["existing_issue"], d["existing_version"] = "replaces", entry["issue"], entry.get("version")
    keys = {d["key"] for d in drafts}
    return [{"key": k, "issue": e.get("issue"), "version": e.get("version"), "title": e.get("title", "")}
            for k, e in sorted(known.items()) if k not in keys and isinstance(e, dict)]


def preflight(drafts: list[dict[str, Any]], repo: str, have_labels: list[str] | None, have_milestones: list[str] | None) -> tuple[str, bool]:
    """What must exist on GitHub before the issues are created, and whether anything is known to be missing."""
    labels = sorted({l for d in drafts if d.get("action", "create") != "exists" for l in d["labels"]})
    milestones = sorted({d["milestone"] for d in drafts if d["milestone"] and d.get("action", "create") != "exists"})
    r = repo or "<owner>/<repo>"
    out = [f"Labels needed: {', '.join(labels) or '-'}", f"Milestones needed: {', '.join(milestones) or '-'}"]
    missing = False
    if have_labels is None or have_milestones is None:
        out += [
            "Check that they exist before creating any issue (GitHub CLI shown; any GitHub access works):",
            f"  gh label list --repo {r} --limit 300 --json name --jq '.[].name'",
            f"  gh api 'repos/{r}/milestones?state=all&per_page=100' --jq '.[].title'",
            "Then run this again with --have-labels \"a,b\" --have-milestones \"x,y\" to see what is missing.",
        ]
    else:
        ml = [l for l in labels if l not in have_labels]
        mm = [m for m in milestones if m not in have_milestones]
        missing = bool(ml or mm)
        out.append(f"Missing labels: {', '.join(ml) or 'none'}")
        for l in ml:
            out.append(f"  gh label create \"{l}\" --repo {r}    (lane and risk labels: the scaffold's github-setup/create-labels.sh has all of them)")
        out.append(f"Missing milestones: {', '.join(mm) or 'none'}")
        if mm:
            out.append("  Creating a milestone is an owner hand step unless the ruleset says otherwise (ROLE-02): ask, do not create it.")
        out.append("Pre-flight failed: create nothing until the missing items exist." if missing else "Pre-flight passed.")
    return "\n".join(out) + "\n", missing


def render_issues(drafts: list[dict[str, Any]], obsolete: list[dict[str, Any]] | None = None) -> str:
    out = []
    for n, d in enumerate(drafts, 1):
        todo = {"create": "create",
                "exists": f"already created as #{d.get('existing_issue')}: skip",
                "replaces": f"replaces #{d.get('existing_issue')} (made for v{d.get('existing_version')}): the owner decides whether to edit or close it"}[d.get("action", "create")]
        head = (f"### Draft {n} ({d['key']}): {d['title']}\nLabels: {', '.join(d['labels']) or '-'} | "
                f"Milestone: {d['milestone'] or '-'} | To do: {todo}")
        out.append(head + "\n\n" + d["body"])
    text = "\n\n---\n\n".join(out) + "\n"
    if obsolete:
        text += "\n---\n\nIssues whose work package is no longer in this version (the owner decides: close or keep):\n"
        text += "".join(f"- #{o['issue']} ({o['key']}, made for v{o['version']}) {o['title']}\n" for o in obsolete)
    return text


def lint_roadmap(data: dict[str, Any], plans: Path | None) -> list[Finding]:
    f: list[Finding] = []
    ms = data.get("milestones")
    if not isinstance(ms, list) or not ms:
        return [Finding("R001", "ERROR", "milestones must be a non-empty, ordered list", "milestones")]
    contracts: dict[str, list[dict[str, Any]]] = {}
    if plans and plans.is_dir():
        for cp in sorted(plans.glob("contract-*.y*ml")):
            if cp.name == TEMPLATE_NAME:
                continue
            try:
                cd = load(cp)
            except Exception:
                f.append(Finding("R005", "WARN", f"cannot read {cp.name}", "plans"))
                continue
            m = s((cd.get("contract") or {}).get("milestone"))
            contracts.setdefault(m, []).append(cd)
    names: set[str] = set()
    for i, m in enumerate(ms):
        if not isinstance(m, dict) or is_placeholder(m.get("name")):
            f.append(Finding("R001", "ERROR", "milestone needs a name", f"milestones[{i}]"))
            continue
        name = s(m.get("name"))
        if name in names:
            f.append(Finding("R002", "ERROR", f"milestone {name} appears twice", name))
        names.add(name)
        status = s(m.get("status")).lower()
        if status not in ROADMAP_STATUSES:
            f.append(Finding("R003", "ERROR", f"status must be one of {sorted(ROADMAP_STATUSES)}, got '{status}'", name))
        if is_placeholder(m.get("goal")) and status != "dropped":
            f.append(Finding("R004", "WARN", "goal sentence is missing", name))
        if plans is None:
            continue
        mine = contracts.get(name, [])
        approved = [c for c in mine if s((c.get("contract") or {}).get("status")).lower() == "approved"]
        if status == "active" and not approved:
            f.append(Finding("R006", "ERROR", "active milestone has no owner-approved acceptance contract; run specify first", name))
        if status == "dropped" and approved:
            f.append(Finding("R007", "WARN", "dropped milestone still has an approved contract; mark it superseded so no thread works from it", name))
        if len(approved) > 1:
            f.append(Finding("R008", "ERROR", "more than one approved contract version; mark the older ones superseded", name))
        want = s(m.get("contract"))
        have = {s((c.get("contract") or {}).get("id")) for c in mine}
        if want and have and want not in have:
            f.append(Finding("R009", "WARN", f"roadmap names contract {want} but plans/ holds {', '.join(sorted(have))} for this milestone", name))
    if plans is not None:
        for m_name in sorted(set(contracts) - names - {""}):
            f.append(Finding("R010", "WARN", f"plans/ holds a contract for milestone '{m_name}' that is not on the roadmap", m_name))
    return f


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
    p_lint.add_argument("--max-package-criteria", type=int, default=MAX_PACKAGE_CRITERIA,
                        help=f"warn when a work package holds more criteria (default {MAX_PACKAGE_CRITERIA}, 0 = no check)")
    p_sum = sub.add_parser("summary", help="five-line hand-back for the coordinator, with the pickup line")
    p_sum.add_argument("contract", type=Path)
    p_brief = sub.add_parser("brief", help="compact criteria view for worker threads; --owner: everything the owner approves")
    p_brief.add_argument("contract", type=Path)
    p_brief.add_argument("--ids", help="comma-separated criterion ids (default: all)")
    p_brief.add_argument("--owner", action="store_true", help="add users, access, constraints, out of scope, cut items and the hash")
    p_hash = sub.add_parser("hash", help="print the value for approval.hash")
    p_hash.add_argument("contract", type=Path)
    p_iss = sub.add_parser("issues", help="issue drafts from work packages and cut items (prints only, creates nothing)")
    p_iss.add_argument("contract", type=Path)
    p_iss.add_argument("--json", action="store_true")
    p_iss.add_argument("--record", type=Path, help="file with the issue numbers already created (default: issues-<contract id>.json next to the contract)")
    p_iss.add_argument("--preflight", action="store_true", help="print the labels and milestones that must exist, and how to check them")
    p_iss.add_argument("--repo", help="owner/repo for the pre-flight commands (default: `repository` of the ruleset)")
    p_iss.add_argument("--have-labels", help="comma-separated labels that exist on GitHub (with --preflight)")
    p_iss.add_argument("--have-milestones", help="comma-separated milestones that exist on GitHub (with --preflight)")
    p_rec = sub.add_parser("record-issue", help="note the GitHub issue number created for a work package, so a second run does not create it again")
    p_rec.add_argument("contract", type=Path)
    p_rec.add_argument("key", help="work package key, or cut-<n> for a backlog item, as shown by `issues`")
    p_rec.add_argument("number", type=int, help="the issue number GitHub returned")
    p_rec.add_argument("--record", type=Path)
    p_road = sub.add_parser("roadmap", help="check roadmap.yaml, optionally against the contracts in a plans directory")
    p_road.add_argument("contract", type=Path, metavar="roadmap")
    p_road.add_argument("--plans", type=Path)
    p_road.add_argument("--strict", action="store_true")
    p_goal = sub.add_parser("goal", help="print a /goal line for Claude Code")
    p_goal.add_argument("contract", type=Path)
    p_goal.add_argument("--ids", help="comma-separated criterion ids (default: all must criteria + core probe)")
    p_goal.add_argument("--turns", type=int, default=30)
    p_goal.add_argument("--allow-draft", action="store_true")
    for sp in (p_lint, p_goal, p_iss):
        sp.add_argument("--state", type=Path, help="project-state.yaml holding the pickup records (default: ../project-state.yaml)")
        sp.add_argument("--decision-log", type=Path, help="decision log holding the pickup records (default: ../kb/decision-log.md)")
        sp.add_argument("--rules", type=Path, help="ruleset to check work-package labels against (default: ../claude-project-rules.yaml)")
    args = ap.parse_args()

    try:
        data = load(args.contract)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: cannot read {args.contract}: {e}", file=sys.stderr)
        return 2

    if args.cmd == "summary":
        print(summary(args.contract, data), end="")
        return 0
    if args.cmd == "brief":
        print(brief(data, [i.strip() for i in args.ids.split(",")] if args.ids else None, owner=args.owner), end="")
        return 0
    if args.cmd == "hash":
        print(contract_hash(data))
        return 0
    if args.cmd == "roadmap":
        rf = lint_roadmap(data, args.plans)
        print(render_markdown(args.contract, rf).replace("# Contract lint:", "# Roadmap check:").replace(
            "Judge the criteria themselves next: are they the right ones?", "Order and goals are the owner's call."), end="")
        return 1 if any(x.severity == "ERROR" for x in rf) or (args.strict and any(x.severity == "WARN" for x in rf)) else 0
    if args.cmd == "record-issue":
        try:
            path = record_path(args.contract, data, args.record)
            rec = read_record(path)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        drafts = {d["key"]: d for d in issue_drafts(args.contract, data)}
        if args.key not in drafts:
            print(f"error: '{args.key}' is not a work package or cut item of this contract; known: {', '.join(drafts)}", file=sys.stderr)
            return 1
        if args.number < 1:
            print("error: the issue number must be positive", file=sys.stderr)
            return 1
        meta = data.get("contract") or {}
        rec["contract"] = s(meta.get("id"))
        rec["packages"][args.key] = {"issue": args.number, "version": meta.get("version"), "title": drafts[args.key]["title"]}
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded {args.key} -> #{args.number} in {path}")
        return 0

    record_texts, rules_path = workspace_files(args.contract, getattr(args, "state", None),
                                               getattr(args, "decision_log", None), getattr(args, "rules", None))
    labels, repo = ruleset_labels(rules_path)

    if args.cmd == "issues":
        errs = [x for x in lint(data, labels=labels) if x.severity == "ERROR"]
        if errs:
            print(f"error: {len(errs)} lint error(s); run `contract_tool.py lint` first", file=sys.stderr)
            return 1
        drafts = issue_drafts(args.contract, data)
        try:
            obsolete = plan_issues(drafts, read_record(record_path(args.contract, data, args.record)),
                                   s((data.get("contract") or {}).get("version")))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.preflight:
            split = lambda v: None if v is None else [x.strip() for x in v.split(",") if x.strip()]  # noqa: E731
            text, missing = preflight(drafts, args.repo or repo, split(args.have_labels), split(args.have_milestones))
            print(text, end="")
            return 1 if missing else 0
        if args.json:
            print(json.dumps({"drafts": drafts, "obsolete": obsolete}, indent=2, ensure_ascii=False))
        else:
            print(render_issues(drafts, obsolete), end="")
        return 0

    findings = lint(data, getattr(args, "max_package_criteria", MAX_PACKAGE_CRITERIA),
                    record_texts=record_texts, labels=labels)
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
    meta = data.get("contract") or {}
    if status == "approved" and not find_records(s(meta.get("id")), s(meta.get("version")), record_texts):
        print(f"error: no pickup record for {s(meta.get('id'))} v{s(meta.get('version'))} (no D-number): the coordinator has not "
              "picked this contract up yet (PLAN-03). It records the line from `contract_tool.py summary` in "
              "approved_contracts of project-state.yaml; --state names a state file elsewhere", file=sys.stderr)
        return 1
    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    print(goal_line(args.contract, data, ids, args.turns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
