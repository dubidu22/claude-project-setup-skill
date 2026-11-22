"""Lessons from Druthulu/ProjectArchitect: checks are proved, workers hand back with one word, leftovers get a
decision, the audit starts from flags, each role has a reading list."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import SKILL, findings, notable, run


def codes(result, severity=None):
    return {(f["code"], f["message"]) for f in findings(result) if severity in (None, f["severity"])}


def has(result, code, needle):
    return any(c == code and needle in m for c, m in codes(result))

sys.path.insert(0, str(SKILL / "scripts"))
import pr_checks  # noqa: E402

REPO = SKILL.parent
FULL = {
    "ownership_labels": ["lane:core", "lane:cli", "lane:infra", "lane:docs"],
    "label_paths": {"lane:cli": ["src/cli/**"], "lane:core": ["src/core/**"]},
    "open_labels": ["lane:docs"], "lock_label": "lane:infra", "locked_label": "lane:core",
    "critical_paths": ["src/core/**"], "governance_paths": ["governance/**"],
    "doc_paths": ["docs/**", "**/README.md"],
}


def rule_ids(w, role):
    return {r["id"] for r in yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())["rules"]}


# ---- rules -------------------------------------------------------------------------------------------

def test_new_rules_are_generated_scoped_and_short(w):
    assert w.generate().returncode == 0
    thr15 = w.rule("THR-15")
    for phrase in ("starts with one word: done, question, blocked, review or handoff", "two attempts failed for different reasons",
                   "name its id", "destructive git operation, never attempted", "Recommended: <one action>", "ledger entry"):
        assert phrase in thr15, phrase
    thr16 = w.rule("THR-16")
    for phrase in ("ledger_tool.py triage", "ledger/deferred/", "planned (the issue)", "postponed (reason and until when)",
                   "dropped (the owner's word and the reason)", "No batch starts"):
        assert phrase in thr16, phrase
    ver02 = w.rule("VER-02")
    for phrase in ("failed once on a case known to be wrong", "pr_checks.py --self-test", "looks too good", "is a claim"):
        assert phrase in ver02, phrase
    role15 = w.rule("ROLE-15")
    for phrase in ("ledger_tool.py flags", "not from thread chats", "check (", "rule (", "split (", "owner (", "leave (", "builds nothing"):
        assert phrase in role15, phrase
    pr06 = w.rule("PR-06")
    assert "at the size it was asked" in pr06 and "three lines in the PR body" in pr06
    assert "what you tried and ruled out, with the evidence" in w.rule("THR-07")
    for rid in ("THR-15", "THR-16", "VER-02", "ROLE-15", "PR-06", "THR-07"):
        assert len(w.rule(rid)) <= 450, (rid, len(w.rule(rid)))
    assert {"THR-15"} <= rule_ids(w, "implementation") and not ({"VER-02", "PR-06", "THR-16", "ROLE-15"} & rule_ids(w, "implementation"))
    assert {"THR-15", "VER-02", "PR-06"} <= rule_ids(w, "review")
    assert {"THR-16"} <= rule_ids(w, "coordinator") and "THR-15" not in rule_ids(w, "coordinator")
    assert {"ROLE-15", "VER-02"} <= rule_ids(w, "audit")
    assert not notable(w.audit("--json"))


@pytest.mark.parametrize("sets", [(), ("model_preset=economy", "profile_key=frugal"), ("dispatcher=true",), ("workspace_root=./governance",)])
def test_every_variant_stays_within_the_rule_load(w, sets):
    assert w.generate(None, *sets).returncode == 0
    found = [f for f in notable(w.audit("--json")) if f["code"] != "A14"]
    assert not found, (sets, found)
    for extract in (w.ws / "rules").glob("*.yaml"):
        assert len(yaml.safe_load(extract.read_text())["rules"]) <= 40, extract.name


def test_role_extracts_carry_a_reading_list(w):
    assert w.generate().returncode == 0
    impl = yaml.safe_load((w.ws / "rules" / "implementation.yaml").read_text())
    assert any("contract_tool.py brief" in x for x in impl["start_reading"]) and any("your plan" in x for x in impl["start_reading"])
    assert any("other lanes' plans" in x for x in impl["leave_unread"]) and any("full ruleset" in x for x in impl["leave_unread"])
    review = yaml.safe_load((w.ws / "rules" / "review.yaml").read_text())
    assert review["start_reading"][0] == "the pull request's diff" and "the implementation thread's chat" in review["leave_unread"]
    audit = yaml.safe_load((w.ws / "rules" / "audit.yaml").read_text())
    assert any("ledger_tool.py flags" in x for x in audit["start_reading"]) and "thread chats" in audit["leave_unread"]
    coordinator = yaml.safe_load((w.ws / "rules" / "coordinator.yaml").read_text())
    assert any("triage" in x for x in coordinator["start_reading"])
    for extract in (w.ws / "rules").glob("*.yaml"):
        data = yaml.safe_load(extract.read_text())
        assert data["start_reading"] and data["leave_unread"], extract.name
    # the lists follow the workspace
    assert w.generate(None, "workspace_root=./governance").returncode == 0
    impl = yaml.safe_load((w.ws / "rules" / "implementation.yaml").read_text())
    assert any("./governance/tools/contract_tool.py brief" in x for x in impl["start_reading"])
    assert "/mnt/project-files" not in (w.ws / "rules" / "implementation.yaml").read_text()
    # and the extract check still passes: the lists are not rules
    assert not has(w.audit("--json"), "A12", "")


def test_reading_list_without_contracts_names_no_contract_tool(w):
    assert w.generate(None, "acceptance_contracts=false").returncode == 0
    text = (w.ws / "rules" / "implementation.yaml").read_text() + (w.ws / "rules" / "review.yaml").read_text()
    assert "contract_tool.py" not in text and not (w.ws / "rules" / "specify.yaml").exists()


def test_audit_lists_checks_never_seen_to_fail(w):
    inv = json.dumps(["The schema stays backwards compatible. [check: tests/test_schema_compat.py]",
                      "Imports follow the layers. [check: ci:lint-imports (proved: PR #12)]",
                      "Names are kind."])
    assert w.generate(None, f"custom_invariants={inv}").returncode == 0
    a16 = [m for c, m in codes(w.audit("--json")) if c == "A16"]
    assert len(a16) == 1
    text = w.rules_text()
    unproved = next(l for l in text.splitlines() if "test_schema_compat" in l)
    proved = next(l for l in text.splitlines() if "ci:lint-imports" in l)
    assert "(proved: PR #12)" in proved and "(proved:" not in unproved
    ids = {i for i in ("INV-01", "INV-02", "INV-03", "INV-04", "INV-05", "INV-06") if i in a16[0]}
    by_id = {r["id"]: r["rule"] for v in yaml.safe_load(text).values() if isinstance(v, list) for r in v if isinstance(r, dict) and "id" in r}
    assert all("(proved:" not in by_id[i] and "review only" not in by_id[i] for i in ids)
    assert not any("ci:lint-imports" in by_id[i] or "Names are kind" in by_id[i] for i in ids)
    assert [f for f in findings(w.audit("--json")) if f["code"] == "A16"][0]["severity"] == "INFO"
    # the proof note survives the round trip
    out = w.ws.parent / "derived.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    assert any("(proved: PR #12)" in x for x in json.loads(out.read_text())["custom_invariants"])


# ---- the self-test of the pull-request checks ---------------------------------------------------------

def test_self_test_proves_every_configured_check():
    results = {r["check"]: r["status"] for r in pr_checks.self_test(FULL)}
    assert results == {c: "ok" for c in ("commits", "title", "lane label", "ownership", "lock", "critical", "tests", "new docs",
                                         "dependencies", "comments")}


def test_self_test_says_off_for_what_is_not_configured():
    bare = {"ownership_labels": [], "label_paths": {}, "open_labels": [], "lock_label": "", "locked_label": "", "critical_paths": [],
            "governance_paths": []}
    results = {r["check"]: r["status"] for r in pr_checks.self_test(bare)}
    assert results["commits"] == results["title"] == results["tests"] == results["comments"] == results["dependencies"] == "ok"
    assert all(results[c] == "off" for c in ("lane label", "ownership", "lock", "critical", "new docs"))
    one = {**FULL, "label_paths": {"lane:cli": ["src/cli/**"]}}
    results = {r["check"]: r for r in pr_checks.self_test(one)}
    assert results["ownership"]["status"] == "off" and "fewer than two labels" in results["ownership"]["message"]


@pytest.mark.parametrize("change, dead", [
    ({"doc_paths": ["**/*.md", "*.md", "SELFTEST-KNOWN-BAD-NOTES.md"]}, "new docs"),      # everything is a documentation path
    ({"governance_paths": ["src/**", "selftest-known-bad/**"]}, "title"),                  # everything counts as governance
    ({"label_paths": {"lane:cli": ["src/**"], "lane:core": ["src/**"]}}, None),              # overlapping globs: off, not dead
])
def test_self_test_finds_a_check_that_cannot_fail(change, dead):
    results = {r["check"]: r["status"] for r in pr_checks.self_test({**FULL, **change})}
    if dead:
        assert results[dead] == "DEAD", results
    else:
        assert results["ownership"] == "off" and "DEAD" not in results.values()


def test_self_test_on_the_command_line(tmp_path):
    cfg = tmp_path / "pr-checks.json"
    cfg.write_text(json.dumps(FULL))
    r = run("pr_checks.py", "--config", cfg, "--self-test")
    assert r.returncode == 0 and "10 check(s) proved, 0 not configured, 0 dead." in r.stdout
    assert "ok   ownership: fails on the known-bad pull request, as it should" in r.stdout
    cfg.write_text(json.dumps({**FULL, "doc_paths": ["**/*.md", "*.md", "SELFTEST-KNOWN-BAD-NOTES.md"]}))
    r = run("pr_checks.py", "--config", cfg, "--self-test")
    assert r.returncode == 1 and "DEAD new docs" in r.stdout and "1 dead." in r.stdout
    data = json.loads(run("pr_checks.py", "--config", cfg, "--self-test", "--json").stdout)
    assert {"check": "new docs", "status": "DEAD"}.items() <= next(d for d in data if d["check"] == "new docs").items()
    cfg.write_text("not json")
    assert run("pr_checks.py", "--config", cfg, "--self-test").returncode == 2
    cfg.write_text(json.dumps(FULL))
    r = run("pr_checks.py", "--config", cfg)  # the normal mode still needs its inputs
    assert r.returncode == 2 and "--title, --files and --commits are required" in r.stderr


def test_self_test_passes_on_a_scaffolded_setup_and_the_workflow_runs_it(w):
    assert w.generate(None, "workspace_root=./governance", 'label_paths=["lane:cli=src/cli/**","lane:core=src/core/**"]',
                      'critical_paths=["src/core/**"]').returncode == 0
    assert w.scaffold("--github").returncode == 0
    gh = w.ws / "github-setup"
    r = subprocess.run([sys.executable, str(gh / "pr_checks.py"), "--config", str(gh / "pr-checks.json"), "--self-test"], capture_output=True, text=True)
    assert r.returncode == 0 and "0 dead." in r.stdout and "DEAD" not in r.stdout
    workflow = (gh / "pr-checks-workflow.yml").read_text()
    steps = yaml.safe_load(workflow)["jobs"]["checks"]["steps"]
    script = next(s["run"] for s in steps if "pr_checks.py" in s.get("run", ""))
    assert script.index("--self-test") < script.index("--title")
    assert "--self-test" in (gh / "README.md").read_text() and "VER-02" in (gh / "README.md").read_text()


def test_dependency_manifests_are_listed_for_the_reviewer():
    def status(changes):
        res = pr_checks.run_checks(FULL, "cli: add import (#12)", ["lane:cli"], changes, "x\n")
        return {r["check"]: r for r in res}
    got = status([("M", "src/cli/package.json"), ("A", "requirements-dev.txt"), ("M", "src/cli/main.py")])
    assert got["dependencies"]["status"] == "WARN" and "src/cli/package.json, requirements-dev.txt" in got["dependencies"]["message"]
    assert "PR-06" in got["dependencies"]["message"]
    assert "dependencies" not in status([("M", "src/cli/main.py"), ("D", "old/package.json"), ("M", "docs/requirements.md")])
    assert "dependencies" not in status([("M", "governance/tools/pyproject.toml")])
    for name in ("pyproject.toml", "go.mod", "Cargo.toml", "app/build.gradle.kts", "Gemfile", "App.csproj"):
        assert "dependencies" in status([("M", name)]), name


# ---- hand-backs, triage and flags in the ledger -------------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def put(w, sub, name, body):
    folder = w.ws / "ledger" / sub
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(body)


def pr_entry(n, extra=""):
    return f'pr: {n}\nopened: 2026-01-31\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n{extra}'


def round_entry(pr, k, must, verdict, date, merged="", should=0, kinds=""):
    crit = "critical: no\n" if k == 1 else ""
    return (f"pr: {pr}\nround: {k}\ndate: {date}\nthread: review-1\nhead: 3f9c2a{k}\n{crit}verdict: {verdict}\nmust_fix: {must}\n"
            f'should_fix: {should}\nkinds: "{kinds}"\nreport: plans/review-pr{pr}-round{k}.md\nmerged: "{merged}"\n')


def deferred(pr, decision="open", extra=""):
    return f'pr: {pr}\ndate: 2026-02-03\nwhat: "S2: the dialog forgets the last folder"\ndecision: {decision}\n{extra}'


@pytest.fixture
def led(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    (w.ws / "ledger" / "deferred" / "since.txt").write_text("# test\n2026-02-01\n")
    put(w, "prs", "pr-12", pr_entry(12))
    put(w, "rounds", "pr12-round1", round_entry(12, 1, 0, "approved", "2026-02-02"))
    return w


def test_scaffold_writes_the_triage_start_date_once(w):
    import re
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    since = w.ws / "ledger" / "deferred" / "since.txt"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", since.read_text().strip().splitlines()[-1])
    since.write_text("# kept\n2025-12-24\n")
    assert w.scaffold("--force").returncode == 0 and w.scaffold("--refresh").returncode == 0
    assert since.read_text() == "# kept\n2025-12-24\n"


def test_an_open_handback_stops_the_gate(led):
    assert ledger(led, "gate", "12").returncode == 0
    put(led, "prs", "pr-12", pr_entry(12, 'handback: blocked\nrecommended: "Ask the owner whether the old import format must stay"\n'))
    r = ledger(led, "gate", "12")
    assert r.returncode == 1 and "handed back `blocked` (THR-15)" in r.stdout and "old import format" in r.stdout
    assert ledger(led, "check").returncode == 0
    assert "Hand-backs waiting (THR-15): #12 blocked." in ledger(led, "stats").stdout
    for word in ("question", "review"):
        put(led, "prs", "pr-12", pr_entry(12, f'handback: {word}\nrecommended: "Decide the scope of the importer"\n'))
        assert ledger(led, "gate", "12").returncode == 1
    for word in ("done", "handoff"):
        put(led, "prs", "pr-12", pr_entry(12, f"handback: {word}\n"))
        assert ledger(led, "gate", "12").returncode == 0 and ledger(led, "check").returncode == 0
    assert "Hand-backs waiting" not in ledger(led, "stats").stdout


@pytest.mark.parametrize("extra, word", [
    ("handback: stuck\n", "`handback` must be one of done, question, blocked, review, handoff"),
    ("handback: blocked\n", "carries `recommended`"),
    ('handback: question\nrecommended: "ask"\n', "carries `recommended`"),
])
def test_malformed_handbacks_are_problems(led, extra, word):
    put(led, "prs", "pr-12", pr_entry(12, extra))
    r = ledger(led, "check")
    assert r.returncode == 1 and word in r.stdout


def test_triage_refuses_until_every_leftover_has_a_decision(led):
    assert ledger(led, "triage").returncode == 0
    # the PR is merged with two should-fix findings open and nothing recorded
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 0, "approved", "2026-02-02", merged="5b7e1c9", should=2))
    r = ledger(led, "triage")
    assert r.returncode == 1 and "PR #12 was merged with 2 should-fix finding(s) open, 0 recorded" in r.stdout
    assert "plans/review-pr12-round1.md" in r.stdout
    put(led, "deferred", "pr12-1", deferred(12))
    r = ledger(led, "triage")
    assert r.returncode == 1 and "1 recorded" in r.stdout and "deferred/pr12-1.yaml (PR #12)" in r.stdout and "no decision yet" in r.stdout
    put(led, "deferred", "pr12-2", deferred(12, "planned", "issue: 40\n"))
    r = ledger(led, "triage")
    assert r.returncode == 1 and "Settled (1)" in r.stdout and "planned in #40" in r.stdout and "recorded in deferred" not in r.stdout
    put(led, "deferred", "pr12-1", deferred(12, "postponed", 'reason: "Needs the settings store from milestone 3"\nuntil: milestone 3\n'))
    r = ledger(led, "triage")
    assert r.returncode == 0 and "Nothing is waiting for a decision." in r.stdout and "postponed until milestone 3" in r.stdout
    assert ledger(led, "check").returncode == 0
    put(led, "deferred", "pr12-1", deferred(12, "dropped", 'reason: "The dialog is replaced in the next release"\nby: "owner, chat 2026-02-04"\n'))
    assert ledger(led, "triage").returncode == 0 and "dropped by owner, chat 2026-02-04" in ledger(led, "triage").stdout


@pytest.mark.parametrize("decision, extra, word", [
    ("planned", "", "names the `issue`"),
    ("planned", "issue: soon\n", "names the `issue`"),
    ("postponed", 'reason: "Needs the settings store from milestone 3"\n', "says `until` when"),
    ("postponed", "until: milestone 3\n", "says why in `reason`"),
    ("dropped", 'reason: "The dialog is replaced in the next release"\n', "the owner's call"),
    ("dropped", 'reason: "The dialog is replaced in the next release"\nby: coordinator\n', "the owner's call"),
    ("dropped", 'reason: "no"\nby: owner\n', "says why in `reason`"),
    ("later", "", "`decision` must be one of open, fixed, planned, postponed, dropped"),
])
def test_a_decision_without_its_particulars_does_not_settle_anything(led, decision, extra, word):
    put(led, "deferred", "pr12-1", deferred(12, decision, extra))
    r = ledger(led, "triage")
    assert r.returncode == 1 and word in r.stdout
    c = ledger(led, "check")
    assert c.returncode == 1 and word in c.stdout


def test_triage_does_not_count_merges_before_the_start_date_or_unmerged_prs(led):
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 0, "approved", "2026-01-15", merged="5b7e1c9", should=3))  # before since.txt
    put(led, "prs", "pr-13", pr_entry(13))
    put(led, "rounds", "pr13-round1", round_entry(13, 1, 0, "approved", "2026-02-05", should=2))  # not merged: may still be fixed
    r = ledger(led, "triage")
    assert r.returncode == 0 and "Merges before 2026-02-01 are not counted" in r.stdout
    (led.ws / "ledger" / "deferred" / "since.txt").unlink()  # an older ledger without the marker: everything counts
    assert ledger(led, "triage").returncode == 1


def test_flags_are_derived_from_the_entries(led):
    assert ledger(led, "flags").stdout.strip() == "No flags."
    put(led, "prs", "pr-12", pr_entry(12).replace("compactions: 0", "compactions: 2") + 'handback: question\nrecommended: "Decide the scope"\n')
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 2, "changes_requested", "2026-02-02", kinds="timer-workaround"))
    put(led, "rounds", "pr12-round2", round_entry(12, 2, 1, "changes_requested", "2026-02-03"))
    put(led, "rounds", "pr12-round3", round_entry(12, 3, 0, "approved", "2026-02-04", merged="5b7e1c9", should=1))
    put(led, "prs", "pr-13", pr_entry(13))
    put(led, "rounds", "pr13-round1", round_entry(13, 1, 1, "changes_requested", "2026-02-05", kinds="timer-workaround"))
    put(led, "reverts", "pr-12", 'pr: 12\ndate: 2026-02-09\nby: review-1\nreason: "broke the import on Windows"\n')
    put(led, "overrides", "pr-13", 'pr: 13\ndate: 2026-02-06\nby: "owner, chat"\nhead: 3f9c2a1\nreason: "Hotfix for the broken release build"\n')
    out = ledger(led, "flags").stdout.splitlines()
    kinds = [l.split(" | ")[0] for l in out]
    assert kinds == ["flag: rounds", "flag: compactions", "flag: repeated-kind", "flag: revert", "flag: override", "flag: handback", "flag: untriaged"]
    assert "flag: rounds | PR #12 took 3 review rounds" in out and "flag: repeated-kind | timer-workaround in #12, #13" in out
    assert any("broke the import on Windows" in l for l in out) and any("handed back `question`: Decide the scope" in l for l in out)
    assert any(l.startswith("flag: untriaged | PR #12 was merged with 1 should-fix") for l in out)
    assert ledger(led, "flags").returncode == 0  # flags inform; they do not fail a run


def test_flags_include_a_regressed_fix(led):
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 1, "changes_requested", "2026-02-02", kinds="timer-workaround"))
    put(led, "prs", "pr-15", pr_entry(15, 'fixes_kinds: "timer-workaround"\n'))
    put(led, "rounds", "pr15-round1", round_entry(15, 1, 0, "approved", "2026-02-05", merged="bbbbbbb"))
    put(led, "prs", "pr-16", pr_entry(16))
    put(led, "rounds", "pr16-round1", round_entry(16, 1, 1, "changes_requested", "2026-02-07", kinds="timer-workaround"))
    assert "flag: regressed | timer-workaround claimed fixed by #15, back in #16" in ledger(led, "flags").stdout


# ---- templates, reference, eval guide ---------------------------------------------------------------------

def test_templates_and_reference_describe_the_mechanisms(led):
    readme = (led.ws / "ledger" / "README.md").read_text()
    for phrase in ("ledger_tool.py triage", "ledger_tool.py flags", "deferred/pr<N>-<k>.yaml", "handback:", "recommended:", "THR-15",
                   "THR-16", "ROLE-15", "deferred/since.txt"):
        assert phrase in readme, phrase
    plans = (led.ws / "plans" / "README.md").read_text()
    assert "`Ruled out:`" in plans and "`done`, `question`, `blocked`,\n`review` or `handoff`" in plans
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Proving the checks, and what is left behind", "Druthulu/ProjectArchitect", "Verify the verifier", "--self-test",
                   "A closed list of reasons to stop", "An audit in two halves", "A reading list per role", "(A16)"):
        assert phrase in model, phrase
    assert "Proof and leftovers" in (SKILL / "references" / "audit-checklist.md").read_text()
    assert "(proved: <where it was seen to fail>)" in (SKILL / "init.md").read_text()


def test_eval_guide_names_real_cases_and_is_honest():
    guide = (REPO / "eval-results" / "README.md").read_text()
    for case in ("routing-bare-invocation", "init-stage-one-waits", "specify-approval-without-hash", "audit-asked-to-fix"):
        assert case in guide and (SKILL / "evals" / case / "case.yaml").is_file(), case
    assert "No eval run has been\nrecorded here yet" in guide
    for word in ("`skill`", "`grader`", "`harness`", "unclassified"):
        assert word in guide
    assert not list((REPO / "eval-results").glob("*.json"))  # when a run is recorded, update the guide's first paragraph
    assert "eval-results/README.md" in (REPO / "README.md").read_text()
