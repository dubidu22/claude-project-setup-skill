#!/usr/bin/env python3
"""
Mechanical audit of a `claude-project-rules.yaml` ruleset (and optionally its
`project-state.yaml`) for multi-thread Claude project governance.

This script finds the things a machine can find reliably: duplicate or missing
rule ids, missing `applies_to` scopes, labels referenced but never declared,
volatile state leaking into the static ruleset, dead history, implausible
numeric thresholds, and a few contradiction *patterns* that deserve a human
look. It does not understand the rules; the semantic contradictions are judged
by Claude using references/audit-checklist.md after reading this report.

Usage:
    python3 audit_rules.py claude-project-rules.yaml
    python3 audit_rules.py claude-project-rules.yaml --state project-state.yaml
    python3 audit_rules.py claude-project-rules.yaml --json      # machine-readable
    python3 audit_rules.py claude-project-rules.yaml --strict    # exit 1 on WARN too
    python3 audit_rules.py claude-project-rules.yaml --extracts rules   # per-role extracts (default: ./rules next to the file)

Exit code: 0 clean or only WARN/INFO, 1 when any ERROR (or WARN with --strict),
2 when the file cannot be read or parsed.

Works with or without PyYAML. Without it, a small line-based reader extracts the
rule entries and the top-level scalar/list fields the checks need.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

VALID_SCOPES = {"owner", "coordinator", "dispatcher", "specify", "assist", "advisor", "implementation", "review", "kb", "audit", "all"}
VOLATILE_KEYS = {
    "active_now",
    "paused",
    "slow_down",
    "thread_freeze",
    "active_milestones",
    "notifications_pending",
    "owner_autonomy_message_ids",
    "current_batch",
    "approved_contracts",
    "closed_milestones",
    "owner_open_steps",
    "active_threads",
    "pending_notifications",
}
DEAD_HISTORY_MARKERS = [
    r"\blifted\b",
    r"\bno longer\b",
    r"\bsuperseded\b",
    r"\bdeprecated\b",
    r"\bretired\b",
    r"\bhistorical\b",
    r"\bwas previously\b",
    r"\buntil \d{4}-\d{2}-\d{2}\b",
    r"\(removed",
    r"\bobsolete\b",
]
HISTORY_SECTION_NAMES = {"history", "commands_history", "lifted_rules", "archive", "changelog", "past_commands"}
REQUIRED_TOKEN_KEYS = {
    "max_concurrent_lanes",
    "replace_at_compressions",
    "watchdog_interval_minutes",
    "non_critical_max_review_rounds",
    "critical_max_review_rounds",
}
LEGACY_ROUTING_KEYS = {"coordinator", "implementation_and_critical_review", "standard_review_audit_and_kb"}
REQUIRED_ROUTING_KEYS = {"coordinator", "specify", "critical_work", "implementation", "review_kb_audit", "operations"}
NUMERIC_TOKEN_KEYS = {
    "max_concurrent_lanes", "replace_at_compressions", "replace_after_prs", "watchdog_interval_minutes",
    "watchdog_max_nudges", "non_critical_max_review_rounds", "critical_max_review_rounds", "rounds_after_escalation",
    "goal_turn_cap", "cache_ttl_minutes", "coordinator_compact_at_tokens", "coordinator_compact_every_batches",
}
LONG_RULE_CHARS = 450
# What one thread reads at its start is its role's rules plus the rules for all, so that is what is counted.
MANY_RULES_PER_ROLE = 40
MANY_RULES_TOTAL = 90


@dataclass
class Finding:
    code: str
    severity: str  # ERROR | WARN | INFO
    message: str
    where: str = ""


@dataclass
class Rule:
    id: str | None
    applies_to: str | None
    text: str
    section: str
    line: int
    extra_keys: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Loading: PyYAML when available, line-based fallback otherwise.
# ----------------------------------------------------------------------------

def model_tier(name: str) -> int:
    """A rough cost tier from a model name the owner typed: 4 Fable or Mythos, 3 Opus, 2 Sonnet, 1 Haiku, 0 unknown."""
    n = name.lower()
    for tier, words in ((4, ("fable", "mythos")), (3, ("opus",)), (2, ("sonnet",)), (1, ("haiku",))):
        if any(w in n for w in words):
            return tier
    return 0


def load_yaml_or_none(path: Path) -> dict[str, Any] | None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"error: YAML parse failure in {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    if data is None:
        return {}
    if not isinstance(data, dict):
        print(f"error: {path} is not a YAML mapping at the top level", file=sys.stderr)
        sys.exit(2)
    return data


def rules_from_data(data: dict[str, Any], text: str) -> list[Rule]:
    """Extract rule entries (list items with id/applies_to/rule) from parsed YAML."""
    line_of_id = {}
    for i, raw in enumerate(text.splitlines(), 1):
        m = re.match(r"\s*-\s*id:\s*(\S+)", raw)
        if m:
            line_of_id.setdefault(m.group(1).strip("\"'"), i)
    rules: list[Rule] = []
    for section, value in data.items():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if not ({"id", "rule", "applies_to"} & set(item)):
                continue
            rid = item.get("id")
            rid = str(rid) if rid is not None else None
            scope = item.get("applies_to")
            rules.append(
                Rule(
                    id=rid,
                    applies_to=str(scope) if scope is not None else None,
                    text=str(item.get("rule", "") or ""),
                    section=str(section),
                    line=line_of_id.get(rid or "", 0),
                    extra_keys=sorted(set(item) - {"id", "applies_to", "rule", "values", "note"}),
                )
            )
    return rules


def strip_comment(line: str) -> str:
    """Remove a trailing YAML comment. A '#' inside quotes is text, not a comment."""
    quote = ""
    i = 0
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


def unquote(v: str) -> str:
    """Value of a plain, single-quoted or double-quoted YAML scalar."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        out, i, body = [], 0, v[1:-1]
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                if nxt == "x" and i + 3 < len(body):
                    try:
                        out.append(chr(int(body[i + 2:i + 4], 16)))
                        i += 4
                        continue
                    except ValueError:
                        pass
                out.append(escapes.get(nxt, nxt))
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def split_inline(body: str) -> list[str]:
    """Split the inside of an inline list on commas that are outside quotes."""
    items, cur, quote, i = [], [], "", 0
    while i < len(body):
        ch = body[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(body):
                cur.append(body[i + 1])
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    items.append("".join(cur))
    return [x.strip() for x in items if x.strip()]


def fallback_parse(text: str) -> tuple[dict[str, Any], list[Rule]]:
    """Very small reader for the generator's flat layout when PyYAML is absent."""
    data: dict[str, Any] = {}
    rules: list[Rule] = []
    section = ""
    current: Rule | None = None
    stack: list[tuple[int, str]] = []  # (indent, key) for nested scalar maps

    def strip_q(v: str) -> Any:
        v = v.strip()
        if v in ("true", "false"):
            return v == "true"
        return unquote(v)

    def inline(val: str) -> list[str]:
        return [unquote(x) for x in split_inline(val[1:-1])]

    for i, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        m_item = re.match(r"\s*-\s*id:\s*(.+)$", line)
        if m_item:
            current = Rule(id=unquote(m_item.group(1)), applies_to=None, text="", section=section, line=i)
            rules.append(current)
            continue
        m_kv = re.match(r"\s*([A-Za-z_][\w-]*):\s*(.*)$", line)
        m_li = re.match(r"\s*-\s+(.+)$", line)
        if m_li and not m_kv and current is None and section and data.get(section) in ({}, []) or (
            m_li and not m_kv and current is None and isinstance(data.get(section), list)
        ):
            # a block list of plain values under a top-level key, e.g. `authority:`
            if not isinstance(data.get(section), list):
                data[section] = []
            data[section].append(strip_q(m_li.group(1)))
            continue
        if not m_kv:
            continue
        key, val = m_kv.group(1), m_kv.group(2)
        if indent == 0:
            section = key
            current = None
            stack = [(0, key)]
            if val == "":
                data[key] = {}
            elif val.startswith("[") and val.endswith("]"):
                data[key] = inline(val)
            else:
                data[key] = strip_q(val)
            continue
        if current is not None and indent >= 4:
            if key == "applies_to":
                current.applies_to = unquote(val)
            elif key == "rule":
                current.text = unquote(val)
            elif key not in {"values", "note"}:
                current.extra_keys.append(key)
            continue
        # nested scalar map under a top-level mapping (project_profile, execution_profile ...)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        node = data
        for _, k in stack:
            node = node.setdefault(k, {}) if isinstance(node, dict) else node
        if isinstance(node, dict):
            if val == "":
                node[key] = {}
                stack.append((indent, key))
            elif val.startswith("[") and val.endswith("]"):
                node[key] = inline(val)
            else:
                v = strip_q(val)
                node[key] = int(v) if isinstance(v, str) and re.fullmatch(r"-?\d+", v) and val.strip() == v else v
    return data, rules


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

def get_path(data: dict[str, Any], *keys: str) -> Any:
    node: Any = data
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def run_checks(data: dict[str, Any], rules: list[Rule], raw_text: str, state_text: str | None,
               extracts: dict[str, str] | None = None) -> list[Finding]:
    f: list[Finding] = []

    # --- A01 header fields ---
    for key in ("version", "date", "project", "authority"):
        if key not in data:
            f.append(Finding("A01", "WARN", f"top-level `{key}` is missing", "header"))
    date = data.get("date")
    if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        f.append(Finding("A01", "WARN", f"`date` should be YYYY-MM-DD, got {date!r}", "header"))

    # --- A13 authority order ---
    authority = data.get("authority")
    if isinstance(authority, list):
        order = [str(x) for x in authority]
        pos = {name: i for i, name in enumerate(order)}
        if "owner_messages" in pos and "kb_decision_log" in pos and pos["kb_decision_log"] < pos["owner_messages"]:
            f.append(Finding("A13", "WARN", "`authority` ranks the decision log above the owner's messages; the owner's newest message on a point must outrank older D-entries (ROLE-01)", "authority"))
        if not any("ruleset" in name for name in order):
            f.append(Finding("A13", "WARN", "`authority` does not list the ruleset itself; say where it ranks", "authority"))
        if any(re.search(r"acceptance[- ]contract", r.text, re.I) for r in rules) and not any("contract" in name for name in order):
            f.append(Finding("A13", "WARN", "`authority` does not list approved acceptance contracts although the rules use them", "authority"))

    # --- A02 rule ids unique, present, well-formed ---
    seen: dict[str, Rule] = {}
    for r in rules:
        if not r.id:
            f.append(Finding("A02", "ERROR", f"rule without an `id` in section `{r.section}`", f"line {r.line or '?'}"))
            continue
        if r.id in seen:
            f.append(Finding("A02", "ERROR", f"duplicate rule id `{r.id}` (first at line {seen[r.id].line})", f"line {r.line}"))
        else:
            seen[r.id] = r
        if not re.fullmatch(r"[A-Z]{2,6}-\d{2,3}", r.id):
            f.append(Finding("A02", "INFO", f"rule id `{r.id}` does not follow the `ABC-01` convention", f"line {r.line}"))

    # --- A03 applies_to present and valid ---
    for r in rules:
        rid = r.id or f"(unnamed, line {r.line})"
        if r.applies_to is None or not str(r.applies_to).strip():
            f.append(Finding("A03", "ERROR", f"rule `{rid}` has no `applies_to` scope", f"line {r.line}"))
        else:
            scopes = {s.strip() for s in str(r.applies_to).replace("|", ",").split(",")}
            bad = scopes - VALID_SCOPES
            if bad:
                f.append(Finding("A03", "ERROR", f"rule `{rid}` has unknown applies_to value(s): {', '.join(sorted(bad))}", f"line {r.line}"))
        if not r.text.strip():
            f.append(Finding("A03", "ERROR", f"rule `{rid}` has empty `rule` text", f"line {r.line}"))
        if r.extra_keys:
            f.append(Finding("A03", "INFO", f"rule `{rid}` carries unexpected keys: {', '.join(r.extra_keys)}", f"line {r.line}"))

    # --- A04 lanes and labels ---
    labels = get_path(data, "project_profile", "file_ownership_labels") or []
    lanes = get_path(data, "project_profile", "execution_lanes") or []
    labels = [str(x) for x in labels] if isinstance(labels, list) else []
    lanes = [str(x) for x in lanes] if isinstance(lanes, list) else []
    if not labels:
        f.append(Finding("A04", "WARN", "no `project_profile.file_ownership_labels` declared", "project_profile"))
    if not lanes:
        f.append(Finding("A04", "WARN", "no `project_profile.execution_lanes` declared", "project_profile"))
    all_text = " ".join(r.text for r in rules)
    mentions_infra_lock = bool(re.search(r"lane:infra", all_text))
    if mentions_infra_lock and labels and "lane:infra" not in labels:
        f.append(Finding("A04", "ERROR", "rules require `lane:infra` for core changes but `lane:infra` is not in file_ownership_labels", "project_profile"))
    for needed in ("lane:core", "lane:docs"):
        if labels and needed not in labels and needed in all_text:
            f.append(Finding("A04", "WARN", f"rules mention `{needed}` but it is not declared in file_ownership_labels", "project_profile"))
    referenced = set(re.findall(r"\blane:[a-z0-9_-]+", raw_text))
    if mentions_infra_lock and labels and "lane:infra" not in labels:
        referenced.discard("lane:infra")  # already reported as an error above
    undeclared = sorted(l for l in referenced if labels and l not in labels)
    if undeclared:
        f.append(Finding("A04", "WARN", f"label(s) referenced in rules but not declared: {', '.join(undeclared)}", "rules"))
    note = get_path(data, "project_profile", "lane_mapping_note")
    if lanes and labels and not note:
        f.append(Finding("A04", "WARN", "no `lane_mapping_note` explaining which labels map to which execution lane", "project_profile"))

    # --- A05 execution profile sanity ---
    routing = get_path(data, "execution_profile", "model_routing") or {}
    token = get_path(data, "execution_profile", "token_economy") or {}

    # --- A17 per-PR work on the coordinator's model ---
    if isinstance(routing, dict):
        scopes = {x.strip() for r in rules for x in str(r.applies_to or "").replace("|", ",").split(",")}
        lanes_n = to_int(token.get("max_concurrent_lanes")) if isinstance(token, dict) else None
        coord, ops = str(routing.get("coordinator") or ""), str(routing.get("operations") or "")
        if "dispatcher" not in scopes and (lanes_n or 0) >= 3:  # one or two lanes may run without one (init.md)
            f.append(Finding("A17", "WARN", f"no dispatcher while up to {lanes_n} lanes run at once: every watch, merge go and "
                             f"relay of every PR is a turn of the coordinator on {coord or 'its model'}, on its whole context. "
                             "Turn the dispatcher on (dispatcher=true) and give the operations slot a cheaper model",
                             "execution_profile"))
        tc, to = model_tier(coord), model_tier(ops)
        if to >= 3 or (tc and to and to >= tc):
            same = " the same tier as the coordinator," if tc and to >= tc else ""
            f.append(Finding("A17", "INFO", f"the operations slot ({ops}) is on{same} a top tier: dispatcher watches, merge go "
                             "and hand steps need no planning model. A Sonnet-class model is enough for them",
                             "execution_profile"))
    have = set(routing) if isinstance(routing, dict) else set()
    # Rulesets generated before the routing was split carry three keys; both shapes are valid.
    wanted = LEGACY_ROUTING_KEYS if (have & LEGACY_ROUTING_KEYS) - {"coordinator"} else REQUIRED_ROUTING_KEYS
    if not wanted <= have:
        missing = sorted(wanted - have)
        f.append(Finding("A05", "WARN", f"model_routing missing: {', '.join(missing) or 'whole section'}", "execution_profile"))
    blank = sorted(k for k in have if not str(routing.get(k) or "").strip())
    if blank:
        f.append(Finding("A05", "WARN", f"model_routing has no model for: {', '.join(blank)}", "execution_profile"))
    if not isinstance(token, dict) or not REQUIRED_TOKEN_KEYS <= set(token):
        missing = sorted(REQUIRED_TOKEN_KEYS - set(token if isinstance(token, dict) else {}))
        f.append(Finding("A05", "WARN", f"token_economy missing: {', '.join(missing) or 'whole section'}", "execution_profile"))
    if isinstance(token, dict):
        for key in sorted(NUMERIC_TOKEN_KEYS & set(token)):
            v = token[key]
            if isinstance(v, bool) or to_int(v) is None or str(v).strip() != str(to_int(v)):
                f.append(Finding("A05", "ERROR", f"{key} must be a whole number, got {v!r}; threads cannot act on it", "execution_profile"))
        ncr_rounds = to_int(token.get("non_critical_max_review_rounds"))
        if ncr_rounds == 1:
            f.append(Finding("A05", "WARN", "non_critical_max_review_rounds=1 leaves no round in which the reviewer confirms the fix; review and verification are where tokens pay off, so save on coordination instead (2 is the lowest profile value)", "execution_profile"))
        rap = to_int(token.get("replace_after_prs"))
        if rap is not None and rap < 1:
            f.append(Finding("A05", "ERROR", "replace_after_prs must be at least 1", "execution_profile"))
        mcl = to_int(token.get("max_concurrent_lanes"))
        rac = to_int(token.get("replace_at_compressions"))
        wim = to_int(token.get("watchdog_interval_minutes"))
        ncr = to_int(token.get("non_critical_max_review_rounds"))
        ccr = to_int(token.get("critical_max_review_rounds"))
        if mcl is not None and lanes and mcl > len(lanes):
            f.append(Finding("A05", "WARN", f"max_concurrent_lanes={mcl} exceeds the {len(lanes)} declared execution lanes (one thread per lane)", "execution_profile"))
        if mcl is not None and mcl < 1:
            f.append(Finding("A05", "ERROR", "max_concurrent_lanes must be at least 1", "execution_profile"))
        if rac is not None and rac < 1:
            f.append(Finding("A05", "ERROR", "replace_at_compressions must be at least 1 (0 would replace threads before they start)", "execution_profile"))
        if wim is not None and wim <= 0:
            f.append(Finding("A05", "ERROR", "watchdog_interval_minutes must be positive", "execution_profile"))
        ttl = to_int(token.get("cache_ttl_minutes"))
        if ttl is not None and ttl not in (5, 60):
            f.append(Finding("A05", "WARN", f"cache_ttl_minutes={ttl}; the prompt cache lasts 60 minutes on a subscription and 5 on an API key or usage credits", "execution_profile"))
        cct = to_int(token.get("coordinator_compact_at_tokens"))
        if cct is not None and cct < 0:
            f.append(Finding("A05", "ERROR", "coordinator_compact_at_tokens must be 0 (never) or a positive token count", "execution_profile"))
        if ttl is None and any(re.search(r"cache_ttl_minutes", r.text) for r in rules):
            f.append(Finding("A05", "WARN", "rules refer to cache_ttl_minutes but token_economy does not set it", "execution_profile"))
        if ncr is not None and ccr is not None and ncr > ccr:
            f.append(Finding("A05", "ERROR", f"non_critical_max_review_rounds={ncr} exceeds critical_max_review_rounds={ccr}", "execution_profile"))
        # A rule that names the round at which critical PRs stop must name the configured one.
        if ccr is not None:
            off: dict[int, list[str]] = {}
            for r in rules:
                for sentence in re.split(r"(?<=[.;])\s+", r.text):
                    if re.search(r"hard stop|sign-?off", sentence, re.I):
                        found = re.findall(r"\bround[\s-]*(\d+)\b", sentence, re.I)
                    elif re.search(r"(?<!non-)\bcritical prs?\b", sentence, re.I):
                        found = re.findall(r"\b(?:up to|after|at|until|reach\w*|hits?)\s+(?:review\s+)?round[\s-]*(\d+)\b", sentence, re.I)
                    else:
                        continue
                    for n in found:
                        if int(n) != ccr and (r.id or "?") not in off.setdefault(int(n), []):
                            off[int(n)].append(r.id or "?")
            for n, ids in sorted(off.items()):
                f.append(Finding("A05", "ERROR", f"critical_max_review_rounds={ccr} but rule(s) {', '.join(ids)} hard-code a round-{n} stop", "execution_profile"))

    # --- A06 volatile state inside the static ruleset ---
    for key in data:
        if key in VOLATILE_KEYS:
            f.append(Finding("A06", "ERROR", f"volatile runtime key `{key}` lives in the ruleset; move it to project-state.yaml", f"section {key}"))
    for r in rules:
        if re.search(r"\b(paused|active_milestones|currently active|as of \d{4}-\d{2}-\d{2}|this week|right now)\b", r.text, re.I):
            f.append(Finding("A06", "WARN", f"rule `{r.id}` reads like runtime state rather than a standing rule", f"line {r.line}"))
    if "state_file" not in json.dumps(get_path(data, "project_profile") or {}):
        f.append(Finding("A06", "INFO", "project_profile has no `state_file` pointer to project-state.yaml", "project_profile"))

    # --- A07 dead history / lifted commands ---
    for key in data:
        if key.lower() in HISTORY_SECTION_NAMES:
            f.append(Finding("A07", "WARN", f"section `{key}` keeps history in the live ruleset; every token of it is re-read by every thread", f"section {key}"))
    for r in rules:
        for marker in DEAD_HISTORY_MARKERS:
            if re.search(marker, r.text, re.I):
                f.append(Finding("A07", "WARN", f"rule `{r.id}` looks like dead history (matches '{marker.strip(chr(92)+'b')}'); replace with the current rule or delete", f"line {r.line}"))
                break

    # --- A08 token bloat ---
    per_role: dict[str, int] = {}
    n_all = sum(1 for r in rules if str(r.applies_to or "").strip() == "all")
    for r in rules:
        for scope in {x.strip() for x in str(r.applies_to or "").replace("|", ",").split(",")} - {"all", "owner", ""}:
            per_role[scope] = per_role.get(scope, 0) + 1
    heavy = sorted((n + n_all, role) for role, n in per_role.items() if n + n_all > MANY_RULES_PER_ROLE)
    for n, role in heavy:
        f.append(Finding("A08", "WARN", f"a {role} thread is bound by {n} rules (its own plus those for all); above ~{MANY_RULES_PER_ROLE} threads start skimming. Merge or demote to references.", "rules"))
    if len(rules) > MANY_RULES_TOTAL:
        f.append(Finding("A08", "WARN", f"{len(rules)} rules in total; merge or demote to references.", "rules"))
    for r in rules:
        if len(r.text) > LONG_RULE_CHARS:
            f.append(Finding("A08", "INFO", f"rule `{r.id}` is {len(r.text)} chars; consider splitting or tightening", f"line {r.line}"))
    norm: dict[str, Rule] = {}
    for r in rules:
        key = re.sub(r"[^a-z0-9 ]", "", r.text.lower())
        key = " ".join(key.split()[:12])
        if key and key in norm:
            f.append(Finding("A08", "WARN", f"rules `{norm[key].id}` and `{r.id}` start with the same wording; likely duplicates", f"line {r.line}"))
        elif key:
            norm[key] = r

    # --- A09 contradiction patterns that need a human read ---
    def rules_matching(pattern: str) -> list[Rule]:
        return [r for r in rules if re.search(pattern, r.text, re.I)]

    reduced_release_ci = rules_matching(r"release/\*\*?.*\b(only|linux-only|ubuntu-only|single)\b|\b(only|linux-only|ubuntu-only)\b.*release/")
    full_matrix_critical = rules_matching(r"critical.*(full[- ]matrix|full multi-platform|all target_platforms|full[- ]ci)|(full[- ]matrix|full[- ]ci|full multi-platform).*critical")
    overriding = [r for r in reduced_release_ci if re.search(r"regardless|every pr|all prs|no exception|including critical", r.text, re.I)]
    if overriding:
        ids = ", ".join(r.id or "?" for r in overriding)
        other = (" (contradicts " + ", ".join(r.id or "?" for r in full_matrix_critical) + ")") if full_matrix_critical else ""
        f.append(Finding("A09", "ERROR", f"{ids} apply reduced release-branch CI to every PR; a branch trigger must never override the full-matrix requirement for critical PRs" + other, "testing_and_ci"))
    elif reduced_release_ci and not full_matrix_critical:
        ids = ", ".join(r.id or "?" for r in reduced_release_ci)
        f.append(Finding("A09", "ERROR", f"{ids} reduce CI on release branches but no rule requires a full-matrix run for critical PRs; branch triggers must not override critical PR rules", "testing_and_ci"))
    elif reduced_release_ci:
        ids = ", ".join(r.id or "?" for r in reduced_release_ci)
        f.append(Finding("A09", "INFO", f"{ids} reduce CI on release branches; confirm they explicitly exempt critical PRs into release branches", "testing_and_ci"))

    kb_critical = rules_matching(r"\bkb\b.*critical|critical.*\bkb\b|knowledge.base.*critical")
    kb_exempt = rules_matching(r"(decision.log|kb).*(exempt|self-merge|without (code )?review|no code review)")
    kb_all_review = rules_matching(r"(all|every) kb pr.*review")
    if kb_critical and not kb_exempt:
        f.append(Finding("A09", "WARN", "KB documents are marked critical but nothing exempts the routine decision-log batch PRs from code review; the KB thread cannot self-merge", "github_kb_and_release"))
    if kb_all_review and kb_exempt:
        f.append(Finding("A09", "ERROR", f"`{kb_all_review[0].id}` requires review of every KB PR while `{kb_exempt[0].id}` lets the KB thread self-merge", "github_kb_and_release"))

    atomic = rules_matching(r"atomic|finishes its current|next hand-?off|never mid")
    mid_step = [
        r for r in rules_matching(r"(immediately|mid-?step|mid-?review|mid-?commit|at once).*(replac|compress)|(replac|compress).*(immediately|mid-?step|mid-?review|mid-?commit|at once)")
        if r not in atomic
    ]
    if mid_step:
        ids = ", ".join(r.id or "?" for r in mid_step)
        other = (" (contradicts " + ", ".join(r.id or "?" for r in atomic) + ")") if atomic else ""
        f.append(Finding("A09", "ERROR", f"{ids} replace threads immediately on compression; a thread must finish its current atomic step (review round, fix commit, KB PR) and be replaced at the next hand-off" + other, "threads_and_watchdog"))

    round4_stop = rules_matching(r"round\s*\d+.*(hard stop|owner sign-?off|wait)|(hard stop|owner sign-?off).*round\s*\d+")
    bypass = rules_matching(r"(without|no) owner.*(critical|round\s*\d+)|(critical|round\s*\d+).*(without|no) owner")
    if round4_stop and bypass:
        f.append(Finding("A09", "ERROR", f"`{bypass[0].id}` lets the coordinator proceed without the owner where `{round4_stop[0].id}` demands owner sign-off", "autonomy"))
    critical_rounds = [r for r in rules if re.search(r"(?<!non-)\bcritical prs?\b[^.]*\bround", r.text, re.I)]
    if critical_rounds and not round4_stop:
        ids = ", ".join(r.id or "?" for r in critical_rounds)
        f.append(Finding("A09", "ERROR", f"{ids} cap the review rounds of critical PRs but no rule stops them for owner sign-off at the last round (invariant 5: a critical PR that has not converged waits for the owner, not for the coordinator)", "pull_requests_and_reviews"))
    # Judge the rule that sets the merge conditions itself; the same words in another rule do not bind the merge.
    merge_rules = [r for r in rules if re.search(r"squash-?merges? only|merges? only on", r.text, re.I)]
    setting = [r for r in merge_rules if (r.id or "").startswith("MRG-") or r.section == "pull_requests_and_reviews"] or merge_rules
    must_fix = r"no open (B/M|must-?fix)|zero (open )?(B/M|must-?fix)|without (an )?open (B/M|must-?fix)"
    if setting and not any(re.search(must_fix, r.text, re.I) for r in setting):
        f.append(Finding("A09", "WARN", f"`{setting[0].id}` sets the merge conditions but does not require that no must-fix finding is open", "pull_requests_and_reviews"))
    if rules_matching(r"\bcritical\b") and not rules_matching(r"\b(decides?|confirms?|classif(y|ies)|determines?)\b[^.]*\bcritical\b|\bcritical\b[^.]*\b(decides?|confirms?|classif(y|ies)|determines?)\b"):
        f.append(Finding("A09", "WARN", "rules treat critical PRs differently but no rule says who decides whether a PR is critical", "plans_and_criticality"))

    force_push_banned = rules_matching(r"never force-?push|no force-?push")
    force_push_allowed = rules_matching(r"(always|may|should) force-?push|force-?push to keep")
    if force_push_banned and force_push_allowed:
        f.append(Finding("A09", "ERROR", f"`{force_push_allowed[0].id}` allows force-push while `{force_push_banned[0].id}` forbids it", "pull_requests_and_reviews"))

    # --- A11 optional roles: defined when used, and kept inside their authority ---
    role_scopes = {s.strip() for r in rules if r.section == "roles" and r.applies_to for s in str(r.applies_to).split(",")}
    for scope in ("dispatcher", "specify", "assist", "advisor"):
        used = [r for r in rules if r.applies_to and scope in str(r.applies_to) and r.section != "roles"]
        if used and scope not in role_scopes:
            ids = ", ".join(r.id or "?" for r in used)
            f.append(Finding("A11", "WARN", f"{ids} bind a `{scope}` thread but no rule in `roles` defines that role", "roles"))
    def dispatcher_over_reach(text: str) -> bool:
        for sentence in re.split(r"(?<=[.;])\s+", text):
            if not re.search(r"\bdispatcher\b", sentence, re.I) or re.search(r"\bnever\b|\bnot\b", sentence, re.I):
                continue
            if not re.search(r"\b(may|can|grants?|approves?|decides?)\b", sentence, re.I):
                continue
            if re.search(r"(?<!non-)\bcritical\b|\bproduct scope\b|\bowner approval\b|\bacceptance contract\b", sentence, re.I) and not re.search(
                r"dispatcher for non-critical", sentence, re.I
            ):
                return True
        return False

    over_reach = [r for r in rules if dispatcher_over_reach(r.text)]
    if over_reach:
        ids = ", ".join(r.id or "?" for r in over_reach)
        f.append(Finding("A11", "ERROR", f"{ids} give the dispatcher authority over critical work, scope or owner approval; that stays with the coordinator and the owner", "roles"))
    owner_contract = rules_matching(r"owner-approved acceptance contract|owner[^.]*approv[^.]*acceptance contract")
    thread_contract = rules_matching(r"\b(coordinator|dispatcher|specify thread|review thread)\b[^.]*\b(may|can)\b[^.]*\b(approve|change|edit|amend)[^.]*acceptance contract")
    if thread_contract:
        other = f" (contradicts `{owner_contract[0].id}`)" if owner_contract else ""
        f.append(Finding("A11", "ERROR", f"`{thread_contract[0].id}` lets a thread approve or change an acceptance contract; only the owner approves, and a change is a new version" + other, "plans_and_criticality"))

    # --- A15 invariants that rest on prose alone ---
    prose_only = [r.id for r in rules if (r.id or "").startswith("INV-")
                  and not re.search(r"Enforced by:\s*(?!review only)\S|enforced automatically \(", r.text, re.I)]
    if prose_only:
        f.append(Finding("A15", "INFO", f"{', '.join(prose_only)} {'is' if len(prose_only) == 1 else 'are'} enforced by review only. An invariant holds reliably once a lint rule, test or CI check enforces it; name that check in the config (`[check: ...]`, `licence_check`, `telemetry_check`)", "hard_invariants_and_owner_prefs"))

    # --- A16 checks that were never seen to fail ---
    unproved = [r.id for r in rules if (r.id or "").startswith("INV-")
                and re.search(r"Enforced by:\s*(?!review only)\S", r.text, re.I) and not re.search(r"\(proved:", r.text, re.I)]
    if unproved:
        f.append(Finding("A16", "INFO", f"{', '.join(unproved)} name{'s' if len(unproved) == 1 else ''} a check that is not recorded as proved. "
                         "A check counts once it has failed on a case known to be wrong (VER-02); note where in the config, "
                         "e.g. `[check: ci:lint-imports (proved: PR #12)]`", "hard_invariants_and_owner_prefs"))

    # --- A12 per-role extracts in step with the ruleset ---
    if extracts:
        version, date = str(data.get("version", "")), str(data.get("date", ""))
        for name, text in sorted(extracts.items()):
            m_role = re.search(r"^extract_for:\s*(\S+)", text, re.M)
            role = m_role.group(1) if m_role else Path(name).stem
            m_v = re.search(r"^version:\s*(\S+)", text, re.M)
            m_d = re.search(r"^date:\s*(\S+)", text, re.M)
            if (m_v and m_v.group(1).strip("\"'") != version) or (m_d and m_d.group(1).strip("\"'") != date):
                f.append(Finding("A12", "WARN", f"extract `{name}` was generated from another ruleset version or date; regenerate so threads do not read stale rules", "extracts"))
                continue
            want = {r.id for r in rules if r.id and {x.strip() for x in str(r.applies_to or "").split(",")} & {role, "all"}}
            got = set(re.findall(r"^\s*-\s*id:\s*(\S+)", text, re.M))
            if want != got:
                diff = ", ".join(sorted(want ^ got))
                f.append(Finding("A12", "WARN", f"extract `{name}` does not hold the rules that bind a {role} thread (differs in: {diff}); it was edited by hand or is stale", "extracts"))
            texts = {r.id: r.text for r in rules if r.id}
            for rid, body in re.findall(r"^\s*-\s*id:\s*(\S+)\n\s*applies_to:.*\n\s*rule:\s*(.*)$", text, re.M):
                if rid in texts and unquote(body) != texts[rid]:
                    f.append(Finding("A12", "WARN", f"extract `{name}` words rule `{rid}` differently from the ruleset; the ruleset wins, regenerate the extract", "extracts"))
                    break

    # --- A10 state file cross-check ---
    if state_text is not None:
        if "active_now" not in state_text:
            f.append(Finding("A10", "WARN", "project-state.yaml has no `active_now` block", "state"))
        if re.search(r"^\s*-\s*id:\s*[A-Z]+-\d+", state_text, re.M):
            f.append(Finding("A10", "ERROR", "project-state.yaml contains rule entries; rules belong in claude-project-rules.yaml", "state"))
        rules_proj = str(data.get("project", "")).strip()
        m = re.search(r"^project:\s*(.+)$", state_text, re.M)
        if rules_proj and m and unquote(strip_comment(m.group(1))) != rules_proj:
            f.append(Finding("A10", "WARN", f"state file project `{unquote(strip_comment(m.group(1)))}` differs from rules project `{rules_proj}`", "state"))

    return f


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

SEV_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}


def render_markdown(path: Path, findings: list[Finding], n_rules: int) -> str:
    counts = {s: sum(1 for x in findings if x.severity == s) for s in SEV_ORDER}
    lines = [
        f"# Ruleset audit: {path.name}",
        "",
        f"Rules found: {n_rules}. Findings: {counts['ERROR']} error, {counts['WARN']} warn, {counts['INFO']} info.",
        "",
    ]
    if not findings:
        lines.append("No mechanical findings. Continue with the semantic checklist.")
        return "\n".join(lines) + "\n"
    for sev in SEV_ORDER:
        group = [x for x in findings if x.severity == sev]
        if not group:
            continue
        lines.append(f"## {sev}")
        for x in group:
            where = f" ({x.where})" if x.where else ""
            lines.append(f"- **{x.code}** {x.message}{where}")
        lines.append("")
    lines.append("Codes: A01 header, A02 ids, A03 scopes, A04 lanes/labels, A05 execution profile, "
                 "A06 state leakage, A07 dead history, A08 token bloat, A09 contradiction patterns, A10 state file, "
                 "A11 optional roles, A12 per-role extracts, A13 authority order, A14 comparison with the default branch, "
                 "A15 invariants without a check, A16 checks never seen to fail, A17 per-PR work on the coordinator's model.")
    return "\n".join(lines) + "\n"


def git_checks(rules_path: Path, data: dict[str, Any]) -> list[Finding]:
    """A14: in a repository, the ruleset, its config, the extracts and the roadmap must equal their copies on the
    default branch. Threads read them on a branch any of them can write, so the working copy proves nothing."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import contract_tool as ct  # type: ignore
    except ImportError:
        return []
    prof = data.get("project_profile") if isinstance(data.get("project_profile"), dict) else {}
    in_repo = str(prof.get("environment", "")) == "claude_code"
    workspace = rules_path.resolve().parent
    ref, trust = ct.trusted_ref(workspace, str(prof.get("default_branch") or ""), in_repo)
    # Outside git the audit has nothing to compare with; it says so for an in-repo workspace and is silent otherwise.
    out = [Finding("A14", "INFO" if "not a git checkout" in f.message else f.severity, f.message, "default branch")
           for f in trust if f.severity != "INFO" or "no remote" in f.message]
    out += [Finding("A14", f.severity, f.message, "default branch") for f in ct.protected_findings(workspace, ref, "A14")]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Mechanical audit of claude-project-rules.yaml")
    ap.add_argument("rules", type=Path, help="path to claude-project-rules.yaml")
    ap.add_argument("--state", type=Path, help="path to project-state.yaml for cross-checks")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON instead of markdown")
    ap.add_argument("--strict", action="store_true", help="exit 1 on WARN as well as ERROR")
    ap.add_argument("--no-git", action="store_true", help="do not compare the ruleset, config, extracts and roadmap with the default branch")
    ap.add_argument("--extracts", type=Path, help="directory with the per-role extracts (default: `rules/` next to the ruleset, if it exists)")
    args = ap.parse_args()

    if not args.rules.is_file():
        print(f"error: {args.rules} not found", file=sys.stderr)
        return 2
    raw_text = args.rules.read_text(encoding="utf-8")
    data = load_yaml_or_none(args.rules)
    if data is None:
        data, rules = fallback_parse(raw_text)
    else:
        rules = rules_from_data(data, raw_text)
    state_text = args.state.read_text(encoding="utf-8") if args.state and args.state.is_file() else None
    if args.state and state_text is None:
        print(f"warning: state file {args.state} not found; skipping cross-checks", file=sys.stderr)

    extract_dir = args.extracts or args.rules.parent / "rules"
    extracts = {p.name: p.read_text(encoding="utf-8") for p in sorted(extract_dir.glob("*.yaml"))} if extract_dir.is_dir() else None
    if args.extracts and extracts is None:
        print(f"warning: extract directory {args.extracts} not found; skipping that check", file=sys.stderr)

    findings = run_checks(data, rules, raw_text, state_text, extracts)
    if not args.no_git:
        findings += git_checks(args.rules, data)
    findings.sort(key=lambda x: (SEV_ORDER[x.severity], x.code))

    if args.json:
        print(json.dumps({"file": str(args.rules), "rules": len(rules), "findings": [asdict(x) for x in findings]}, indent=2))
    else:
        print(render_markdown(args.rules, findings, len(rules)), end="")

    has_error = any(x.severity == "ERROR" for x in findings)
    has_warn = any(x.severity == "WARN" for x in findings)
    return 1 if has_error or (args.strict and has_warn) else 0


if __name__ == "__main__":
    sys.exit(main())
