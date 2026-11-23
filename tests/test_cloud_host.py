"""Claude Code on the owner's computer or in the cloud: what init asks, what the rules say, what the scaffold writes."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

from conftest import SKILL, notable, run


def profile(w):
    return yaml.safe_load(w.rules_text())["project_profile"]


def ids(w, role):
    return {r["id"] for r in yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())["rules"]}


def test_local_is_the_default_and_keeps_the_local_questions(w):
    assert w.generate(None, "workspace_root=./governance").returncode == 0
    prof = profile(w)
    assert prof["claude_code_host"] == "local" and "local_clone_path" in prof and "local_environment" in prof
    assert "THR-17" not in w.rules_text()
    assert w.scaffold().returncode == 0 and not (w.ws / "cloud_environment.md").exists()


def test_a_claude_ai_project_has_no_host(w):
    assert w.generate().returncode == 0
    assert "claude_code_host" not in profile(w) and "local_clone_path" in profile(w)
    r = w.generate(None, "claude_code_host=cloud")
    assert r.returncode == 2 and "claude_code_host=cloud needs the workspace in the repository" in r.stderr


def test_cloud_rule_profile_and_template(w):
    assert w.generate(None, "workspace_root=./governance", "claude_code_host=cloud").returncode == 0
    prof = profile(w)
    assert prof["claude_code_host"] == "cloud" and "local_clone_path" not in prof and "local_environment" not in prof
    rule = w.rule("THR-17")
    for phrase in ("Sessions run in the cloud", "nothing runs on the owner's computer", "desktop app, a display or local hardware",
                   "runs in CI or becomes an owner hand step", "never reported as run", "setup script", "not installed around"):
        assert phrase in rule, phrase
    assert len(rule) <= 450
    assert "THR-17" in ids(w, "implementation") and "THR-17" in ids(w, "review") and "THR-17" not in ids(w, "coordinator")
    assert not [f for f in notable(w.audit("--json")) if f["code"] != "A14"]
    assert w.scaffold().returncode == 0
    text = (w.ws / "cloud_environment.md").read_text()
    for phrase in ("claude.ai/code", "Connect GitHub", "setup script", "cached", "Network access", "No secrets in the repository",
                   "Run the desktop app", "(`THR-17`)", "keep running when the browser is closed", "clones the repository"):
        assert phrase in text, phrase
    assert "{{" not in text


def test_round_trip_and_switching_back(w, tmp_path):
    assert w.generate(None, "workspace_root=./governance", "claude_code_host=cloud").returncode == 0
    out = tmp_path / "back.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert json.loads(out.read_text())["claude_code_host"] == "cloud"
    before = w.rules_text()
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.rules_text() == before
    assert w.generate(None, "claude_code_host=local").returncode == 0
    assert "THR-17" not in w.rules_text() and profile(w)["claude_code_host"] == "local"


@pytest.mark.parametrize("value", ["remote", "Cloud", ""])
def test_unknown_hosts_are_refused(w, value):
    r = w.generate(None, "workspace_root=./governance", f"claude_code_host={value}")
    assert r.returncode == 2 and "claude_code_host" in r.stderr


def test_wizard_asks_the_host_only_for_a_repository_workspace(tmp_path):
    script = str(SKILL / "scripts" / "generate_project_rules.py")
    base = ["demo", "o/demo", "", "", "", "", "", ""]  # name, repo, public, owner, handle, timezone, shell, clone path
    answers = "\n".join(base + ["./governance", "cloud"]) + "\n" + "\n" * 80
    r = subprocess.run([sys.executable, script, "--out-dir", str(tmp_path / "o")], input=answers, capture_output=True, text=True)
    assert "Where do the Claude Code sessions run" in r.stdout and "Traceback" not in r.stderr
    answers = "\n".join(base + [""]) + "\n" + "\n" * 80
    r = subprocess.run([sys.executable, script, "--out-dir", str(tmp_path / "p")], input=answers, capture_output=True, text=True)
    assert "Where do the Claude Code sessions run" not in r.stdout and "Traceback" not in r.stderr


def test_docs_describe_the_choice():
    init = (SKILL / "init.md").read_text()
    assert "(`claude_code_host`): `local`" in init and "skip the local OS, shell and clone-path" in init
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Claude Code on the owner's computer or in the cloud", "| Tokens per turn | same | same |",
                   "A claude.ai Project costs more\nper piece of work than either"):
        assert phrase in model, phrase
