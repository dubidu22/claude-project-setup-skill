"""Keeping per-PR traffic away from the coordinator: few wake-up events, no hands-on work, the merging thread
watches the default branch, a short status instead of a list in chat, and an audit warning when the dispatcher
is off."""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from conftest import findings, notable


def ids(w, role):
    return {r["id"] for r in yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())["rules"]}


def a17(w):
    return [(f["severity"], f["message"]) for f in findings(w.audit("--json")) if f["code"] == "A17"]


# ---- rules -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("disp", ["true", "false"])
def test_event_rule_and_no_hands_on_work(w, disp):
    assert w.generate(None, f"dispatcher={disp}").returncode == 0
    r17 = w.rule("ROLE-17")
    for phrase in ("Act on few events", "a plan or contract to approve", "a verdict or gate that needs you", "a blocked or question hand-back",
                   "the owner's messages", "Everything else ends in the thread it belongs to", "PRs by number only, never their titles",
                   "no list of what is pending", "ledger_tool.py status"):
        assert phrase in r17, phrase
    assert ("the batch report" in r17) is (disp == "true") and ("the end of a batch" in r17) is (disp == "false")
    r05 = w.rule("ROLE-05")
    for phrase in ("writes no product code", "no hands-on work", "CI and merge watches", "starting or stopping the app", "cleanups go to",
                   "never with a shell heredoc or echo"):
        assert phrase in r05, phrase
    assert ("the dispatcher or a worker thread" in r05) is (disp == "true")
    r07 = w.rule("ROLE-07")
    assert "After a merge it watches the run on main for the merge commit and records the result in the round entry" in r07
    for rid in ("ROLE-05", "ROLE-07", "ROLE-17"):
        assert len(w.rule(rid)) <= 450
    assert {"ROLE-05", "ROLE-17"} <= ids(w, "coordinator") and "ROLE-17" not in ids(w, "implementation")
    assert "ROLE-07" in ids(w, "review")


@pytest.mark.parametrize("sets", [("dispatcher=false", "workspace_root=./governance"), ("dispatcher=false",), ("dispatcher=true", "workspace_root=./governance")])
def test_coordinator_stays_within_its_rule_load(w, sets):
    assert w.generate(None, *sets).returncode == 0
    assert len(yaml.safe_load((w.ws / "rules" / "coordinator.yaml").read_text())["rules"]) <= 40
    assert not [f for f in findings(w.audit("--json")) if f["code"] == "A08" and "coordinator" in f["message"]]


def test_templates_carry_the_reporting_rules(w):
    for disp, event in (("true", "the Dispatcher's batch report"), ("false", "the end of a batch")):
        assert w.generate(None, f"dispatcher={disp}").returncode == 0 and w.scaffold("--refresh").returncode == 0
        text = (w.ws / "project_instructions.md").read_text()
        for phrase in ("the number of turns\n  matters more than their length", "Act only on the events in `ROLE-17`", event,
                       "a background command you start reports back to you", "never with a\n  shell heredoc",
                       "PRs by number (`#712`), never with their\n  titles", "ledger_tool.py status"):
            assert phrase in text, (disp, phrase)
        assert "{{" not in text
    assert w.generate(None, "dispatcher=true").returncode == 0 and w.scaffold("--refresh").returncode == 0
    dispatcher = (w.ws / "dispatcher_instructions.md").read_text()
    assert "per-PR traffic never reaches the Coordinator" in dispatcher and "once per batch" in dispatcher


# ---- the audit warning ---------------------------------------------------------------------------------

def test_no_dispatcher_with_several_lanes_is_warned(w):
    assert w.generate(None, "dispatcher=false", "coordinator_model=Fable 5.1", "ops_model=Sonnet 5.5").returncode == 0
    found = a17(w)
    assert [s for s, _ in found] == ["WARN"]
    msg = found[0][1]
    assert "no dispatcher while up to 3 lanes run at once" in msg and "Fable 5.1" in msg and "dispatcher=true" in msg
    for lanes in (1, 2):  # one or two lanes: a small project may run without a dispatcher (init.md)
        assert w.generate(None, "dispatcher=false", f"token_cfg.max_concurrent_lanes={lanes}", "ops_model=Sonnet 5.5").returncode == 0
        assert not a17(w), lanes
    assert w.generate(None, "dispatcher=true", "ops_model=Sonnet 5.5").returncode == 0
    assert not a17(w)


@pytest.mark.parametrize("coord, ops, note", [
    ("Fable 5.1", "Opus 5.5 medium", "top tier"),
    ("Opus 5.5", "Opus 5.5 medium", "the same tier as the coordinator"),
    ("Sonnet 5.5", "Sonnet 5.5", "the same tier as the coordinator"),
    ("Fable 5.1", "Sonnet 5.5", None),
    ("Fable 5.1", "Haiku 5.5", None),
    ("my-model", "other-model", None),
])
def test_operations_tier_note(w, coord, ops, note):
    assert w.generate(None, "dispatcher=true", f"coordinator_model={coord}", f"ops_model={ops}").returncode == 0
    found = a17(w)
    if note is None:
        assert not found
    else:
        assert len(found) == 1 and found[0][0] == "INFO" and note in found[0][1] and ops in found[0][1]


def test_the_projects_own_settings_get_both_messages(w):
    """The settings of the project the excerpt came from: no dispatcher, Fable coordinator, Opus operations."""
    assert w.generate(None, "dispatcher=false", "coordinator_model=Fable 5.1", "ops_model=Opus 5.5 medium").returncode == 0
    assert [s for s, _ in a17(w)] == ["WARN", "INFO"]
    assert not [f for f in notable(w.audit("--json")) if f["code"] not in ("A17",)]


# ---- ledger_tool.py status -------------------------------------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def put(w, sub, name, body):
    folder = w.ws / "ledger" / sub
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(body)


def pr(n, extra=""):
    return f'pr: {n}\nopened: 2026-01-31\nthread: impl-{n}\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n{extra}'


def rnd(n, k, must, verdict, merged="", should=0):
    crit = "critical: no\n" if k == 1 else ""
    return (f"pr: {n}\nround: {k}\ndate: 2026-02-0{k}\nthread: review-1\nhead: 3f9c2a{k}\n{crit}verdict: {verdict}\nmust_fix: {must}\n"
            f'should_fix: {should}\nkinds: ""\nreport: plans/review-pr{n}-round{k}.md\nmerged: "{merged}"\n')


def test_status_is_short_and_uses_numbers_only(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    (w.ws / "ledger" / "deferred" / "since.txt").write_text("# test\n2026-01-01\n")
    assert ledger(w, "status").stdout == "Open PRs: 0.\nLeftovers without a decision: 0.\n"
    put(w, "prs", "pr-712", pr(712))
    put(w, "rounds", "pr712-round1", rnd(712, 1, 1, "changes_requested"))
    put(w, "rounds", "pr712-round2", rnd(712, 2, 0, "approved"))
    put(w, "prs", "pr-715", pr(715))
    put(w, "rounds", "pr715-round1", rnd(715, 1, 2, "changes_requested"))
    put(w, "prs", "pr-716", pr(716, 'handback: question\nrecommended: "Cut release/1.4 from the v1.4.0 tag"\n'))
    put(w, "prs", "pr-717", pr(717))
    put(w, "prs", "pr-713", pr(713))
    put(w, "rounds", "pr713-round1", rnd(713, 1, 0, "approved", merged="9ad6d11", should=1))
    r = ledger(w, "status")
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Open PRs: 4:",
        "  #712  round 2 approved, gate passes  [next: merge]",
        "  #715  round 1 changes_requested, 2 must-fix  [next: impl-715]",
        "  #716  question: Cut release/1.4 from the v1.4.0 tag  [next: coordinator]",
        "  #717  in work, no review round yet  [next: impl-717]",
        "Leftovers without a decision: 1 (ledger_tool.py triage).",
    ]


def test_status_names_a_stopped_gate(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    put(w, "prs", "pr-720", pr(720))
    put(w, "rounds", "pr720-round1", rnd(720, 1, 0, "approved").replace("critical: no\n", ""))  # round 1 must say whether it is critical
    line = ledger(w, "status").stdout.splitlines()[1]
    assert line.startswith("  #720  round 1 approved, gate stops") and line.endswith("[next: coordinator]")


def test_reference_explains_where_the_tokens_go():
    from conftest import SKILL
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Where a coordinator's tokens go", "each extra turn costs more than the one before", "`ROLE-17`", "(A17)"):
        assert phrase in model, phrase
    init = (SKILL / "init.md").read_text()
    assert "The audit warns about this (A17)" in init and "start the coordinator fresh" in init
    assert "| Coordinator load |" in (SKILL / "references" / "audit-checklist.md").read_text()
