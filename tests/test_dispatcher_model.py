"""The dispatcher runs on the strongest model it starts: a session starts sessions only on its own model or a cheaper one."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

from conftest import SKILL, findings, notable, run

sys.path.insert(0, str(SKILL / "scripts"))
import generate_project_rules as gen  # noqa: E402

PROJECT = ("coordinator_model=Opus 5.5 high", "specify_model=Opus 5.5 high", "critical_model=Opus 5.5 high",
           "implementation_model=Opus 5.5 high", "review_model=Opus 5.5 medium", "ops_model=Sonnet 5.5 high")


def routing(w):
    return yaml.safe_load(w.rules_text())["execution_profile"]["model_routing"]


def a18(w):
    return [f["message"] for f in findings(w.audit("--json")) if f["code"] == "A18"]


def test_dispatcher_takes_the_strongest_worker_model(w):
    assert w.generate(None, "dispatcher=true", *PROJECT).returncode == 0
    r = routing(w)
    assert r["dispatcher"] == "Opus 5.5 high" and r["operations"] == "Sonnet 5.5 high"
    assert not a18(w) and not notable(w.audit("--json"))
    assert w.scaffold("--refresh").returncode == 0
    text = (w.ws / "dispatcher_instructions.md").read_text()
    assert "You run on Opus 5.5 high, the strongest model\namong the threads you start" in text and "Sonnet" not in text
    assert "do not\nwork around it: post the starter block" in text


@pytest.mark.parametrize("models, want", [
    ({"critical_model": "Opus (high effort)", "implementation_model": "Sonnet (high effort)", "review_model": "Sonnet"}, "Opus (high effort)"),
    ({"critical_model": "Opus", "implementation_model": "Fable 5.1", "review_model": "Opus"}, "Fable 5.1"),
    ({"critical_model": "Opus 5.5 high", "implementation_model": "Opus 5.5 medium", "review_model": "Opus 5.5 low"}, "Opus 5.5 high"),
    ({"critical_model": "house-model-a", "implementation_model": "house-model-b", "review_model": "house-model-c"}, "house-model-a"),
])
def test_default_dispatcher_model(models, want):
    assert gen.dispatcher_model({"dispatcher_model": "", **models}) == want


def test_no_dispatcher_line_without_a_dispatcher(w):
    assert w.generate(None, "dispatcher=false", "token_cfg.max_concurrent_lanes=2").returncode == 0
    assert "dispatcher" not in routing(w)


def test_a_stronger_dispatcher_may_be_named_a_weaker_one_is_refused(w, tmp_path):
    assert w.generate(None, "dispatcher=true", *PROJECT, "dispatcher_model=Fable 5.1").returncode == 0
    assert routing(w)["dispatcher"] == "Fable 5.1"
    out = tmp_path / "back.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert json.loads(out.read_text())["dispatcher_model"] == "Fable 5.1"
    r = w.generate(None, "dispatcher=true", *PROJECT, "dispatcher_model=Sonnet 5.5 high")
    assert r.returncode == 2 and "dispatcher_model 'Sonnet 5.5 high' is weaker than Opus 5.5 high, Opus 5.5 medium" in r.stderr
    assert "only on its own model or a cheaper one" in r.stderr


def test_audit_flags_an_older_ruleset_whose_dispatcher_is_on_the_operations_slot(w):
    assert w.generate(None, "dispatcher=true", *PROJECT).returncode == 0
    text = w.rules_text()
    w.rules.write_text(text.replace('    dispatcher: "Opus 5.5 high"\n', ""))  # what a ruleset before this change looks like
    msgs = a18(w)
    assert len(msgs) == 1
    assert "runs on Sonnet 5.5 high (the operations slot, since the ruleset names no dispatcher model)" in msgs[0]
    assert "Opus 5.5 high, Opus 5.5 medium" in msgs[0] and "Regenerate" in msgs[0]
    # a named dispatcher model that is weaker is flagged too
    w.rules.write_text(text.replace('    dispatcher: "Opus 5.5 high"', '    dispatcher: "Haiku 5.5"'))
    assert "runs on Haiku 5.5 (its own slot)" in a18(w)[0]
    # without a dispatcher there is nothing to start
    assert w.generate(None, "dispatcher=false", "token_cfg.max_concurrent_lanes=2", *PROJECT).returncode == 0
    assert not a18(w)


def test_operations_note_speaks_of_assist_only(w):
    assert w.generate(None, "dispatcher=true", "coordinator_model=Fable 5.1", "ops_model=Opus 5.5 medium").returncode == 0
    notes = [f["message"] for f in findings(w.audit("--json")) if f["code"] == "A17"]
    assert len(notes) == 1 and "only assist threads" in notes[0] and "dispatcher" not in notes[0]


# ---- the fixed decision for leftovers -----------------------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def test_a_leftover_fixed_before_the_merge_is_settled_by_its_commit(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    (w.ws / "ledger" / "deferred" / "since.txt").write_text("# test\n2026-01-01\n")
    folder = w.ws / "ledger" / "deferred"
    (folder / "pr715-1.yaml").write_text('pr: 715\ndate: 2026-11-22\nwhat: "S1: an object in a reference cycle is freed in the job thread"\n'
                                         "decision: fixed\ncommit: 266f10f\n")
    r = ledger(w, "triage")
    assert r.returncode == 0 and "fixed in 266f10f" in r.stdout
    (folder / "pr715-1.yaml").write_text('pr: 715\ndate: 2026-11-22\nwhat: "S1: freed in the job thread"\ndecision: fixed\ncommit: later\n')
    r = ledger(w, "triage")
    assert r.returncode == 1 and "a fixed item names the `commit`" in r.stdout
    assert ledger(w, "check").returncode == 1
    assert "fixed (the commit)" in w.rule("THR-16") and len(w.rule("THR-16")) <= 450
    readme = (w.ws / "ledger" / "README.md").read_text()
    assert "open | fixed | planned | postponed | dropped" in readme and "commit:" in readme


def test_docs_explain_why():
    model = (SKILL / "references" / "governance-model.md").read_text()
    assert "a\nSonnet dispatcher could not start Opus workers" in model and "(A18)" in model
    assert "| `operations` | assist |" in model
    init = (SKILL / "init.md").read_text()
    assert "only on its own model or a cheaper one" in init and "`dispatcher_model`" in init
    assert "A18 a dispatcher that cannot start its workers" in (SKILL / "scripts" / "audit_rules.py").read_text()
