"""The advisor role, governance_paths and the promised-tests sentence of PLAN-01."""

from __future__ import annotations

import json

import pytest
import yaml

from conftest import SKILL, findings, notable, run


def ids(w, role):
    p = w.ws / "rules" / f"{role}.yaml"
    return {r["id"] for r in yaml.safe_load(p.read_text())["rules"]} if p.exists() else set()


def profile(w):
    return yaml.safe_load(w.rules_text())


# ---- advisor -------------------------------------------------------------------------------------------

def test_no_advisor_by_default(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    text = w.rules_text()
    assert "ROLE-18" not in text and "advisor" not in profile(w)["execution_profile"]["model_routing"]
    assert not (w.ws / "rules" / "advisor.yaml").exists() and not (w.ws / "advisor_instructions.md").exists()


def test_advisor_rule_extract_routing_and_template(w):
    assert w.generate(None, "advisor=true", "coordinator_model=Opus 5.5 high", "critical_model=Fable 5.1").returncode == 0
    rule = w.rule("ROLE-18")
    for phrase in ("fresh, read-only session on the advisor model", "only about a decision it would otherwise put to the owner",
                   "a real open choice in a critical plan", "the question, the options and the evidence",
                   "one recommendation and its reasons", "decides nothing", "kb/pending-decisions.md"):
        assert phrase in rule, phrase
    assert len(rule) <= 450
    assert profile(w)["execution_profile"]["model_routing"]["advisor"] == "Fable 5.1"  # defaults to the critical-work model
    assert "ROLE-18" in ids(w, "coordinator") and "ROLE-18" in ids(w, "advisor") and "ROLE-18" not in ids(w, "implementation")
    extract = yaml.safe_load((w.ws / "rules" / "advisor.yaml").read_text())
    assert "the brief the coordinator gives you" in extract["start_reading"] and "thread chats" in extract["leave_unread"]
    assert len(extract["rules"]) <= 15  # an advisor carries few rules
    assert not notable(w.audit("--json"))
    assert w.scaffold().returncode == 0
    tmpl = (w.ws / "advisor_instructions.md").read_text()
    for phrase in ("fresh, read-only session on Fable 5.1", "Question:", "Options:", "Evidence:", "Recommendation:",
                   "What would change my mind:", "decides\n   nothing", "kb/pending-decisions.md", "`ROLE-18`"):
        assert phrase in tmpl, phrase
    assert "{{" not in tmpl


def test_advisor_model_can_be_set_and_survives_the_round_trip(w, tmp_path):
    assert w.generate(None, "advisor=true", "advisor_model=Fable 5.2", "coordinator_model=Opus 5.5").returncode == 0
    assert profile(w)["execution_profile"]["model_routing"]["advisor"] == "Fable 5.2"
    out = tmp_path / "back.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    back = json.loads(out.read_text())
    assert back["advisor"] is True and back["advisor_model"] == "Fable 5.2"
    before = w.rules_text()
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.rules_text() == before


@pytest.mark.parametrize("sets, word", [
    (("advisor=true", "coordinator_model=Opus 5.5", "advisor_model=Opus 5.5"), "advisor_model is the coordinator's model"),
    (("advisor=yes",), "advisor must be true or false"),
])
def test_bad_advisor_settings_are_refused(w, sets, word):
    r = w.generate(None, *sets)
    assert r.returncode == 2 and word in r.stderr


def test_audit_knows_the_advisor_scope(w):
    assert w.generate(None, "advisor=true", "coordinator_model=Opus 5.5").returncode == 0
    assert not [f for f in findings(w.audit("--json")) if f["code"] in ("A03", "A11")]
    # a rule that binds the advisor without the role being defined is reported
    text = w.rules_text().replace("applies_to: coordinator,advisor", "applies_to: coordinator")
    text = text.replace('  - id: PREF-01\n    applies_to: all', '  - id: PREF-01\n    applies_to: advisor', 1)
    w.rules.write_text(text)
    assert any(f["code"] == "A11" and "advisor" in f["message"] for f in findings(w.audit("--json")))


@pytest.mark.parametrize("sets", [("advisor=true", "dispatcher=true", "workspace_root=./governance"),
                                  ("advisor=true", "dispatcher=false", "token_cfg.max_concurrent_lanes=2")])
def test_coordinator_load_with_the_advisor(w, sets):
    assert w.generate(None, "coordinator_model=Opus 5.5", *sets).returncode == 0
    assert len(yaml.safe_load((w.ws / "rules" / "coordinator.yaml").read_text())["rules"]) <= 40
    assert not [f for f in findings(w.audit("--json")) if f["code"] == "A08"]


# ---- governance_paths ----------------------------------------------------------------------------------

GOV = '["governance/kb/**","governance/plans/**","governance/ledger/**","governance/project-state.yaml"]'


def test_governance_paths_are_kept_and_reach_the_pr_checks(w, tmp_path):
    assert w.generate(None, "workspace_root=./governance", f"governance_paths={GOV}").returncode == 0
    assert profile(w)["project_profile"]["governance_paths"] == json.loads(GOV)
    assert w.scaffold("--github").returncode == 0
    assert json.loads((w.ws / "github-setup" / "pr-checks.json").read_text())["governance_paths"] == json.loads(GOV)
    out = tmp_path / "back.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert json.loads(out.read_text())["governance_paths"] == json.loads(GOV)
    # without the setting the whole workspace counts, as before
    assert w.generate(None, "workspace_root=./governance", "governance_paths=[]").returncode == 0 and w.scaffold("--github", "--force").returncode == 0
    assert "governance_paths" not in profile(w)["project_profile"]
    assert json.loads((w.ws / "github-setup" / "pr-checks.json").read_text())["governance_paths"] == ["governance/**"]


def test_a_config_with_governance_paths_is_no_longer_unknown(w):
    cfg_path = w.ws / "governance-config.json"
    assert w.generate(None, "workspace_root=./governance").returncode == 0
    cfg = json.loads(cfg_path.read_text())
    cfg["governance_paths"] = json.loads(GOV)
    cfg_path.write_text(json.dumps(cfg))
    r = run("generate_project_rules.py", "--from-json", cfg_path, "--out-dir", w.ws)
    assert r.returncode == 0 and "unknown config key" not in r.stdout + r.stderr


@pytest.mark.parametrize("value", ['["/governance/**"]', '["../x/**"]', '["**"]', '"governance/**"'])
def test_bad_governance_paths_are_refused(w, value):
    r = w.generate(None, "workspace_root=./governance", f"governance_paths={value}")
    assert r.returncode == 2 and "governance_paths" in r.stderr


# ---- promised tests ------------------------------------------------------------------------------------

def test_promised_tests_sentence_only_when_a_check_is_named(w, tmp_path):
    assert w.generate().returncode == 0
    assert "Tests promised in the plan" not in w.rule("PLAN-01")
    assert w.generate(None, "promised_tests_check=the governance check").returncode == 0
    plan = w.rule("PLAN-01")
    for phrase in ("names every test it promises by its test ID", "'## Tests promised in the plan'",
                   "the governance check fails the PR when a listed test does not exist", "requires a new coordinator D-number"):
        assert phrase in plan, phrase
    assert len(plan) <= 450
    out = tmp_path / "back.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert json.loads(out.read_text())["promised_tests_check"] == "the governance check"


def test_docs_describe_all_three():
    model = (SKILL / "references" / "governance-model.md").read_text()
    assert "| **advisor** (default off) |" in model and "Planner and router on different models" in model
    init = (SKILL / "init.md").read_text()
    for phrase in ("offer the\n   advisor", "`governance_paths` narrows that", "`promised_tests_check`"):
        assert phrase in init, phrase
