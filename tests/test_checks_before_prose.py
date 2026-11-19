"""Checks before prose: invariants with checks, PR checks, readiness, the merge gate, reverts, runtime proof."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

import pr_checks
import repo_readiness
from conftest import SKILL, findings, run


def a15(result) -> list[str]:
    return [f["message"] for f in findings(result) if f["code"] == "A15"]


# ---- invariants name what enforces them ----------------------------------------------------

def test_every_invariant_says_what_enforces_it(w):
    w.generate({
        "project_name": "demo",
        "licence_check": "licence-check job in CI",
        "telemetry_check": "tests/test_no_network.py",
        "custom_invariants": [
            "The schema stays backwards compatible. [check: tests/test_schema_compat.py]",
            "Exports are deterministic",
            "No useEffect in product code [check: eslint rule no-restricted-syntax]",
        ],
    })
    rules = {r["id"]: r["rule"] for r in yaml.safe_load(w.rules_text())["hard_invariants_and_owner_prefs"]}
    assert rules["INV-01"].endswith("Banned licences: AGPL, SSPL, non-commercial, unclear. Enforced by: licence-check job in CI.")
    assert "enforced automatically (import linting)" in rules["INV-02"]
    assert rules["INV-03"].endswith("unrequested network calls. Enforced by: tests/test_no_network.py.")
    assert rules["INV-04"] == "The schema stays backwards compatible. Enforced by: tests/test_schema_compat.py."
    assert rules["INV-05"] == "Exports are deterministic. Enforced by: review only."
    assert rules["INV-06"] == "No useEffect in product code. Enforced by: eslint rule no-restricted-syntax."
    assert "[check:" not in w.rules_text()
    notes = a15(w.audit("--json"))
    assert len(notes) == 1 and notes[0].startswith("INV-05 is enforced by review only")


def test_default_ruleset_admits_which_invariants_have_no_check(w):
    w.generate()
    assert "Enforced by: review only." in w.rule("INV-01")
    notes = a15(w.audit("--json"))
    assert notes and notes[0].startswith("INV-01, INV-03 are enforced by review only")
    assert w.audit("--strict").returncode == 0  # a note, not a failure


def test_invariant_checks_survive_migration(w):
    w.generate({"project_name": "demo", "licence_check": "licence job", "telemetry_check": "tests/test_net.py",
                "custom_invariants": ["A holds. [check: tests/a.py]", "B holds."]})
    out = w.tmp / "derived.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--out", out).returncode == 0
    cfg = json.loads(out.read_text())
    assert cfg["licence_check"] == "licence job" and cfg["telemetry_check"] == "tests/test_net.py"
    assert cfg["custom_invariants"] == ["A holds. [check: tests/a.py]", "B holds."]
    assert cfg["banned_licences"] == ["AGPL", "SSPL", "non-commercial", "unclear"]
    before = w.rules_text()
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.rules_text() == before  # the round trip reproduces the ruleset exactly


# ---- the rules that carry the lessons --------------------------------------------------------

def test_rules_for_root_cause_fixes_proof_and_repeated_corrections(w):
    w.generate()
    assert "becomes a check in the product repository" in w.rule("META-03") and "Prose is the last resort" in w.rule("META-03")
    rev05 = w.rule("REV-05")
    assert "is not a fix and leaves the finding open" in rev05 and "kind already seen in an earlier PR" in rev05
    ver01 = w.rule("VER-01")
    assert "kb/verification.md" in ver01 and "no test-only shortcut" in ver01 and "never weakened to pass" in ver01
    assert "ledger_tool.py gate <N> passes" in w.rule("MRG-01")
    assert "appear in more than one PR" in w.rule("ROLE-09")
    assert "evidence of a runtime step" in w.rule("REV-03") and "evidence file for a runtime step" in w.rule("PLAN-04")
    assert yaml.safe_load((w.ws / "rules" / "implementation.yaml").read_text())["rules"]  # extracts still parse
    ids = {r["id"] for r in yaml.safe_load((w.ws / "rules" / "review.yaml").read_text())["rules"]}
    assert {"REV-05", "META-03"} <= ids and "VER-01" not in ids


def test_runtime_verification_can_be_turned_off_cleanly(w):
    w.generate(None, "runtime_verification=false")
    assert "VER-01" not in w.rule_ids()
    w.scaffold()
    assert not (w.ws / "kb" / "verification.md").exists() and not (w.ws / "kb" / "features").exists()
    text = "\n".join(p.read_text() for p in w.ws.rglob("*.md") if "tools" not in p.parts)
    assert "VER-01" not in text and "verification.md" not in text and "<!--" not in text


def test_runbook_and_feature_map_are_scaffolded_as_drafts(w):
    w.generate()
    w.scaffold()
    runbook = (w.ws / "kb" / "verification.md").read_text()
    assert "Status: **draft**" in runbook
    for section in ("## Surface", "## Start", "## Health check", "## Drive", "## Evidence", "## Cleanup", "## What is not proven here"):
        assert section in runbook
    assert "never by\nprocess name" in runbook and "No internal setter" in runbook
    fmap = (w.ws / "kb" / "features" / "README.md").read_text()
    for section in ("## Sub-features", "## How to get to it", "## Driving it", "## Gotchas"):
        assert section in fmap
    assert "verification.md" in (w.ws / "kb" / "README.md").read_text()
    # a filled-in runbook is the project's own: a refresh never overwrites it
    (w.ws / "kb" / "verification.md").write_text("proven on 2026-03-04 by #7")
    w.scaffold("--refresh")
    assert (w.ws / "kb" / "verification.md").read_text() == "proven on 2026-03-04 by #7"


def test_no_profile_saves_on_review_rounds(w):
    import generate_project_rules as gen

    assert all(p["non_critical_max_review_rounds"] >= 2 for p in gen.TOKEN_PROFILES.values())
    w.generate(None, "profile_key=frugal")
    assert yaml.safe_load(w.rules_text())["execution_profile"]["token_economy"]["non_critical_max_review_rounds"] == 2
    w.generate(None, "token_cfg.non_critical_max_review_rounds=1")  # still the owner's call, but the audit says what it costs
    r = w.audit("--json")
    assert any(f["code"] == "A05" and f["severity"] == "WARN" and "leaves no round" in f["message"] for f in findings(r))


def test_runtime_is_a_verify_type():
    import contract_tool as ct

    data = {"contract": {"id": "C-9", "title": "t", "milestone": "m", "version": 1, "status": "draft"},
            "goal": "g", "core_probe": "p", "users": "u", "access": "a", "out_of_scope": ["x"],
            "criteria": [{"id": "AC-1", "text": "The import dialog lists 3 files", "priority": "must", "category": "happy_path",
                          "verify": {"type": "runtime", "how": "import: open the dialog, pick the folder, 3 rows are listed; screenshot"},
                          "source": {"kind": "owner", "ref": "r"}}]}
    assert not [f for f in ct.lint(data) if f.code == "C014"]
    data["criteria"][0]["verify"]["type"] = "vibes"
    assert [f for f in ct.lint(data) if f.code == "C014"]
    assert "runtime" in (SKILL / "assets/templates/plans/contract-template.yaml").read_text()


# ---- label paths ------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    'label_paths=["src/cli/**"]', 'label_paths=["lane:nope=src/**"]', 'label_paths=["lane:cli=/src/**"]',
    'label_paths=["lane:cli=../x/**"]', 'label_paths=["lane:cli="]', "label_paths=lane:cli=src/**",
])
def test_label_paths_are_validated(w, bad):
    w.generate()
    r = w.generate(None, bad)
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_label_paths_reach_the_ruleset_and_the_pr_check_config(w):
    w.generate(None, 'label_paths=["lane:cli=src/cli/**","lane:cli=bin/*","lane:docs=docs/**","lane:core=src/core/**"]',
               'critical_paths=["src/core/**"]', "workspace_root=./governance")
    assert yaml.safe_load(w.rules_text())["project_profile"]["label_paths"][0] == "lane:cli=src/cli/**"
    assert w.scaffold("--github").returncode == 0
    gh = w.ws / "github-setup"
    cfg = json.loads((gh / "pr-checks.json").read_text())
    assert cfg["label_paths"] == {"lane:cli": ["src/cli/**", "bin/*"], "lane:docs": ["docs/**"], "lane:core": ["src/core/**"]}
    assert cfg["open_labels"] == ["lane:docs"] and cfg["lock_label"] == "lane:infra" and cfg["locked_label"] == "lane:core"
    assert cfg["critical_paths"] == ["src/core/**"] and cfg["governance_paths"] == ["governance/**"]
    assert (gh / "pr_checks.py").read_text() == (SKILL / "scripts" / "pr_checks.py").read_text()
    workflow = yaml.safe_load((gh / "pr-checks-workflow.yml").read_text())
    step = workflow["jobs"]["checks"]["steps"][1]
    assert "pull_request" in workflow[True] and "pr_checks.py" in step["run"]
    # the PR title reaches the script through the environment, never pasted into the shell command
    assert "${{" not in step["run"] and step["env"]["PR_TITLE"] == "${{ github.event.pull_request.title }}"
    readme = (gh / "README.md").read_text()
    for needle in ("Block force pushes", "Require a pull request before merging", "governance pr checks", "Require review from Code Owners"):
        assert needle in readme
    # the scaffolded copy runs as it stands
    (w.tmp / "changed.txt").write_text("M\tsrc/cli/main.py\n")
    (w.tmp / "commits.txt").write_text("add import\n")
    r = subprocess.run([sys.executable, str(gh / "pr_checks.py"), "--config", str(gh / "pr-checks.json"), "--title", "cli: add import (#12)",
                        "--labels", "lane:cli", "--files", str(w.tmp / "changed.txt"), "--commits", str(w.tmp / "commits.txt")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "All checks passed." in r.stdout


def test_without_label_paths_the_readme_says_ownership_is_not_checked(w):
    w.generate()
    w.scaffold("--github")
    assert "File ownership is not checked yet" in (w.ws / "github-setup" / "README.md").read_text()
    assert not (w.ws / "github-setup" / "CODEOWNERS").exists()


# ---- pr_checks.py ---------------------------------------------------------------------------------

CFG = {
    "ownership_labels": ["lane:core", "lane:cli", "lane:infra", "lane:docs"],
    "label_paths": {"lane:cli": ["src/cli/**", "bin/*"], "lane:docs": ["docs/**", "*.md"], "lane:core": ["src/core/**"]},
    "open_labels": ["lane:docs"], "lock_label": "lane:infra", "locked_label": "lane:core",
    "critical_paths": ["src/core/**"], "governance_paths": ["governance/**"],
}


def check(title="cli: add import (#12)", labels=("lane:cli",), files=("src/cli/main.py",), commits="add import\n", cfg=CFG):
    changes = [f if isinstance(f, tuple) else ("M", f) for f in files]
    results = pr_checks.run_checks(cfg, title, list(labels), changes, commits)
    return {r["check"]: r["status"] for r in results}, results


def test_pr_checks_pass_on_a_clean_pull_request():
    status, _ = check(files=("src/cli/main.py", "bin/tool", "docs/usage.md", "README.md"))
    assert set(status.values()) == {"ok"}


@pytest.mark.parametrize("title,ok", [
    ("cli: add import (#12)", True), ("core/db: fix the lock on write (#3)", True),
    ("add import", False), ("cli: add import", False), ("cli:add import (#12)", False), (": x (#1)", False),
    ("cli: add import (#12) ", True), ("cli: add import (12)", False),
])
def test_title_format(title, ok):
    assert (check(title=title)[0]["title"] == "ok") is ok


@pytest.mark.parametrize("message,ok", [
    ("add import\n\nRefs #12\n", True), ("fix the parser for issue 12\n", True), ("prefix #12 handling\n", True),
    ("add import\n\nCloses #12\n", False), ("fixes #7", False), ("Resolved: #9", False), ("closes owner/repo#4", False),
])
def test_closing_keywords_in_commits(message, ok):
    assert (check(commits=message)[0]["commits"] == "ok") is ok


def test_lane_label_and_ownership():
    assert check(labels=("risk:low",))[0]["lane label"] == "FAIL"
    status, results = check(files=("src/cli/main.py", "src/api/server.py"), labels=("lane:cli",),
                            cfg={**CFG, "label_paths": {**CFG["label_paths"], "lane:api": ["src/api/**"]}})
    assert status["ownership"] == "FAIL" and "src/api/server.py (lane:api)" in next(r["message"] for r in results if r["check"] == "ownership")
    # docs are open to every lane; files nobody owns are a warning for the reviewer, not a failure
    status, _ = check(files=("docs/a.md", "scripts/release.sh"))
    assert status["ownership"] == "ok" and status["unowned"] == "WARN"


def test_core_needs_the_lock_label_and_risk_high():
    status, _ = check(files=("src/core/model.py",), labels=("lane:core",))
    assert status["lock"] == "FAIL" and status["critical"] == "FAIL"
    status, _ = check(files=("src/core/model.py",), labels=("lane:core", "lane:infra", "risk:high"))
    assert "lock" not in status and status["critical"] == "ok" and status["ownership"] == "ok"


def test_governance_only_pull_requests_are_exempt_but_not_from_the_commit_check():
    status, _ = check(title="D-041 to D-047", labels=(), files=("governance/kb/decision-log.md",))
    assert status == {"commits": "ok", "scope": "ok"}
    status, _ = check(title="D-041", labels=(), files=("governance/kb/decision-log.md",), commits="Closes #3")
    assert status["commits"] == "FAIL"
    status, _ = check(title="D-041", labels=(), files=("governance/kb/decision-log.md", "src/cli/x.py"))
    assert status["title"] == "FAIL" and status["lane label"] == "FAIL"


def test_deleted_tests_are_pointed_out():
    status, results = check(files=(("D", "tests/test_import.py"), ("M", "src/cli/main.py"), ("D", "src/cli/old.py")))
    assert status["tests"] == "WARN" and "tests/test_import.py" in results[-1]["message"] and "old.py" not in results[-1]["message"]


@pytest.mark.parametrize("glob,path,hit", [
    ("src/cli/**", "src/cli/a.py", True), ("src/cli/**", "src/cli/sub/a.py", True), ("src/cli/**", "src/client/a.py", False),
    ("bin/*", "bin/tool", True), ("bin/*", "bin/sub/tool", False), ("*.md", "README.md", True), ("*.md", "docs/a.md", False),
    ("**/*.sql", "db/migrations/1.sql", True), ("**/*.sql", "1.sql", True), ("src/?.py", "src/a.py", True), ("src/?.py", "src/ab.py", False),
    ("a.b/**", "aXb/c", False),
])
def test_globs(glob, path, hit):
    assert pr_checks.matches(path, [glob]) is hit


def test_pr_checks_command_line(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps(CFG))
    (tmp_path / "files").write_text("M\tsrc/cli/main.py\nR100\tsrc/cli/old.py\tsrc/api/new.py\nD\ttests/test_x.py\n")
    (tmp_path / "commits").write_text("work\n\nFixes #4\n")
    args = ["--config", tmp_path / "c.json", "--labels", "lane:cli, risk:low", "--files", tmp_path / "files", "--commits", tmp_path / "commits"]
    r = run("pr_checks.py", *args, "--title", "cli: add import (#12)", "--json")
    by = {x["check"]: x["status"] for x in json.loads(r.stdout)}
    assert r.returncode == 1 and by["commits"] == "FAIL" and by["title"] == "ok" and by["unowned"] == "WARN" and by["tests"] == "WARN"
    assert run("pr_checks.py", "--config", tmp_path / "missing.json", "--title", "x", "--files", tmp_path / "files", "--commits", tmp_path / "commits").returncode == 2


# ---- repo_readiness.py -------------------------------------------------------------------------------

def make(root, files: dict[str, str]):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


READY = {
    "pyproject.toml": '[project]\nname = "x"\n[project.scripts]\nx = "x.cli:main"\n[tool.ruff]\nline-length = 100\n[tool.mypy]\nstrict = true\n',
    "tests/test_x.py": "def test_x():\n    assert True\n",
    ".github/workflows/ci.yml": "on: [pull_request]\njobs: {}\n",
    "src/x/cli.py": "def main():\n    pass\n",
}


def test_readiness_levels(tmp_path):
    assert repo_readiness.assess(make(tmp_path / "ready", READY))["level"] == "ready"
    one = dict(READY); del one[".github/workflows/ci.yml"]
    r = repo_readiness.assess(make(tmp_path / "one", one))
    assert r["level"] == "one gap" and "ci" in r["missing"]
    r = repo_readiness.assess(make(tmp_path / "bare", {"src/sync.py": "print(1)\n", "README.md": "# x\n"}))
    assert r["level"] == "foundations missing" and {"ci", "tests", "lint"} <= set(r["missing"])
    assert any("max_concurrent_lanes 1" in a for a in r["advice"]) and any("kb/verification.md" in a for a in r["advice"])
    (tmp_path / "empty").mkdir()
    assert repo_readiness.assess(tmp_path / "empty")["level"] == "empty"


def test_readiness_details(tmp_path):
    # a workflow that never runs on pull requests does not count as CI for PRs
    r = repo_readiness.assess(make(tmp_path / "a", {**READY, ".github/workflows/ci.yml": "on: [push]\njobs: {}\n"}))
    assert "ci" in r["missing"] and any("none runs on pull_request" in a for a in r["advice"])
    # node: the placeholder test script is not a test; vendored folders are not the project's tests
    node = {"package.json": json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1', "dev": "vite"},
                                         "devDependencies": {"eslint": "9", "typescript": "5"}}),
            "node_modules/dep/tests/a.test.js": "x", "src/app.ts": "export {}\n"}
    r = repo_readiness.assess(make(tmp_path / "b", node))
    assert "tests" in r["missing"] and r["found"]["lint"] == ["package.json: eslint"] and r["found"]["types"] and r["found"]["run"]
    node["src/app.test.ts"] = "test('x', () => {})\n"
    assert "tests" not in repo_readiness.assess(make(tmp_path / "c", node))["missing"]


def test_readiness_command_line(tmp_path):
    make(tmp_path / "r", READY)
    r = run("repo_readiness.py", tmp_path / "r", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["level"] == "ready"
    plain = run("repo_readiness.py", tmp_path / "r")
    assert "Level: ready" in plain.stdout and "not how good it is" in plain.stdout
    assert run("repo_readiness.py", tmp_path / "nope").returncode == 2
    before = sorted(p.as_posix() for p in (tmp_path / "r").rglob("*"))
    run("repo_readiness.py", tmp_path / "r")
    assert sorted(p.as_posix() for p in (tmp_path / "r").rglob("*")) == before  # read-only


# ---- ledger: merge gate, reverts, repeated findings ----------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def entries(w, rounds: dict[str, str], prs=(12,), reverts: dict[str, str] | None = None):
    base = w.ws / "ledger"
    for sub in ("prs", "rounds", "reverts"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    for n in prs:
        (base / "prs" / f"pr-{n}.yaml").write_text(f'pr: {n}\nopened: 2026-01-31\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n')
    for name, body in rounds.items():
        (base / "rounds" / f"{name}.yaml").write_text(body)
    for name, body in (reverts or {}).items():
        (base / "reverts" / f"{name}.yaml").write_text(body)


def round_entry(pr, k, must, verdict, critical="no", merged="", kinds=""):
    crit = f"critical: {critical}\n" if k == 1 and critical else ""
    return (f"pr: {pr}\nround: {k}\ndate: 2026-02-0{k}\nthread: review-1\nhead: abc{k}\n{crit}verdict: {verdict}\nmust_fix: {must}\n"
            f'should_fix: 0\nkinds: "{kinds}"\nreport: plans/review-pr{pr}-round{k}.md\nmerged: "{merged}"\n')


def test_merge_gate(w):
    w.generate()
    w.scaffold()
    entries(w, {"pr12-round1": round_entry(12, 1, 2, "changes_requested")})
    r = ledger(w, "gate", "12")
    assert r.returncode == 1 and "must not be merged" in r.stdout and "2 open must-fix finding(s)" in r.stdout and "not approved" in r.stdout
    entries(w, {"pr12-round2": round_entry(12, 2, 0, "approved")})
    r = ledger(w, "gate", "#12")
    assert r.returncode == 0 and "may be merged" in r.stdout and "confirmed non-critical" in r.stdout and "head abc2" in r.stdout
    # a critical PR needs the coordinator
    entries(w, {"pr12-round1": round_entry(12, 1, 2, "changes_requested", critical="yes")})
    assert "the coordinator (the PR is critical)" in ledger(w, "gate", "12").stdout
    # round 1 without the reviewer's finding on criticality
    entries(w, {"pr12-round1": round_entry(12, 1, 2, "changes_requested", critical="")})
    r = ledger(w, "gate", "12")
    assert r.returncode == 1 and "CRIT-03" in r.stdout
    # already merged, no rounds at all, no PR entry, no number
    entries(w, {"pr12-round1": round_entry(12, 1, 0, "approved"), "pr12-round2": round_entry(12, 2, 0, "approved", merged="5b7e1c9")})
    assert ledger(w, "gate", "12").returncode == 1 and "already merged" in ledger(w, "gate", "12").stdout
    assert ledger(w, "gate", "99").returncode == 1 and "no review round is recorded" in ledger(w, "gate", "99").stdout
    assert ledger(w, "gate").returncode == 2 and ledger(w, "gate", "twelve").returncode == 2


def test_reverts_and_repeated_finding_kinds(w):
    w.generate()
    w.scaffold()
    entries(w, {
        "pr12-round1": round_entry(12, 1, 1, "changes_requested", kinds="timer-workaround, missing-test"),
        "pr12-round2": round_entry(12, 2, 0, "approved", merged="aaa111"),
        "pr13-round1": round_entry(13, 1, 0, "approved", merged="bbb222", kinds="Timer-Workaround"),
        "pr14-round1": round_entry(14, 1, 0, "approved", merged="ccc333", kinds="naming"),
    }, prs=(12, 13, 14), reverts={"pr-13": 'pr: 13\ndate: 2026-02-09\nby: "#19"\nreason: "broke files with a BOM"\n'})
    assert ledger(w, "check").returncode == 0
    stats = ledger(w, "stats").stdout
    assert "Reverted: 1 of 3 merged PRs (33.3%): #13." in stats
    assert "timer-workaround: #12, #13" in stats and "missing-test" not in stats.split("Finding kinds")[1] and "naming:" not in stats
    assert "reverted by #19" in ledger(w, "table").stdout
    # a revert entry must point at a PR that was merged, and be complete
    entries(w, {}, prs=(12, 13, 14), reverts={"pr-15": "pr: 15\ndate: 2026-02-09\n"})
    bad = ledger(w, "check")
    assert bad.returncode == 1 and "`by` is missing" in bad.stdout and "PR #15 has no round entry that records a merge" in bad.stdout


def test_stats_without_reverts_or_kinds(w):
    w.generate()
    w.scaffold()
    entries(w, {"pr12-round1": round_entry(12, 1, 0, "approved", merged="aaa111")})
    stats = ledger(w, "stats").stdout
    assert "Reverted: 0 of 1 merged PRs (0.0%)." in stats and "Finding kinds seen in more than one PR: none." in stats
