"""audit_rules.py: what it must flag, and that it reads the same without PyYAML."""
from __future__ import annotations

import json

import pytest

from conftest import EVALS, errors, findings, run

PLANTED = EVALS / "audit-planted-contradictions" / "files" / "governance"


def codes(result, severity=None):
    return {(f["code"], f["message"]) for f in findings(result) if severity in (None, f["severity"])}


def has(result, code, needle):
    return any(c == code and needle in m for c, m in codes(result))


def edit(w, old, new):
    text = w.rules_text()
    assert old in text, old
    w.rules.write_text(text.replace(old, new))


@pytest.mark.parametrize("no_yaml", [False, True])
def test_planted_contradictions_are_found(no_yaml):
    r = run("audit_rules.py", PLANTED / "claude-project-rules.yaml", "--state", PLANTED / "project-state.yaml", "--json", no_yaml=no_yaml)
    assert r.returncode == 1
    for code, needle in [
        ("A02", "duplicate rule id `LANE-02`"), ("A03", "`LANE-04` has no `applies_to`"), ("A04", "lane:infra"),
        ("A05", "critical_max_review_rounds=6"), ("A06", "active_now"), ("A07", "commands_history"),
        ("A09", "reduced release-branch CI"), ("A09", "KB-02"), ("A09", "immediately on compression"),
        ("A09", "without the owner"), ("A13", "ranks the decision log above the owner"),
    ]:
        assert has(r, code, needle), (code, needle)


def test_non_numeric_token_value_is_an_error(w):
    w.generate()
    edit(w, "max_concurrent_lanes: 3", "max_concurrent_lanes: many")
    assert has(w.audit("--json"), "A05", "max_concurrent_lanes must be a whole number")
    assert has(w.audit("--json", no_yaml=True), "A05", "max_concurrent_lanes must be a whole number")


def test_missing_hard_stop_is_an_error(w):
    w.generate()
    edit(w, "then hit a hard stop requiring owner sign-off", "then go to coordinator escalation")
    r = w.audit("--json")
    assert r.returncode == 1 and has(r, "A09", "no rule stops them for owner sign-off")


def test_round_named_in_a_rule_must_match_the_config(w):
    w.generate()
    edit(w, "critical_max_review_rounds: 4", "critical_max_review_rounds: 3")
    assert has(w.audit("--json"), "A05", "hard-code a round-4 stop")


def test_merge_without_must_fix_condition_and_undecided_criticality_are_flagged(w):
    w.generate()
    edit(w, "with no open B/M finding in the latest round report and required CI green", "with required CI green")
    edit(w, "with green CI and no open must-fix finding", "with green CI")
    assert has(w.audit("--json"), "A09", "nothing requires that no must-fix finding is open")
    w.generate(None, "dispatcher=true")
    text = w.rules_text()
    start = text.index("  - id: CRIT-03")
    w.rules.write_text(text[:start] + text[text.index("\n\n", start) + 1:])
    assert has(w.audit("--json", "--extracts", w.tmp / "none"), "A09", "who decides whether a PR is critical")


def test_authority_order_checks(w):
    w.generate()
    edit(w, "  - this_ruleset           # and the project instructions generated from it\n", "")
    assert has(w.audit("--json"), "A13", "does not list the ruleset")


def test_stale_or_edited_extract_is_flagged(w):
    w.generate()
    kb = w.ws / "rules" / "kb.yaml"
    original = kb.read_text()
    kb.write_text(original.replace("version: 2.0.0", "version: 1.9.0"))
    assert has(w.audit("--json"), "A12", "another ruleset version")
    kb.write_text(original.replace("self-merges without code review", "self-merges after review"))
    assert has(w.audit("--json"), "A12", "words rule `ROLE-08` differently")
    start = original.index("  - id: ROLE-08")
    kb.write_text(original[:start] + original[original.index("  - id:", start + 5):])
    assert has(w.audit("--json"), "A12", "does not hold the rules that bind a kb thread")
    kb.write_text(original)
    assert not [c for c, _ in codes(w.audit("--json")) if c == "A12"]


def test_rule_load_is_counted_per_role_so_custom_invariants_have_room(w):
    many = json.dumps([f"Invariant number {i} holds." for i in range(8)])
    w.generate(None, f"custom_invariants={many}", "workspace_root=./governance")
    assert not [m for c, m in codes(w.audit("--json")) if c == "A08" and "bound by" in m]
    many = json.dumps([f"Invariant number {i} holds." for i in range(20)])
    w.generate(None, f"custom_invariants={many}")
    assert has(w.audit("--json"), "A08", "implementation thread is bound by")


def test_fallback_reader_keeps_hash_signs_inside_quotes(w):
    w.generate()
    with_yaml = json.loads(w.audit("--json").stdout)
    without = json.loads(w.audit("--json", no_yaml=True).stdout)
    assert with_yaml == without
    import audit_rules

    _, rules = audit_rules.fallback_parse(w.rules_text())
    pr01 = next(r for r in rules if r.id == "PR-01")
    assert pr01.text.endswith("never in branch commit messages.") and "(#N)" in pr01.text
    assert audit_rules.strip_comment('a: "x # y"  # tail') == 'a: "x # y"'
    assert audit_rules.split_inline('"a, b", c, \'d,e\'') == ['"a, b"', "c", "'d,e'"]
