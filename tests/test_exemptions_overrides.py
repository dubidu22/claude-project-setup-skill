"""Labelled exemptions (PR-04), one-off owner overrides (MRG-02), derived fix standing (REV-06), the fix ladder (META-03)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

from conftest import SKILL, notable, run

sys.path.insert(0, str(SKILL / "scripts"))
import ledger_tool  # noqa: E402
import pr_checks  # noqa: E402

CFG = {
    "ownership_labels": ["lane:core", "lane:cli", "lane:infra", "lane:docs"],
    "label_paths": {"lane:cli": ["src/cli/**"], "lane:docs": ["docs/**"], "lane:core": ["src/core/**"]},
    "open_labels": ["lane:docs"], "lock_label": "lane:infra", "locked_label": "lane:core",
    "critical_paths": ["src/core/**"], "governance_paths": ["governance/**"],
}
DEBT = {"check": "ownership", "paths": ["src/core/legacy/**"], "kind": "debt", "issue": 31,
        "reason": "CLI still imports the legacy loader; issue 31 moves it"}
SANCTIONED = {"check": "unowned", "paths": ["LICENSE"], "kind": "sanctioned",
              "reason": "Licence text belongs to no lane and changes only with the owner"}


def check(files, labels=("lane:cli",), exemptions=None, open_issues=None):
    results = pr_checks.run_checks(CFG, "cli: add import (#12)", list(labels), [("M", f) for f in files], "add import\n",
                                   exemptions, open_issues)
    return {r["check"]: r["status"] for r in results}, results


# ---- rules -------------------------------------------------------------------------------------------

def test_rules_carry_the_ladder_exemptions_overrides_and_fix_claims(w):
    w.generate()
    meta = w.rule("META-03")
    assert "one step up this order of strength" in meta and "a loud failure at runtime" in meta
    assert meta.index("makes the mistake impossible") < meta.index("a type") < meta.index("lint rule") < meta.index("loud failure") < meta.index("Prose is the last resort")
    rev06 = w.rule("REV-06")
    assert "A retry, a timeout or deadline, a cache, or a raised limit" in rev06 and "fixes_kinds" in rev06 and "regressed" in rev06
    pr04 = w.rule("PR-04")
    assert "sanctioned" in pr04 and "debt" in pr04 and "Never widen a path glob" in pr04
    mrg02 = w.rule("MRG-02")
    assert "Only the owner" in mrg02 and "ledger/overrides/pr-<N>.yaml" in mrg02 and "holds for that head only" in mrg02
    assert "never turned into a setting" in mrg02
    rules = yaml.safe_load(w.rules_text())
    flat = [r for v in rules.values() if isinstance(v, list) for r in v if isinstance(r, dict) and "id" in r]
    scope = {r["id"]: r["applies_to"] for r in flat}
    assert scope["MRG-02"] == "coordinator,review" and scope["REV-06"] == "implementation,review" == scope["PR-04"]
    for role, want, absent in (("review", {"MRG-02", "REV-06", "PR-04"}, set()), ("implementation", {"REV-06", "PR-04"}, {"MRG-02"}),
                               ("coordinator", {"MRG-02"}, {"REV-06", "PR-04"})):
        ids = {r["id"] for r in yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())["rules"]}
        assert want <= ids and not (absent & ids), role
    assert not notable(w.audit("--json"))  # no rule too long, no role over its load, extracts in sync


@pytest.mark.parametrize("sets", [(), ("model_preset=economy", "profile_key=frugal"), ("dispatcher=true",), ("workspace_root=./governance",)])
def test_new_rules_keep_every_variant_clean(w, sets):
    assert w.generate(None, *sets).returncode == 0
    found = [f for f in notable(w.audit("--json")) if f["code"] != "A14"]  # A14: the test workspace is not a git checkout
    assert not found, (sets, found)
    assert all(len(r) <= 450 for r in (w.rule(i) for i in ("META-03", "REV-06", "PR-04", "MRG-02")))


# ---- exemptions --------------------------------------------------------------------------------------

def test_an_exemption_lets_exactly_its_paths_through_and_is_printed():
    status, _ = check(["src/cli/main.py", "src/core/legacy/loader.py"], labels=("lane:cli", "risk:high"))
    assert status["ownership"] == "FAIL"
    status, results = check(["src/cli/main.py", "src/core/legacy/loader.py"], labels=("lane:cli", "risk:high"), exemptions=[DEBT])
    assert status["ownership"] == "ok" and status["exemption"] == "WARN"
    note = next(r["message"] for r in results if r["check"] == "exemption")
    assert "src/core/legacy/loader.py" in note and "#31" in note and "legacy loader" in note
    # another path of the same lane is not covered
    status, _ = check(["src/core/engine.py"], labels=("lane:cli", "risk:high"), exemptions=[DEBT])
    assert status["ownership"] == "FAIL" and "exemption" not in status
    # an exemption for one check does not cover another: the lock label is still required
    status, _ = check(["src/core/legacy/loader.py"], labels=("lane:core", "risk:high"), exemptions=[DEBT])
    assert status["lock"] == "FAIL"


def test_sanctioned_exemption_and_unused_exemptions_stay_quiet():
    status, _ = check(["src/cli/main.py", "LICENSE"])
    assert status["unowned"] == "WARN"
    status, results = check(["src/cli/main.py", "LICENSE"], exemptions=[SANCTIONED, DEBT])
    assert "unowned" not in status and status["exemption"] == "ok"
    assert len([r for r in results if r["check"] == "exemption"]) == 1  # the unused debt entry is not reported as used


def test_critical_and_deleted_test_exemptions():
    crit = {"check": "critical", "paths": ["src/core/version.py"], "kind": "sanctioned", "reason": "Version string only, bumped by the release job"}
    status, _ = check(["src/core/version.py"], labels=("lane:core", "lane:infra"))
    assert status["critical"] == "FAIL"
    status, _ = check(["src/core/version.py"], labels=("lane:core", "lane:infra"), exemptions=[crit])
    assert "critical" not in status and status["exemption"] == "ok"
    status, _ = check(["src/core/version.py", "src/core/engine.py"], labels=("lane:core", "lane:infra"), exemptions=[crit])
    assert status["critical"] == "FAIL"  # the other critical file still needs risk:high
    tests = {"check": "tests", "paths": ["tests/legacy/**"], "kind": "debt", "issue": 7, "reason": "Legacy suite is replaced by tests/import in issue 7"}
    results = pr_checks.run_checks(CFG, "cli: drop legacy (#7)", ["lane:cli"], [("D", "tests/legacy/test_old.py"), ("D", "tests/test_keep.py")], "x\n", [tests])
    warn = next(r["message"] for r in results if r["check"] == "tests")
    assert "tests/test_keep.py" in warn and "tests/legacy/test_old.py" not in warn


def test_debt_whose_issue_is_closed_fails():
    status, results = check(["src/cli/main.py"], exemptions=[DEBT], open_issues={31, 40})
    assert "exemption debt" not in status
    status, results = check(["src/cli/main.py"], exemptions=[DEBT, SANCTIONED], open_issues={40})
    assert status["exemption debt"] == "FAIL" and "#31" in next(r["message"] for r in results if r["check"] == "exemption debt")
    status, _ = check(["src/cli/main.py"], exemptions=[DEBT], open_issues=set())
    assert status["exemption debt"] == "FAIL"
    status, _ = check(["src/cli/main.py"], exemptions=[DEBT])  # not asked: no claim either way
    assert "exemption debt" not in status


@pytest.mark.parametrize("entry, word", [
    ({**DEBT, "check": "title"}, "`check` must be one of"),
    ({**DEBT, "kind": "temporary"}, "`kind` must be sanctioned or debt"),
    ({**DEBT, "reason": "legacy"}, "`reason` must say why"),
    ({k: v for k, v in DEBT.items() if k != "issue"}, "names the `issue`"),
    ({**DEBT, "issue": "31"}, "names the `issue`"),
    ({**DEBT, "issue": True}, "names the `issue`"),
    ({**SANCTIONED, "issue": 3}, "names no `issue`"),
    ({**DEBT, "paths": []}, "non-empty list"),
    ({**DEBT, "paths": "src/**"}, "non-empty list"),
    ({**DEBT, "paths": ["**"]}, "not everything"),
    ({**DEBT, "paths": ["../other"]}, "not everything"),
    ({**DEBT, "until": "2027"}, "unknown key(s) until"),
    ("src/core/**", "must be an object"),
])
def test_malformed_exemptions_are_named(entry, word):
    assert any(word in e for e in pr_checks.exemption_errors([entry]))


def test_exemption_errors_accepts_good_lists_and_rejects_non_lists():
    assert pr_checks.exemption_errors([]) == [] and pr_checks.exemption_errors([DEBT, SANCTIONED]) == []
    assert pr_checks.exemption_errors({"exemptions": []}) == ["the exemptions file must hold a JSON list"]


def test_exemptions_on_the_command_line(tmp_path):
    (tmp_path / "pr-checks.json").write_text(json.dumps({**CFG, "lock_label": "", "locked_label": ""}))
    (tmp_path / "changed.txt").write_text("M\tsrc/cli/main.py\nM\tsrc/core/legacy/loader.py\n")
    (tmp_path / "commits.txt").write_text("add import\n")
    args = ["--config", tmp_path / "pr-checks.json", "--title", "cli: add import (#12)", "--labels", "lane:cli,risk:high",
            "--files", tmp_path / "changed.txt", "--commits", tmp_path / "commits.txt"]
    assert run("pr_checks.py", *args).returncode == 1  # no exemptions file: ownership fails
    (tmp_path / "pr-check-exemptions.json").write_text(json.dumps([DEBT]))
    r = run("pr_checks.py", *args)  # the file next to the config is picked up
    assert r.returncode == 0 and "exempt from the ownership check as debt" in r.stdout
    r = run("pr_checks.py", *args, "--open-issues", "12, #40")
    assert r.returncode == 1 and "whose issue is not open: #31" in r.stdout
    assert run("pr_checks.py", *args, "--open-issues", "31").returncode == 0
    assert run("pr_checks.py", *args, "--open-issues", "abc").returncode == 2
    # a malformed list is a config error, never a silent pass
    (tmp_path / "pr-check-exemptions.json").write_text(json.dumps([{**DEBT, "kind": "todo"}]))
    r = run("pr_checks.py", *args)
    assert r.returncode == 2 and "`kind` must be sanctioned or debt" in r.stderr
    (tmp_path / "pr-check-exemptions.json").write_text("not json")
    assert run("pr_checks.py", *args).returncode == 2
    # an explicit file that does not exist is an error too
    assert run("pr_checks.py", *args, "--exemptions", tmp_path / "missing.json").returncode == 2
    other = tmp_path / "other.json"
    other.write_text("[]")
    assert run("pr_checks.py", *args, "--exemptions", other).returncode == 1  # explicit empty list: ownership fails again


def test_scaffold_writes_an_empty_exemptions_list_once_and_protects_the_checks(w):
    assert w.generate(None, "workspace_root=./governance", 'label_paths=["lane:cli=src/cli/**"]').returncode == 0
    assert w.scaffold("--github").returncode == 0
    gh = w.ws / "github-setup"
    assert json.loads((gh / "pr-check-exemptions.json").read_text()) == []
    (gh / "pr-check-exemptions.json").write_text(json.dumps([SANCTIONED]))
    assert w.scaffold("--github", "--force").returncode == 0
    assert json.loads((gh / "pr-check-exemptions.json").read_text()) == [SANCTIONED]  # the project's record survives --force
    owners = (gh / "CODEOWNERS").read_text()
    assert "/.github/governance/" in owners and "/.github/workflows/governance-pr-checks.yml" in owners
    readme = (gh / "README.md").read_text()
    assert "pr-check-exemptions.json" in readme and "PR-04" in readme and "Known gaps, on purpose" in readme
    r = subprocess.run([sys.executable, str(gh / "pr_checks.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--open-issues" in r.stdout


# ---- overrides ---------------------------------------------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def put(w, sub, name, body):
    folder = w.ws / "ledger" / sub
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(body)


def pr_entry(n, thread="impl-1", fixes=""):
    extra = f'fixes_kinds: "{fixes}"\n' if fixes else ""
    return f'pr: {n}\nopened: 2026-01-31\nthread: {thread}\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n{extra}'


def round_entry(pr, k, must, verdict, head, date, merged="", kinds=""):
    crit = "critical: no\n" if k == 1 else ""
    return (f"pr: {pr}\nround: {k}\ndate: {date}\nthread: review-1\nhead: {head}\n{crit}verdict: {verdict}\nmust_fix: {must}\n"
            f'should_fix: 0\nkinds: "{kinds}"\nreport: plans/review-pr{pr}-round{k}.md\nmerged: "{merged}"\n')


def override(pr, head, reason="Hotfix for the broken release build; finding tracked in #40", by="owner, chat 2026-02-03", date="2026-02-03"):
    return f'pr: {pr}\ndate: {date}\nby: "{by}"\nhead: {head}\nreason: "{reason}"\n'


@pytest.fixture
def led(w):
    w.generate()
    w.scaffold()
    put(w, "prs", "pr-12", pr_entry(12))
    put(w, "rounds", "pr12-round1", round_entry(12, 1, 1, "changes_requested", "3f9c2ab", "2026-02-01"))
    return w


def test_override_lets_one_head_through_and_says_so(led):
    assert ledger(led, "gate", "12").returncode == 1
    put(led, "overrides", "pr-12", override(12, "3f9c2ab"))
    r = ledger(led, "gate", "12")
    assert r.returncode == 0 and "may be merged by owner override" in r.stdout and "OWNER OVERRIDE by owner, chat 2026-02-03" in r.stdout
    assert "1 open must-fix finding(s)" in r.stdout and "from the owner only" in r.stdout  # what was overridden stays visible
    assert ledger(led, "check").returncode == 0
    assert "Owner overrides of the merge gate: 1: #12 (2026-02-03)" in ledger(led, "stats").stdout
    # a full SHA in the override matches the short head of the round
    put(led, "overrides", "pr-12", override(12, "3f9c2ab" + "0" * 33))
    assert ledger(led, "gate", "12").returncode == 0


def test_override_does_not_carry_over_to_a_new_head_or_another_pr(led):
    put(led, "overrides", "pr-12", override(12, "3f9c2ab"))
    put(led, "rounds", "pr12-round2", round_entry(12, 2, 1, "changes_requested", "77aa001", "2026-02-02"))
    r = ledger(led, "gate", "12")
    assert r.returncode == 1 and "does not carry over to a changed PR" in r.stdout
    put(led, "prs", "pr-13", pr_entry(13))
    put(led, "rounds", "pr13-round1", round_entry(13, 1, 2, "changes_requested", "3f9c2ab", "2026-02-02"))
    r = ledger(led, "gate", "13")
    assert r.returncode == 1 and "OVERRIDE" not in r.stdout


def test_override_is_not_needed_and_not_shown_when_the_gate_passes(led):
    put(led, "overrides", "pr-12", override(12, "3f9c2ab"))
    put(led, "rounds", "pr12-round2", round_entry(12, 2, 0, "approved", "77aa001", "2026-02-02"))
    r = ledger(led, "gate", "12")
    assert r.returncode == 0 and "OVERRIDE" not in r.stdout and "by owner override" not in r.stdout


def test_override_is_used_once(led):
    put(led, "overrides", "pr-12", override(12, "3f9c2ab"))
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 1, "changes_requested", "3f9c2ab", "2026-02-01", merged="5b7e1c9"))
    r = ledger(led, "gate", "12")
    assert r.returncode == 1 and "already merged" in r.stdout and "used once" in r.stdout


@pytest.mark.parametrize("body, word", [
    (override(12, "3f9c2ab", reason="hotfix"), "`reason` must say why"),
    (override(12, "latest"), "`head` must be the commit SHA"),
    (override(12, "3f9c2ab").replace('by: "owner, chat 2026-02-03"\n', ""), "`by` is missing"),
    (override(12, "3f9c2ab").replace("head: 3f9c2ab\n", ""), "`head` is missing"),
    (override(12, "3f9c2ab").replace("date: 2026-02-03\n", ""), "`date` is missing"),
])
def test_malformed_override_does_not_count(led, body, word):
    put(led, "overrides", "pr-12", body)
    r = ledger(led, "gate", "12")
    assert r.returncode == 1 and "does not count" in r.stdout and word in r.stdout
    c = ledger(led, "check")
    assert c.returncode == 1 and word in c.stdout


def test_override_without_a_round_needs_the_head(led):
    put(led, "prs", "pr-14", pr_entry(14))
    put(led, "overrides", "pr-14", override(14, "abcdef1"))
    r = ledger(led, "gate", "14")
    assert r.returncode == 1 and "pass the PR's current head with --head" in r.stdout
    assert ledger(led, "gate", "14", "--head", "abcdef1234").returncode == 0
    assert ledger(led, "gate", "14", "--head", "9999999").returncode == 1
    # --head never replaces the head of a recorded round
    put(led, "overrides", "pr-12", override(12, "abcdef1"))
    assert ledger(led, "gate", "12", "--head", "abcdef1").returncode == 1


def test_same_head():
    assert ledger_tool.same_head("3f9c2ab", "3F9C2AB01") and ledger_tool.same_head("3f9c2ab01", "3f9c2ab")
    assert not ledger_tool.same_head("3f9c2", "3f9c2ab") and not ledger_tool.same_head("", "") and not ledger_tool.same_head("3f9c2ab", "3f9c2ac")


def test_stats_without_overrides_or_claims(led):
    out = ledger(led, "stats").stdout
    assert "Owner overrides of the merge gate: 0." in out and "Fixes claimed" not in out


# ---- fix claims: pending, holding, regressed -------------------------------------------------------------

def test_fix_claim_standing_is_derived(led):
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 1, "changes_requested", "3f9c2ab", "2026-02-01", kinds="timer-workaround"))
    put(led, "prs", "pr-15", pr_entry(15, fixes="Timer-Workaround"))
    put(led, "rounds", "pr15-round1", round_entry(15, 1, 0, "approved", "aaaaaaa", "2026-02-05"))
    assert "timer-workaround: #15, pending, the PR is not merged" in ledger(led, "stats").stdout
    put(led, "rounds", "pr15-round1", round_entry(15, 1, 0, "approved", "aaaaaaa", "2026-02-05", merged="bbbbbbb"))
    assert "timer-workaround: #15, holding, not seen since" in ledger(led, "stats").stdout  # #12's round is older
    put(led, "prs", "pr-16", pr_entry(16))
    put(led, "rounds", "pr16-round1", round_entry(16, 1, 1, "changes_requested", "ccccccc", "2026-02-07", kinds="missing-test, timer-workaround"))
    out = ledger(led, "stats").stdout
    assert "timer-workaround: #15, REGRESSED, seen again in #16" in out and "one step up the ladder (META-03)" in out
    assert ledger(led, "check").returncode == 0


def test_fix_claim_same_day_and_own_rounds(led):
    put(led, "rounds", "pr12-round1", round_entry(12, 1, 1, "changes_requested", "3f9c2ab", "2026-02-01", kinds="timer-workaround"))
    # the claiming PR's own rounds never regress it, and an older PR reviewed on the merge day does not either
    put(led, "prs", "pr-15", pr_entry(15, fixes="timer-workaround"))
    put(led, "rounds", "pr15-round1", round_entry(15, 1, 1, "changes_requested", "aaaaaaa", "2026-02-05", kinds="timer-workaround"))
    put(led, "rounds", "pr15-round2", round_entry(15, 2, 0, "approved", "aaaaaab", "2026-02-06", merged="bbbbbbb"))
    put(led, "rounds", "pr12-round2", round_entry(12, 2, 1, "changes_requested", "3f9c2ac", "2026-02-06", kinds="timer-workaround"))
    assert "timer-workaround: #15, holding" in ledger(led, "stats").stdout
    # a newer PR reviewed on the merge day counts as later
    put(led, "prs", "pr-17", pr_entry(17))
    put(led, "rounds", "pr17-round1", round_entry(17, 1, 1, "changes_requested", "ddddddd", "2026-02-06", kinds="timer-workaround"))
    assert "REGRESSED, seen again in #17" in ledger(led, "stats").stdout


def test_fix_claim_for_an_unknown_kind_is_a_problem(led):
    put(led, "prs", "pr-15", pr_entry(15, fixes="flaky-network"))
    r = ledger(led, "check")
    assert r.returncode == 1 and "`fixes_kinds` names 'flaky-network', a finding kind no review round has recorded" in r.stdout


# ---- templates and reference -------------------------------------------------------------------------------

def test_templates_and_reference_describe_the_mechanisms(w):
    w.generate()
    w.scaffold()
    ledger_readme = (w.ws / "ledger" / "README.md").read_text()
    for phrase in ("overrides/pr-<N>.yaml", "MRG-02", "fixes_kinds", "pending", "regressed", "a record, not proof"):
        assert phrase in ledger_readme, phrase
    features = (w.ws / "kb" / "features" / "README.md").read_text()
    assert "(#<issue that removes it>)" in features and "(stays: <why>)" in features
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Further up the ladder", "Known gaps, on purpose", "REV-01..06, MRG-01..02", "equinai/equin"):
        assert phrase in model, phrase
    assert "Exemptions and overrides" in (SKILL / "references" / "audit-checklist.md").read_text()
    assert "Known gaps, on purpose" in (SKILL / "scripts" / "pr_checks.py").read_text()
