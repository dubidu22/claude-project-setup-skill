"""contract_tool.py: the freeze, the owner view, lint gaps, issues, roadmap, and YAML without PyYAML."""
from __future__ import annotations

import datetime
import glob
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import contract_tool as ct
from conftest import EVALS, SKILL, errors, findings, run

CONTRACT = "plans/contract-001-csv-import.yaml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """The specify-plan-change fixture: a generated workspace with an approved, picked-up contract."""
    r = subprocess.run(["bash", str(EVALS / "specify-plan-change" / "place-files.sh")], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tmp_path / "governance"


def lint(ws: Path, *extra, name: str = CONTRACT, no_yaml: bool = False):
    return run("contract_tool.py", "lint", ws / name, "--json", *extra, no_yaml=no_yaml)


def has(result, code, needle="", severity=None):
    return any(f["code"] == code and needle in f["message"] and severity in (None, f["severity"]) for f in findings(result))


def edit(path: Path, old: str, new: str):
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


def test_fixture_contract_is_clean(ws):
    r = lint(ws)
    assert r.returncode == 0 and findings(r) == []


# ---- D1: the freeze ----------------------------------------------------------

def test_edit_with_recomputed_hash_is_caught_by_the_pickup_record(ws):
    c = ws / CONTRACT
    old_hash = ct.contract_hash(ct.load(c))
    edit(c, "stores 120 transactions", "stores 12 transactions")
    assert has(lint(ws), "C027", "edited in place", "ERROR")
    new_hash = run("contract_tool.py", "hash", c).stdout.strip()
    assert new_hash != old_hash
    c.write_text(c.read_text().replace(old_hash, new_hash))  # the thread also rewrites hash and quoted message
    r = lint(ws)
    assert r.returncode == 1 and has(r, "C037", "differs from what was picked up", "ERROR")
    goal = run("contract_tool.py", "goal", c)
    assert goal.returncode == 1 and "/goal" not in goal.stdout


def test_hash_only_rewritten_is_caught_by_the_owner_message(ws):
    c = ws / CONTRACT
    old_hash = ct.contract_hash(ct.load(c))
    edit(c, "stores 120 transactions", "stores 12 transactions")
    new_hash = run("contract_tool.py", "hash", c).stdout.strip()
    edit(c, f"hash: {old_hash}", f"hash: {new_hash}")
    assert has(lint(ws), "C038", "does not contain the hash", "ERROR")


@pytest.mark.parametrize("old,new", [
    ('users: "only the owner"', 'users: "public"'),
    ('access: "CLI on macOS and Ubuntu"', 'access: "browser"'),
    ('  - "multi-currency"', '  - "nothing"'),
    ('  - "transaction data never leaves the machine"', '  - "none"'),
    ("Fresh clone, follow README", "Old clone, skip README"),
    ("pytest tests/test_import.py::test_fixture_count", "true"),
    ("priority: must\n    category: happy_path", "priority: should\n    category: happy_path"),
])
def test_hash_covers_scope_and_every_criterion_field(ws, old, new):
    c = ws / CONTRACT
    before = ct.contract_hash(ct.load(c))
    text = c.read_text()
    assert old in text
    c.write_text(text.replace(old, new, 1))
    assert ct.contract_hash(ct.load(c)) != before
    assert lint(ws).returncode == 1


def test_regrouping_work_packages_does_not_change_the_hash(ws):
    c = ws / CONTRACT
    before = ct.contract_hash(ct.load(c))
    edit(c, 'title: "Monthly report"', 'title: "Report"')
    assert ct.contract_hash(ct.load(c)) == before and lint(ws).returncode == 0


def test_record_in_the_decision_log_counts_too(ws):
    c = ws / CONTRACT
    h = ct.contract_hash(ct.load(c))
    edit(ws / "project-state.yaml", f'approved_contracts: ["C-001 v1 D-004 hash {h}"]', "approved_contracts: []")
    assert has(lint(ws), "C037", "approved but not picked up", "WARN")
    assert run("contract_tool.py", "goal", c).returncode == 1
    log = ws / "kb" / "decision-log.md"
    log.write_text(log.read_text() + f"\n## D-004 (2026-11-12, owner)\nPicked up C-001 v1, hash {h}.\nOwner message: \"approved {h}\"\n")
    assert findings(lint(ws)) == []
    assert run("contract_tool.py", "goal", c, "--ids", "AC-1").returncode == 0
    log.write_text(log.read_text().replace(f"hash {h}.", "hash 000000000000."))
    assert has(lint(ws), "C037", "differs from what was picked up", "ERROR")


def test_format_example_in_the_state_file_is_not_a_record(ws):
    edit(ws / "project-state.yaml", "approved_contracts: [", "approved_contracts: []  # was [")
    state = (ws / "project-state.yaml").read_text()
    assert '# Format: "C-001 v1 D-012 hash 0123456789ab"' in state and "# was [" in state
    assert has(lint(ws), "C037", "approved but not picked up")  # neither comment counts as a record


def test_contract_approved_under_the_old_hash_formula_is_a_warning_not_an_error(ws):
    c = ws / CONTRACT
    data = ct.load(c)
    new, old = ct.contract_hash(data), ct.legacy_hash(data)
    c.write_text(c.read_text().replace(new, old))
    (ws / "project-state.yaml").write_text((ws / "project-state.yaml").read_text().replace(new, old))
    r = lint(ws)
    assert r.returncode == 0 and has(r, "C027", "older tool version", "WARN") and not errors(r)


def test_no_workspace_next_to_the_contract_is_reported(tmp_path):
    src = EVALS / "specify-plan-change" / "files" / "governance" / CONTRACT
    lone = tmp_path / "somewhere" / "plans" / "c.yaml"
    lone.parent.mkdir(parents=True)
    shutil.copy(src, lone)
    r = run("contract_tool.py", "lint", lone, "--json")
    assert has(r, "C037", "cannot be checked", "WARN")


# ---- D2: what the owner sees --------------------------------------------------

def test_owner_view_shows_everything_the_approval_covers(ws):
    c = ws / CONTRACT
    out = run("contract_tool.py", "brief", c, "--owner").stdout
    h = ct.contract_hash(ct.load(c))
    for needle in ("users: only the owner", "access: CLI on macOS and Ubuntu", "constraints: transaction data never leaves",
                   "out of scope: multi-currency", "AC-1 [must]", "pytest tests/test_import.py::test_fixture_count",
                   "core probe:", f"hash: {h}", f"reply: approved {h}"):
        assert needle in out, needle
    worker = run("contract_tool.py", "brief", c, "--ids", "AC-2").stdout
    assert "AC-2" in worker and "AC-1" not in worker and "hash" not in worker
    assert f"C-001 v1 D-<n> hash {h}" in run("contract_tool.py", "summary", c).stdout


def test_approval_needs_the_owners_message(ws):
    c = ws / CONTRACT
    h = ct.contract_hash(ct.load(c))
    edit(c, f'owner_message: "2026-11-11: approved {h}"', 'owner_message: ""')
    assert has(lint(ws), "C038", "approval.owner_message is empty", "WARN")
    edit(c, 'owner_message: ""', 'owner_message: "ok fine"')
    assert has(lint(ws), "C038", "does not contain the hash", "ERROR")
    edit(c, "by: owner", "by: coordinator")
    assert has(lint(ws), "C023", "approval.by is not 'owner'", "ERROR")


# ---- B11: lint gaps ------------------------------------------------------------

@pytest.mark.parametrize("text,vague", [
    ("The import works reliably and fast on Python 3", True),
    ("Startup is fast", True),
    ("The export is robust for 2 formats", True),
    ("`app --help` returns in under 300 ms on the CI runner", False),
    ("A bad file exits 2 quickly", False),
    ("The page loads fast: at most 3 requests", False),
    ("Importing the fixture stores 120 rows correctly", False),
    ("Importing a CSV with a missing column exits with code 2 and names the column", False),
])
def test_vague_wording_needs_a_measurement_not_just_a_digit(text, vague):
    data = {"contract": {"id": "C-9", "title": "t", "milestone": "m", "version": 1, "status": "draft"},
            "goal": "g", "core_probe": "p", "users": "u", "access": "a", "out_of_scope": ["x"],
            "criteria": [{"id": "AC-1", "text": text, "priority": "must", "category": "happy_path",
                          "verify": {"type": "test", "how": "t"}, "source": {"kind": "owner", "ref": "r"}}]}
    assert any(f.code == "C017" for f in ct.lint(data)) is vague


def test_work_package_label_must_exist_in_the_ruleset(ws):
    c = ws / CONTRACT
    edit(c, 'label: "lane:app"', 'label: "lane:doesnotexist"')
    r = lint(ws)
    assert has(r, "C033", "is not a file-ownership label of this project's ruleset", "ERROR")
    assert has(lint(ws, no_yaml=True), "C033", "is not a file-ownership label")
    assert not has(run("contract_tool.py", "lint", c, "--json", "--rules", ws / "nope.yaml"), "C033", "ruleset")


# ---- B9: roadmap -----------------------------------------------------------------

def test_roadmap_check_skips_only_the_template(ws):
    road = lambda: run("contract_tool.py", "roadmap", ws / "roadmap.yaml", "--plans", ws / "plans")  # noqa: E731
    assert road().returncode == 0 and "R010" not in road().stdout
    other = (ws / CONTRACT).read_text().replace("C-001", "C-002").replace('milestone: "v0.1"', 'milestone: "email"')
    (ws / "plans" / "contract-002-email-templates.yaml").write_text(other)
    assert "R010" in road().stdout and "email" in road().stdout
    assert (ws / "plans" / "contract-template.yaml").exists()
    assert "cannot read contract-template.yaml" not in road().stdout


# ---- B12: issues -------------------------------------------------------------------

def test_issues_have_keys_preflight_and_a_record_that_prevents_duplicates(ws):
    c = ws / CONTRACT
    drafts = json.loads(run("contract_tool.py", "issues", c, "--json").stdout)
    assert [d["key"] for d in drafts["drafts"]] == ["import", "report"] and all(d["action"] == "create" for d in drafts["drafts"])
    pre = run("contract_tool.py", "issues", c, "--preflight")
    assert pre.returncode == 0 and "Labels needed: lane:app, lane:cli" in pre.stdout and "Milestones needed: v0.1" in pre.stdout
    assert "rwaller/ledgerlite" in pre.stdout  # repository taken from the ruleset
    missing = run("contract_tool.py", "issues", c, "--preflight", "--have-labels", "lane:cli", "--have-milestones", "")
    assert missing.returncode == 1 and "Missing labels: lane:app" in missing.stdout and "Missing milestones: v0.1" in missing.stdout
    ok = run("contract_tool.py", "issues", c, "--preflight", "--have-labels", "lane:cli,lane:app,x", "--have-milestones", "v0.1")
    assert ok.returncode == 0 and "Pre-flight passed." in ok.stdout

    assert run("contract_tool.py", "record-issue", c, "import", "41").returncode == 0
    assert run("contract_tool.py", "record-issue", c, "nope", "42").returncode == 1
    record = json.loads((ws / "plans" / "issues-C-001.json").read_text())
    assert record["packages"]["import"] == {"issue": 41, "version": 1, "title": "[C-001] CSV import with validation"}
    drafts = json.loads(run("contract_tool.py", "issues", c, "--json").stdout)["drafts"]
    assert {d["key"]: d["action"] for d in drafts} == {"import": "exists", "report": "create"}
    assert "already created as #41: skip" in run("contract_tool.py", "issues", c).stdout
    # with everything that exists already recorded, the pre-flight only asks for what is still needed
    assert "Labels needed: lane:app" in run("contract_tool.py", "issues", c, "--preflight").stdout


def test_a_new_version_says_which_issues_it_replaces(ws):
    c = ws / CONTRACT
    run("contract_tool.py", "record-issue", c, "import", "41")
    run("contract_tool.py", "record-issue", c, "report", "42")
    v2 = ws / "plans" / "contract-001-csv-import-v2.yaml"
    text = c.read_text().replace("version: 1", "version: 2").replace("status: approved", "status: draft")
    text = text.replace('  - {key: report, title: "Monthly report", label: "lane:app", criteria: [AC-4]}\n', "")
    text = text.replace("criteria: [AC-1, AC-2, AC-3]}", "criteria: [AC-1, AC-2, AC-3, AC-4]}").replace("changes: []", 'changes: ["v2: one package"]')
    v2.write_text(text)
    out = json.loads(run("contract_tool.py", "issues", v2, "--json").stdout)
    assert out["drafts"][0]["action"] == "replaces" and out["drafts"][0]["existing_issue"] == 41
    assert out["obsolete"] == [{"key": "report", "issue": 42, "version": 1, "title": "[C-001] Monthly report"}]
    plain = run("contract_tool.py", "issues", v2).stdout
    assert "replaces #41 (made for v1)" in plain and "#42 (report, made for v1)" in plain


# ---- B13: YAML without PyYAML --------------------------------------------------------

def norm(v):
    if isinstance(v, dict):
        return {str(k): norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()[:10]
    return v


def test_builtin_reader_agrees_with_pyyaml_on_every_yaml_in_the_skill(ws):
    files = glob.glob(str(SKILL / "**" / "*.yaml"), recursive=True) + glob.glob(str(ws / "**" / "*.yaml"), recursive=True)
    assert len(files) > 25
    for f in files:
        text = Path(f).read_text()
        assert norm(ct.mini_yaml(text)) == norm(yaml.safe_load(text)), f


@pytest.mark.parametrize("text", [
    "a: 1\nb: [x, 'y, z', \"q\"]\nc:\n  - k: v\n    l: w\n  - plain\nd: |\n  one\n  two\ne: >-\n  folded\n  text\nf: {x: 1, y: \"a, b\"}\n",
    "list:\n- a\n- b\nempty: []\nnone:\nquoted: \"a: b # c\"\nsingle: 'it''s'\ncomment: x # tail\n",
    "- id: 1\n  nested:\n    deep: true\n- id: 2\n",
])
def test_builtin_reader_on_handwritten_yaml(text):
    assert norm(ct.mini_yaml(text)) == norm(yaml.safe_load(text))


def test_builtin_reader_refuses_what_it_cannot_read():
    with pytest.raises(ValueError, match="continued on the next line"):
        ct.mini_yaml("text: one\n  two\n")
    with pytest.raises(ValueError):
        ct.mini_yaml("a: 1\n  b: 2\n")


def test_all_commands_work_without_pyyaml(ws):
    c = ws / CONTRACT
    for args in (("lint", c, "--json"), ("summary", c), ("brief", c, "--owner"), ("hash", c), ("issues", c),
                 ("roadmap", ws / "roadmap.yaml", "--plans", ws / "plans"), ("goal", c)):
        with_yaml, without = run("contract_tool.py", *args), run("contract_tool.py", *args, no_yaml=True)
        assert without.returncode == 0, (args, without.stderr)
        assert without.stdout == with_yaml.stdout, args


def test_planted_contract_still_fails_for_the_planted_reasons():
    planted = EVALS / "contract-lint-planted-defects" / "files" / "plans" / "contract-004-reminders.yaml"
    r = run("contract_tool.py", "lint", planted, "--json")
    assert r.returncode == 1
    for code, needle in [("C003", "core_probe"), ("C011", "duplicate id AC-3"), ("C016", "retrieved"), ("C016", "URL"),
                         ("C017", "reliably"), ("C020", "manual"), ("C022", "AC-7"), ("C023", "not 'owner'"),
                         ("C024", "AC-8"), ("C027", "approval.hash is empty"), ("C028", "version 2"), ("C037", "D-number")]:
        assert has(r, code, needle), (code, needle)
