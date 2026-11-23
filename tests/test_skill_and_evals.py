"""The skill's own files: metadata, references between files, and the eval fixtures built at test time."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

import contract_tool as ct
import generate_project_rules as gen
from conftest import EVALS, ROOT, SKILL, errors, findings, run

CASES = sorted(p for p in EVALS.iterdir() if p.is_dir())
GENERATED = [c for c in CASES if (c / "files" / "governance" / "fixture-config.json").exists()]


def test_skill_metadata():
    text = (SKILL / "SKILL.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == "project-governance-init"
    desc = " ".join(front["description"].split())
    assert len(desc) <= 1024 and "<" not in desc and ">" not in desc
    # the trigger is narrow: specify only with governance or on explicit request
    assert "ordinary feature request or coding task is not a trigger" in desc
    assert '"I want to add X"' not in desc and '"my plans changed"' not in desc


def test_docs_only_cite_rules_and_flags_that_exist():
    rules = gen.render_rules_yaml(gen.normalize_config({"project_name": "x", "workspace_root": "./g", "model_preset": "economy",
                                                      "seam_groups": ["web=web/api.py,web/jobs.py"],
                                                      "advisor": True, "claude_code_host": "cloud"}))
    # ROLE-16, ROLE-18 and THR-17 exist only when turned on
    ids = set(re.findall(r"^  - id: (\S+)", rules, re.M))
    docs = [SKILL / n for n in ("SKILL.md", "init.md", "specify.md", "audit.md")] + list((SKILL / "references").glob("*.md"))
    keys = set(gen.default_config()) | {"token_cfg"}
    for doc in docs:
        text = doc.read_text()
        for rid in set(re.findall(r"`((?:META|ROLE|AUTO|LANE|THR|PLAN|CRIT|PR|REV|MRG|TST|CI|GH|KB|REL|INV|PREF)-\d{2})`", text)):
            assert rid in ids, f"{doc.name} cites {rid}"
        for flag in set(re.findall(r"`--set ([a-z_]+)=", text)) | set(re.findall(r"^\| [^|]+\| `([a-z_]+)=", text, re.M)):
            assert flag in keys, f"{doc.name} names setting {flag}"
        for gone in ("coordinator_compact_at_tokens", "lanes.yml", "approval.decision", "four-line summary"):
            assert gone not in text, f"{doc.name} still mentions {gone}"


def test_init_says_where_to_run_and_has_a_migration_route():
    init = (SKILL / "init.md").read_text()
    assert "## Where to run this" in init and "never in the coordinator chat" in init
    assert "## Migrating an existing ruleset" in init and "--derive-config" in init
    skill = (SKILL / "SKILL.md").read_text()
    assert "Migrating an existing ruleset" in skill and "When not to start" in skill
    specify = (SKILL / "specify.md").read_text()
    assert "brief <contract> --owner" in specify and "approved <hash>" in specify and "--preflight" in specify
    assert "do not start the interview" in specify


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_eval_case_is_well_formed(case: Path):
    meta = yaml.safe_load((case / "case.yaml").read_text())
    assert meta["name"] == case.name and meta["expected_outcome"].strip()
    prompt = (case / "prompt.md").read_text()
    assert prompt.startswith("---\n") and prompt.split("---")[2].strip()
    graders = sorted((case / "graders").glob("*.md"))
    assert len(graders) >= 2
    for g in graders:
        front = yaml.safe_load(g.read_text().split("---")[1])
        assert front == {"type": "llm", "focus": "trace", "weight": 1} and g.read_text().split("---")[2].strip()
    script = (meta.get("context") or {}).get("scaffold_script")
    assert bool(script) == (case / "files").exists()
    if script:
        assert (case / script).is_file() and (case / script).stat().st_mode & 0o111


def test_evals_cover_interactive_paths_and_routing():
    names = {c.name for c in CASES}
    for needed in ("init-stage-one-waits", "change-settings-preview-waits", "specify-interview-first-question",
                   "specify-approval-recorded", "specify-approval-without-hash", "specify-issues-preflight",
                   "routing-bare-invocation", "routing-plain-feature-request", "audit-asked-to-fix"):
        assert needed in names
    waits = [c for c in CASES if "cannot" not in (c / "prompt.md").read_text().lower() and "can't" not in (c / "prompt.md").read_text().lower()]
    assert len(waits) >= 6  # cases where the owner is present or has not given a go


def test_no_generated_file_is_checked_in_as_a_fixture():
    for case in CASES:
        if case.name.startswith("audit-"):
            continue  # those rulesets are hand-written on purpose: they carry the planted defects
        for name in ("claude-project-rules.yaml", "governance-config.json", "project_instructions.md", "contract-template.yaml"):
            assert not list(case.rglob(name)), f"{case.name} carries a copy of {name}"


@pytest.fixture(scope="module")
def placed(tmp_path_factory) -> dict[str, Path]:
    out = {}
    for case in GENERATED:
        d = tmp_path_factory.mktemp(case.name)
        r = subprocess.run(["bash", str(case / "place-files.sh")], cwd=d, capture_output=True, text=True)
        assert r.returncode == 0, (case.name, r.stderr)
        out[case.name] = d / "governance"
    return out


def test_generated_fixtures_are_current_and_sound(placed):
    assert len(placed) >= 7
    for name, gov in placed.items():
        assert not (gov / "fixture-config.json").exists()
        a = run("audit_rules.py", gov / "claude-project-rules.yaml", "--state", gov / "project-state.yaml", "--json", "--strict")
        assert a.returncode == 0, (name, a.stdout)
        road = run("contract_tool.py", "roadmap", gov / "roadmap.yaml", "--plans", gov / "plans")
        assert road.returncode == 0, (name, road.stdout)
        # the scaffolded template is the current one, not a copy
        assert (gov / "plans" / "contract-template.yaml").read_text().count("owner_message") == 1
        for contract in gov.glob("plans/contract-0*.yaml"):
            lint = run("contract_tool.py", "lint", contract, "--json")
            assert not errors(lint), (name, contract.name, lint.stdout)
        if (gov / "ledger" / "prs").exists():
            led = run("ledger_tool.py", "check", "--ledger", gov / "ledger")
            assert led.returncode == 0, (name, led.stdout)


def test_fixture_states_match_what_the_prompts_claim(placed):
    # an approved, picked-up contract with no findings at all
    def real(result):  # the fixtures are placed outside git, which lint reports
        return [f for f in findings(result) if f["code"] != "C039"]

    gov = placed["specify-plan-change"]
    assert real(run("contract_tool.py", "lint", gov / "plans/contract-001-csv-import.yaml", "--json")) == []
    # the hash the owner quotes in the prompt is the hash of the draft they are shown
    for name in ("specify-approval-recorded",):
        gov = placed[name]
        h = ct.contract_hash(ct.load(gov / "plans/contract-002-budget-alerts.yaml"))
        prompt = (EVALS / name / "prompt.md").read_text()
        assert f"approved {h}" in prompt and h in (EVALS / name / "case.yaml").read_text()
        draft = run("contract_tool.py", "lint", gov / "plans/contract-002-budget-alerts.yaml", "--json", "--strict")
        assert draft.returncode == 0, draft.stdout
    assert "approved c2" not in (EVALS / "specify-approval-without-hash" / "prompt.md").read_text()
    # the issues case: one package already recorded, one backlog draft left, contract picked up
    gov = placed["specify-issues-preflight"]
    import json

    plan = json.loads(run("contract_tool.py", "issues", gov / "plans/contract-002-budget-alerts.yaml", "--json").stdout)
    assert {d["key"]: d["action"] for d in plan["drafts"]} == {"budgets": "exists", "cut-1": "create"}
    assert real(run("contract_tool.py", "lint", gov / "plans/contract-002-budget-alerts.yaml", "--json")) == []
    # live state survives the fixture build
    state = (placed["change-settings-economy"] / "project-state.yaml").read_text()
    assert "slow_down: true" in state and "Create the PyPI token" in state


def test_packaged_tools_are_the_current_scripts(placed):
    gov = placed["specify-plan-change"]
    for tool in ("contract_tool.py", "ledger_tool.py"):
        assert (gov / "tools" / tool).read_text() == (SKILL / "scripts" / tool).read_text()
    assert (gov / "tools" / "acceptance-contracts.md").read_text() == (SKILL / "references" / "acceptance-contracts.md").read_text()


def test_readme_names_the_tests():
    readme = (ROOT / "README.md").read_text()
    assert "pytest" in readme and "claude plugin eval" in readme
