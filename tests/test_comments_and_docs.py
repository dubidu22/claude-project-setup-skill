"""PR-05: comments say why and nothing else; no file that nobody asked for (new markdown only under doc_paths)."""

from __future__ import annotations

import json
import sys

import pytest
import yaml

from conftest import SKILL, notable, run

sys.path.insert(0, str(SKILL / "scripts"))
import pr_checks  # noqa: E402

CFG = {
    "ownership_labels": ["lane:cli", "lane:docs"], "label_paths": {}, "open_labels": [], "lock_label": "", "locked_label": "",
    "critical_paths": [], "governance_paths": ["governance/**"],
    "doc_paths": ["docs/**", "**/README.md", "CHANGELOG.md", ".github/**"],
}


def check(changes, cfg=CFG, exemptions=None, diff=None):
    results = pr_checks.run_checks(cfg, "cli: add import (#12)", ["lane:cli"], changes, "add import\n", exemptions, None, diff)
    return {r["check"]: r["status"] for r in results}, {r["check"]: r["message"] for r in results}


# ---- the rule and the setting -----------------------------------------------------------------------------

def test_rule_and_setting_are_generated(w):
    assert w.generate().returncode == 0
    rule = w.rule("PR-05")
    for phrase in ("says why the code is as it is", "never what it does, what changed or who asked", "narrating-comment",
                   "Create no file the rules, the approved plan or the owner did not name", "project_profile.doc_paths",
                   "PR body or the ledger"):
        assert phrase in rule, phrase
    assert len(rule) <= 450
    rules = yaml.safe_load(w.rules_text())
    assert rules["project_profile"]["doc_paths"] == ["docs/**", "**/README.md", "CHANGELOG.md", "CONTRIBUTING.md", ".github/**"]
    for role, present in (("implementation", True), ("review", True), ("coordinator", False)):
        ids = {r["id"] for r in yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())["rules"]}
        assert ("PR-05" in ids) is present, role
    assert not notable(w.audit("--json"))


def test_doc_paths_can_be_set_and_survive_the_round_trip(w, tmp_path):
    assert w.generate(None, 'doc_paths=["handbook/**","**/README.md"]').returncode == 0
    assert yaml.safe_load(w.rules_text())["project_profile"]["doc_paths"] == ["handbook/**", "**/README.md"]
    out = tmp_path / "derived.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert json.loads(out.read_text())["doc_paths"] == ["handbook/**", "**/README.md"]
    before = w.rules_text()
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.rules_text() == before
    assert w.generate(None, "doc_paths=[]").returncode == 0  # no markdown anywhere without the plan: allowed
    assert yaml.safe_load(w.rules_text())["project_profile"]["doc_paths"] == []


@pytest.mark.parametrize("value", ['["**"]', '["**/*.md"]', '["*.md"]', '["/docs/**"]', '["../docs/**"]', '[" docs/**"]', '[""]', '"docs/**"'])
def test_doc_paths_that_allow_everything_or_are_malformed_are_refused(w, value):
    r = w.generate(None, f"doc_paths={value}")
    assert r.returncode == 2 and "doc_paths" in r.stderr
    assert not w.rules.exists()


def test_scaffold_passes_doc_paths_and_the_diff_to_the_checks(w):
    assert w.generate(None, 'doc_paths=["handbook/**"]').returncode == 0
    assert w.scaffold("--github").returncode == 0
    gh = w.ws / "github-setup"
    assert json.loads((gh / "pr-checks.json").read_text())["doc_paths"] == ["handbook/**"]
    workflow = (gh / "pr-checks-workflow.yml").read_text()
    assert 'git diff "$PR_BASE...$PR_HEAD" > "$RUNNER_TEMP/diff.txt"' in workflow and '--diff "$RUNNER_TEMP/diff.txt"' in workflow
    assert yaml.safe_load(workflow)["jobs"]["checks"]["steps"]  # still valid YAML
    assert "PR-05" in (gh / "README.md").read_text()


# ---- new markdown files -------------------------------------------------------------------------------

def test_new_markdown_outside_the_documentation_paths_fails():
    status, msg = check([("A", "SUMMARY.md"), ("A", "src/cli/NOTES.md"), ("A", "src/IMPLEMENTATION.MD"), ("M", "src/cli/main.py")])
    assert status["new docs"] == "FAIL"
    for name in ("SUMMARY.md", "src/cli/NOTES.md", "src/IMPLEMENTATION.MD"):
        assert name in msg["new docs"]
    assert "PR-05" in msg["new docs"] and "PR body or the ledger" in msg["new docs"]


def test_markdown_in_allowed_places_changed_files_and_governance_pass():
    status, _ = check([
        ("A", "docs/usage.md"), ("A", "README.md"), ("A", "packages/core/README.md"), ("A", "CHANGELOG.md"), ("A", ".github/pull_request_template.md"),
        ("M", "ARCHITECTURE.md"),            # an existing file may be edited anywhere
        ("D", "OLD_NOTES.md"),               # and deleted
        ("R", "docs/renamed.md"),
        ("A", "governance/plans/plan-003.md"),  # the governance workspace: files the rules name
        ("A", "src/cli/main.py"), ("A", "notes.txt"),
    ])
    assert status["new docs"] == "ok"


def test_plain_path_input_cannot_tell_new_from_changed():
    changes = pr_checks.read_changes("SUMMARY.md\nsrc/a.py\n")
    assert check(changes)[0]["new docs"] == "ok"  # documented: needs --name-status input
    changes = pr_checks.read_changes("A\tSUMMARY.md\nM\tsrc/a.py\nR100\tOLD.md\tNEW.md\n")
    status, msg = check(changes)
    assert status["new docs"] == "FAIL" and "SUMMARY.md" in msg["new docs"] and "NEW.md" not in msg["new docs"]


def test_new_docs_check_needs_the_setting_and_honours_an_empty_list():
    old = {k: v for k, v in CFG.items() if k != "doc_paths"}
    assert "new docs" not in check([("A", "SUMMARY.md")], cfg=old)[0]  # a config from before this check
    status, msg = check([("A", "docs/usage.md")], cfg={**CFG, "doc_paths": []})
    assert status["new docs"] == "FAIL" and "none set" in msg["new docs"]


def test_a_document_the_plan_names_goes_through_an_exemption():
    ex = [{"check": "docs", "paths": ["ARCHITECTURE.md"], "kind": "sanctioned", "reason": "Named in plan-004 as the architecture overview"}]
    assert pr_checks.exemption_errors(ex) == []
    status, msg = check([("A", "ARCHITECTURE.md"), ("A", "TODO.md")], exemptions=ex)
    assert status["new docs"] == "FAIL" and "TODO.md" in msg["new docs"] and "ARCHITECTURE.md" not in msg["new docs"]
    status, _ = check([("A", "ARCHITECTURE.md")], exemptions=ex)
    assert status["new docs"] == "ok" and status["exemption"] == "ok"


# ---- comments ---------------------------------------------------------------------------------------------

DIFF = """\
diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +10,9 @@
 x = 1
+# Previously this used a list; now uses a set
+#!/usr/bin/env python3
+y = 2  # now uses a trailing comment the check does not see
+# Retry three times: the vendor API drops the first call after an idle hour
-# Removed the old loader
+    // TODO clean this up
+    // TODO(#12) clean this up
+ * Refactored per review feedback
+# as requested by the owner
diff --git a/NOTES.md b/NOTES.md
new file mode 100644
--- /dev/null
+++ b/NOTES.md
@@ -0,0 +1,2 @@
+# Previously
+- no longer needed
diff --git a/governance/tools/x.py b/governance/tools/x.py
--- a/governance/tools/x.py
+++ b/governance/tools/x.py
@@ -5,0 +6,1 @@
+# previously in the skill
diff --git a/src/gone.py b/src/gone.py
deleted file mode 100644
--- a/src/gone.py
+++ /dev/null
@@ -1,1 +0,0 @@
-# previously here
"""


def test_comment_notes_find_narration_and_bare_todos_with_line_numbers():
    notes = pr_checks.comment_notes(DIFF, ["governance/**"])
    assert notes == [
        "src/a.py:11: Previously this used a list; now uses a set",
        "src/a.py:15: TODO clean this up (no issue number)",
        "src/a.py:17: Refactored per review feedback",
        "src/a.py:18: as requested by the owner",
    ]


def test_comment_check_warns_and_never_fails():
    status, msg = check([("M", "src/a.py")], diff=DIFF)
    assert status["comments"] == "WARN" and "src/a.py:11" in msg["comments"] and "The reviewer decides (PR-05)" in msg["comments"]
    assert "FAIL" not in status.values()
    clean = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,2 @@\n x = 1\n+# The vendor API drops the first call after an idle hour\n"
    assert check([("M", "src/a.py")], diff=clean)[0]["comments"] == "ok"
    assert "comments" not in check([("M", "src/a.py")])[0]  # no diff given: the check does not run


def test_long_lists_of_comment_notes_are_cut():
    body = "".join(f"+# previously value {i}\n" for i in range(30))
    diff = f"--- a/src/a.py\n+++ b/src/a.py\n@@ -0,0 +1,30 @@\n{body}"
    _, msg = check([("M", "src/a.py")], diff=diff)
    assert "(and 18 more)" in msg["comments"] and "src/a.py:12" in msg["comments"] and "src/a.py:13:" not in msg["comments"]


@pytest.mark.parametrize("line, hit", [
    ("# Now uses the shared pool", True), ("// Changed from 5 to 10", True), ("# We now cache the result", True),
    ("-- Fixed the off-by-one", True), ("<!-- Updated the layout per feedback -->", True), ("# FIXME", True),
    ("# FIXME: see https://example.test/org/repo/issues/9", False), ("# The pool is shared: one connection per worker", False),
    ("# Cache for an hour: upstream rate limit is 60 per hour", False), ("#include <stdio.h>", False),
    ("x = previously(1)", False), ("# users can no longer be empty here: validated in parse()", True),  # a known false alarm: it only warns
])
def test_narration_word_list(line, hit):
    diff = f"--- a/src/a.c\n+++ b/src/a.c\n@@ -0,0 +1,1 @@\n+{line}\n"
    assert bool(pr_checks.comment_notes(diff, [])) is hit


def test_command_line_with_diff(tmp_path):
    (tmp_path / "pr-checks.json").write_text(json.dumps(CFG))
    (tmp_path / "changed.txt").write_text("M\tsrc/a.py\nA\tSUMMARY.md\n")
    (tmp_path / "commits.txt").write_text("add import\n")
    (tmp_path / "diff.txt").write_text(DIFF)
    args = ["--config", tmp_path / "pr-checks.json", "--title", "cli: add import (#12)", "--labels", "lane:cli",
            "--files", tmp_path / "changed.txt", "--commits", tmp_path / "commits.txt"]
    r = run("pr_checks.py", *args, "--diff", tmp_path / "diff.txt")
    assert r.returncode == 1 and "FAIL new docs" in r.stdout and "WARN comments" in r.stdout
    (tmp_path / "changed.txt").write_text("M\tsrc/a.py\n")
    r = run("pr_checks.py", *args, "--diff", tmp_path / "diff.txt")
    assert r.returncode == 0 and "WARN comments" in r.stdout  # a warning alone does not fail the check
    assert run("pr_checks.py", *args, "--diff", tmp_path / "missing.txt").returncode == 2


def test_reference_explains_both_rules():
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Comments say why, and only why", "No file that nobody asked for", "PR-01..05", "`doc_paths`", "narrating-comment"):
        assert phrase in model, phrase
    assert "doc_paths" in (SKILL / "init.md").read_text()
    assert "narrating-comment" in (SKILL / "assets" / "templates" / "ledger" / "README.md").read_text()
