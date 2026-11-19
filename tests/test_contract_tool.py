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


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    """The specify-plan-change fixture outside git: a generated workspace with an approved, picked-up contract."""
    r = subprocess.run(["bash", str(EVALS / "specify-plan-change" / "place-files.sh")], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tmp_path / "governance"


@pytest.fixture
def ws(plain: Path) -> Path:
    """The same workspace as a git repo: everything reviewed on main, threads working on the governance branch."""
    root = plain.parent
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "approved contract, reviewed by the owner")
    git(root, "checkout", "-q", "-b", "governance")
    return plain


@pytest.fixture
def repo(ws: Path) -> Path:
    return ws


@pytest.fixture
def cloned(ws: Path) -> Path:
    """As ws, with a remote whose default branch (origin/HEAD) the checkout knows, like a normal clone."""
    root = ws.parent
    bare = root.parent / (root.name + "-origin.git")
    git(root, "clone", "-q", "--bare", ".", str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "fetch", "-q", "origin")
    git(root, "remote", "set-head", "origin", "main")
    return ws


def real(result) -> list[dict]:
    """Findings without the note that a local repo has no remote to compare with."""
    return [f for f in findings(result) if not (f["code"] == "C039" and f["severity"] == "INFO")]


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
    assert r.returncode == 0 and real(r) == []


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
    assert real(lint(ws)) == []
    assert run("contract_tool.py", "goal", c, "--ids", "AC-1").returncode == 0
    log.write_text(log.read_text().replace(f"hash {h}.", "hash 000000000000."))
    assert has(lint(ws), "C037", "differs from what was picked up", "ERROR")


def test_format_example_in_the_state_file_is_not_a_record(ws):
    edit(ws / "project-state.yaml", "approved_contracts: [", "approved_contracts: []  # was [")
    state = (ws / "project-state.yaml").read_text()
    assert '# Format: "C-001 v1 D-012 hash 0123456789ab"' in state and "# was [" in state
    assert has(lint(ws), "C037", "approved but not picked up")  # neither comment counts as a record


def test_contract_approved_under_the_old_hash_formula_is_a_warning_not_an_error(plain):
    ws = plain
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


# ---- N1: in a repo, the copy on the default branch is the one that counts --------------

def test_clean_contract_on_the_governance_branch_passes(repo):
    r = lint(repo)
    assert real(r) == [] and has(r, "C039", "no remote 'origin': compared with the local branch 'main'", "INFO")
    assert run("contract_tool.py", "goal", repo / CONTRACT, "--ids", "AC-1").returncode == 0


def test_rewriting_contract_message_and_record_together_fails_in_a_repo(repo):
    c = repo / CONTRACT
    old = ct.contract_hash(ct.load(c))
    edit(c, "stores 120 transactions", "stores 12 transactions")
    new = run("contract_tool.py", "hash", c).stdout.strip()
    for f in (c, repo / "project-state.yaml"):
        f.write_text(f.read_text().replace(old, new))   # hash, quoted owner message and pickup record all rewritten
    git(repo.parent, "commit", "-qam", "quiet edit on the unprotected branch")
    # without the comparison this is the case the first review left open; skipping it is itself reported
    skipped = lint(repo, "--no-git")
    assert not errors(skipped) and has(skipped, "C039", "--no-git: this contract was not compared", "WARN")
    r = lint(repo)
    assert r.returncode == 1 and has(r, "C039", "differs from the copy on main", "ERROR")
    assert has(lint(repo, no_yaml=True), "C039", "differs from the copy on main")
    goal = run("contract_tool.py", "goal", c)
    assert goal.returncode == 1 and "/goal" not in goal.stdout


def test_approval_fields_must_match_the_reviewed_copy(repo):
    c = repo / CONTRACT
    h = ct.contract_hash(ct.load(c))
    edit(c, f'owner_message: "2026-11-11: approved {h}"', f'owner_message: "2026-11-12: yes, approved {h}"')
    assert has(lint(repo), "C039", "approval.owner_message differ", "ERROR")


def test_contract_approved_only_on_the_working_branch_is_refused(repo):
    v2 = repo / "plans" / "contract-001-csv-import-v2.yaml"
    text = (repo / CONTRACT).read_text().replace("version: 1", "version: 2").replace("changes: []", 'changes: ["v2: same"]')
    v2.write_text(text)
    r = run("contract_tool.py", "lint", v2, "--json")
    assert has(r, "C039", "is not on main", "ERROR")
    # a draft is not compared: drafts live on a pull-request branch until the owner approves
    v2.write_text(text.replace("status: approved", "status: draft"))
    assert not has(run("contract_tool.py", "lint", v2, "--json"), "C039")


def test_origin_is_preferred_over_a_local_branch_that_moved(cloned):
    repo = cloned
    root = repo.parent
    git(root, "checkout", "-q", "main")
    edit(repo / CONTRACT, "stores 120 transactions", "stores 12 transactions")
    git(root, "commit", "-qam", "local main moved without review")
    git(root, "checkout", "-q", "governance")
    git(root, "merge", "-q", "main")
    assert has(lint(repo), "C039", "differs from the copy on origin/main", "ERROR")


# ---- P1: the default branch is the remote's, not what the ruleset on the working branch says ----

def tamper(ws):
    """Change a criterion and rewrite hash, quoted owner message and pickup record to match; commit it."""
    c = ws / CONTRACT
    old = ct.contract_hash(ct.load(c))
    edit(c, "stores 120 transactions", "stores 12 transactions")
    new = run("contract_tool.py", "hash", c).stdout.strip()
    for f in (c, ws / "project-state.yaml"):
        f.write_text(f.read_text().replace(old, new))
    git(ws.parent, "commit", "-qam", "quiet edit on the unprotected branch")


def point_default_branch_at(ws, branch):
    for f in [ws / "claude-project-rules.yaml", *(ws / "rules").glob("*.yaml")]:
        f.write_text(f.read_text().replace('default_branch: "main"', f'default_branch: "{branch}"'))
    cfg = ws / "governance-config.json"
    cfg.write_text(cfg.read_text().replace('"default_branch": "main"', f'"default_branch": "{branch}"'))
    git(ws.parent, "commit", "-qam", "ruleset now names another default branch")


def test_changing_default_branch_in_the_ruleset_does_not_redirect_the_comparison(cloned):
    ws = cloned
    tamper(ws)
    point_default_branch_at(ws, "governance")
    r = lint(ws)
    assert r.returncode == 1
    assert has(r, "C039", "names 'governance' as the default branch, but the remote's default branch is 'main'", "ERROR")
    assert has(r, "C039", "differs from the copy on origin/main", "ERROR")
    assert has(r, "C040", "claude-project-rules.yaml", "WARN")
    goal = run("contract_tool.py", "goal", ws / CONTRACT)
    assert goal.returncode == 1 and "/goal" not in goal.stdout
    audit = run("audit_rules.py", ws / "claude-project-rules.yaml", "--state", ws / "project-state.yaml", "--json")
    assert audit.returncode == 1
    found = {(f["code"], f["severity"]) for f in json.loads(audit.stdout)["findings"]}
    assert ("A14", "ERROR") in found and ("A14", "WARN") in found


def test_without_origin_head_a_redirected_default_branch_is_still_caught(ws):
    # a local-only repo: the remote cannot arbitrate, but comparing a branch with itself is recognised
    tamper(ws)
    point_default_branch_at(ws, "governance")
    r = lint(ws)
    assert has(r, "C039", "is the branch you are on", "WARN")
    goal = run("contract_tool.py", "goal", ws / CONTRACT)
    assert goal.returncode == 1 and "not verified against the copy the owner reviewed" in goal.stderr
    pick = run("contract_tool.py", "pickup", ws / CONTRACT, "--hash", ct.contract_hash(ct.load(ws / CONTRACT)), "--decision", "D-9")
    assert pick.returncode == 1 and pick.stdout == ""


def test_a_default_branch_flag_cannot_redirect_either(cloned):
    tamper(cloned)
    r = lint(cloned, "--default-branch", "governance")
    assert has(r, "C039", "but the remote's default branch is 'main'", "ERROR") and has(r, "C039", "differs from the copy on origin/main")


@pytest.mark.parametrize("rel", ["claude-project-rules.yaml", "rules/implementation.yaml", "roadmap.yaml", "governance-config.json"])
def test_ruleset_extracts_roadmap_and_config_are_compared_too(cloned, rel):
    ws = cloned
    f = ws / rel
    f.write_text(f.read_text() + "\n# quiet change\n" if not rel.endswith(".json") else f.read_text().replace('"is_public": false', '"is_public": true'))
    git(ws.parent, "commit", "-qam", "edit a protected file on the governance branch")
    r = lint(ws)
    assert not errors(r) and has(r, "C040", rel, "WARN")
    goal = run("contract_tool.py", "goal", ws / CONTRACT)
    assert goal.returncode == 1 and "C040" in goal.stderr
    audit = run("audit_rules.py", ws / "claude-project-rules.yaml", "--state", ws / "project-state.yaml", "--json")
    assert any(x["code"] == "A14" and rel in x["message"] for x in json.loads(audit.stdout)["findings"])


def test_clean_clone_is_silent_and_works(cloned):
    assert findings(lint(cloned)) == []
    assert run("contract_tool.py", "goal", cloned / CONTRACT, "--ids", "AC-1").returncode == 0
    audit = run("audit_rules.py", cloned / "claude-project-rules.yaml", "--state", cloned / "project-state.yaml", "--json", "--strict")
    assert audit.returncode == 0 and [f for f in json.loads(audit.stdout)["findings"] if f["code"] != "A15"] == []


# ---- P2: the comparison is never skipped without a trace --------------------------------------

def test_goal_and_pickup_have_no_switch_to_skip_the_comparison(ws):
    c = ws / CONTRACT
    for args in (("goal", c, "--no-git"), ("pickup", c, "--hash", "x", "--decision", "D-1", "--no-git")):
        r = run("contract_tool.py", *args)
        assert r.returncode == 2 and "unrecognized arguments: --no-git" in r.stderr


def test_a_workspace_outside_git_is_reported_and_starts_no_work(plain):
    r = lint(plain)   # the ruleset says environment claude_code, so a missing repository is a warning
    assert r.returncode == 0 and has(r, "C039", "this is not a git checkout", "WARN")
    assert lint(plain, "--strict").returncode == 1
    goal = run("contract_tool.py", "goal", plain / CONTRACT)
    assert goal.returncode == 1 and "not a git checkout" in goal.stderr
    h = ct.contract_hash(ct.load(plain / CONTRACT))
    edit(plain / "project-state.yaml", f'approved_contracts: ["C-001 v1 D-004 hash {h}"]', "approved_contracts: []")
    assert run("contract_tool.py", "pickup", plain / CONTRACT, "--hash", h, "--decision", "D-5").returncode == 1


def test_a_claude_ai_project_outside_git_gets_a_note_and_works(plain):
    for f in [plain / "claude-project-rules.yaml"]:
        f.write_text(f.read_text().replace("environment: claude_code", "environment: claude_ai_project"))
    r = lint(plain)
    assert has(r, "C039", "not a git checkout", "INFO") and lint(plain, "--strict").returncode == 0
    assert run("contract_tool.py", "goal", plain / CONTRACT, "--ids", "AC-1").returncode == 0


def test_missing_origin_ref_or_origin_head_is_a_warning_not_a_silent_fallback(cloned):
    root = cloned.parent
    git(root, "remote", "set-head", "origin", "--delete")
    r = lint(cloned)
    assert not errors(r) and has(r, "C039", "does not record the remote's default branch", "WARN")
    assert run("contract_tool.py", "goal", cloned / CONTRACT).returncode == 1
    git(root, "update-ref", "-d", "refs/remotes/origin/main")
    r = lint(cloned)
    assert has(r, "C039", "origin/main is not in this checkout; compared with the local branch 'main'", "WARN")
    assert run("contract_tool.py", "goal", cloned / CONTRACT).returncode == 1
    assert has(lint(cloned, "--default-branch", "trunk"), "C039", "not known in this checkout", "WARN")


# ---- N4: pickup names the hash the owner approved ------------------------------------------

def unpick(ws):
    """Remove the pickup record, on both branches, as if the coordinator had not picked the contract up yet."""
    h = ct.contract_hash(ct.load(ws / CONTRACT))
    edit(ws / "project-state.yaml", f'approved_contracts: ["C-001 v1 D-004 hash {h}"]', "approved_contracts: []")
    return h


def test_pickup_prints_the_line_only_for_the_hash_the_owner_named(plain):
    ws = plain   # a claude.ai Project: no git to compare with, so the hash the owner names is what ties pickup to approval
    rules = ws / "claude-project-rules.yaml"
    rules.write_text(rules.read_text().replace("environment: claude_code", "environment: claude_ai_project"))
    c = ws / CONTRACT
    h = unpick(ws)
    ok = run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "D-12")
    assert ok.returncode == 0 and ok.stdout.strip() == f"C-001 v1 D-12 hash {h}"
    assert run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "twelve").returncode == 1
    # between approval and pickup: a criterion, the hash and the quoted message are rewritten; lint has no record to compare with
    edit(c, "stores 120 transactions", "stores 12 transactions")
    new = run("contract_tool.py", "hash", c).stdout.strip()
    c.write_text(c.read_text().replace(h, new))
    assert not errors(lint(ws))
    bad = run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "D-12")
    assert bad.returncode == 1 and bad.stdout == "" and "not the contract the owner approved" in bad.stderr


def test_pickup_refuses_drafts_lint_errors_and_a_second_pickup(ws):
    c = ws / CONTRACT
    h = ct.contract_hash(ct.load(c))
    again = run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "D-13")
    assert again.returncode == 1 and "already recorded" in again.stderr
    unpick(ws)
    edit(c, "status: approved", "status: draft")
    assert "not approved" in run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "D-13").stderr
    edit(c, "status: draft", "status: approved")
    edit(c, "by: owner", "by: coordinator")
    assert "C023" in run("contract_tool.py", "pickup", c, "--hash", h, "--decision", "D-13").stderr


def test_pickup_in_a_repo_checks_the_reviewed_copy(repo):
    c = repo / CONTRACT
    old = unpick(repo)
    edit(c, "stores 120 transactions", "stores 12 transactions")
    new = run("contract_tool.py", "hash", c).stdout.strip()
    c.write_text(c.read_text().replace(old, new))
    # even if the owner's pick-up message were forged to name the new hash, the reviewed copy says otherwise
    r = run("contract_tool.py", "pickup", c, "--hash", new, "--decision", "D-12")
    assert r.returncode == 1 and "C039" in r.stderr


# ---- N6: record-issue does not overwrite silently --------------------------------------------

def test_record_issue_refuses_a_second_number_unless_replace(ws):
    c = ws / CONTRACT
    assert run("contract_tool.py", "record-issue", c, "import", "41").returncode == 0
    assert run("contract_tool.py", "record-issue", c, "import", "41").returncode == 0  # the same number again is fine
    clash = run("contract_tool.py", "record-issue", c, "import", "77")
    assert clash.returncode == 1 and "already has issue #41" in clash.stderr and "duplicate" in clash.stderr
    assert json.loads((ws / "plans" / "issues-C-001.json").read_text())["packages"]["import"]["issue"] == 41
    assert run("contract_tool.py", "record-issue", c, "import", "77", "--replace").returncode == 0
    assert json.loads((ws / "plans" / "issues-C-001.json").read_text())["packages"]["import"]["issue"] == 77
