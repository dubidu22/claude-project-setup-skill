"""Seam audit: files that work together are read together, on a derived schedule, with a fixed brief and report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import SKILL, Workspace, notable, run

GROUPS = '["web=web/api.py,web/jobs.py,web/documents.py","extraction=extraction/*.py"]'


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture
def proj(tmp_path: Path) -> Workspace:
    """A repository with two seams and a governance workspace inside it."""
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "extraction").mkdir()
    (repo / "web" / "jobs.py").write_text("class JobTimeout(Exception): pass\n# D-002: jobs time out after 30s (#31)\ndef run(): raise JobTimeout()\n")
    (repo / "web" / "api.py").write_text("import jobs\n# see D-007 and issue #40\ndef route():\n    if jobs.state == 'idle':\n        jobs.run()\n")
    (repo / "web" / "documents.py").write_text("COLOR = '#123'\nx = 1\n")
    (repo / "extraction" / "pdf.py").write_text("y = 1\n")
    (repo / "extraction" / "isolate.py").write_text("z = 1  # D-001\n")
    git(repo, "init", "-q", "-b", "main")
    w = Workspace(repo)
    w.ws = repo / "governance"
    w.rules, w.state, w.config = w.ws / "claude-project-rules.yaml", w.ws / "project-state.yaml", w.ws / "governance-config.json"
    assert w.generate(None, "workspace_root=./governance", f"seam_groups={GROUPS}").returncode == 0
    assert w.scaffold().returncode == 0
    with (w.ws / "kb" / "decision-log.md").open("a") as f:
        f.write("\n## D-003 (2026-03-01, owner)\nTimeouts are now 60 seconds. Supersedes D-002.\n\n## D-002 (2026-02-01, owner)\nTimeouts are 30 seconds.\n")
    return w


def seam(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "seam_audit.py"), *args], capture_output=True, text=True)


def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def merge(w, n, date):
    for sub in ("prs", "rounds"):
        (w.ws / "ledger" / sub).mkdir(parents=True, exist_ok=True)
    (w.ws / "ledger" / "prs" / f"pr-{n}.yaml").write_text(f'pr: {n}\nopened: {date}\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n')
    (w.ws / "ledger" / "rounds" / f"pr{n}-round1.yaml").write_text(
        f'pr: {n}\nround: 1\ndate: {date}\nthread: review-1\nhead: 3f9c2ab\ncritical: no\nverdict: approved\nmust_fix: 0\nshould_fix: 0\n'
        f'kinds: ""\nreport: plans/review-pr{n}-round1.md\nmerged: "5b7e1c9"\n')


def report(w, body, name="seam-2026-03-10.md", read="web, extraction", skipped=None):
    folder = w.ws / "ledger" / "audits"
    folder.mkdir(parents=True, exist_ok=True)
    head = f"# Seam audit 2026-03-10\nGroups read: {read}\n" + (f"Groups skipped: {skipped}\n" if skipped else "")
    (folder / name).write_text(f"{head}\n## Findings\n{body}\n")
    return folder / name


GOOD = ("1. parity | check | web | JobTimeout from jobs.run is not mapped by the route and becomes a 500 | web/jobs.py:3, web/api.py:5\n"
        "2. state | owner | web | The route reads jobs.state and then calls jobs.run without a lock | web/api.py:4, web/jobs.py:3\n"
        "3. drift | rule | web | The comment cites D-002 (30 seconds) but D-003 changed the timeout | web/jobs.py:2")


# ---- the setting and the rule ---------------------------------------------------------------------------

def test_rule_and_settings_only_with_seam_groups(w):
    assert w.generate().returncode == 0
    text = w.rules_text()
    assert "ROLE-16" not in text and "seam_groups" not in text and "seam_audit_every_prs" not in text
    assert w.scaffold().returncode == 0
    assert not (w.ws / "tools" / "seam_audit.py").exists() and "seam" not in (w.ws / "ledger" / "README.md").read_text().lower()
    assert w.generate(None, f"seam_groups={GROUPS}").returncode == 0 and w.scaffold("--refresh").returncode == 0
    rule = w.rule("ROLE-16")
    for phrase in ("fresh, read-only session", "ledger_tool.py stats says it is due or a milestone closes", "seam_audit.py brief",
                   "four checks only", "error and status mapping", "state read before a mutator", "duplicated helpers",
                   "comments citing a changed invariant", "at most ten findings", "ledger/audits/seam-<date>.md", "no edits"):
        assert phrase in rule, phrase
    assert len(rule) <= 450
    prof = yaml.safe_load(w.rules_text())["project_profile"]
    assert prof["seam_groups"] == json.loads(GROUPS) and prof["seam_audit_every_prs"] == 15
    audit_ids = {r["id"] for r in yaml.safe_load((w.ws / "rules" / "audit.yaml").read_text())["rules"]}
    impl_ids = {r["id"] for r in yaml.safe_load((w.ws / "rules" / "implementation.yaml").read_text())["rules"]}
    assert "ROLE-16" in audit_ids and "ROLE-16" not in impl_ids
    assert (w.ws / "tools" / "seam_audit.py").is_file()
    readme = (w.ws / "ledger" / "README.md").read_text()
    assert "audits/seam-<YYYY-MM-DD>.md" in readme and "seam_audit.py brief" in readme and "<!--" not in readme
    assert not notable(w.audit("--json"))


def test_settings_survive_the_round_trip(w, tmp_path):
    assert w.generate(None, f"seam_groups={GROUPS}", "seam_audit_every_prs=8").returncode == 0
    out = tmp_path / "derived.json"
    assert run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out).returncode == 0
    derived = json.loads(out.read_text())
    assert derived["seam_groups"] == json.loads(GROUPS) and derived["seam_audit_every_prs"] == 8
    before = w.rules_text()
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.rules_text() == before


@pytest.mark.parametrize("value, word", [
    ('["web/api.py,web/jobs.py"]', "must look like <name>=<path>,<path>"),
    ('["Web=web/api.py,web/jobs.py"]', "must look like"),
    ('["web=web/api.py,"]', "must look like"),
    ('["web=web/api.py"]', "names one file"),
    ('["web=/web/api.py,web/jobs.py"]', "from the repository root"),
    ('["web=../api.py,web/jobs.py"]', "from the repository root"),
    ('["all=**"]', "not everything"),
    ('["web=web/api.py,web/jobs.py","web=web/a.py,web/b.py"]', "used twice"),
    ('"web=web/api.py,web/jobs.py"', "seam_groups"),
])
def test_malformed_seam_groups_are_refused(w, value, word):
    r = w.generate(None, f"seam_groups={value}")
    assert r.returncode == 2 and word in r.stderr and not w.rules.exists()


def test_interval_has_a_floor_and_a_single_glob_is_a_group(w):
    r = w.generate(None, f"seam_groups={GROUPS}", "seam_audit_every_prs=2")
    assert r.returncode == 2 and "seam_audit_every_prs" in r.stderr
    assert w.generate(None, 'seam_groups=["extraction=extraction/*.py"]', "seam_audit_every_prs=5").returncode == 0


# ---- the brief and the cited decisions ------------------------------------------------------------------

def test_brief_is_fixed_text_plus_the_groups(proj):
    r = seam(proj, "brief", "--closed-issues", "31")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    for phrase in ("read-only", "change no code", "Check these four things and nothing else", "1. parity:", "2. state:", "3. duplicate:",
                   "4. drift:", "  web:", "    web/api.py", "    web/jobs.py", "    web/documents.py", "  extraction:",
                   "    extraction/isolate.py", "    extraction/pdf.py", "At most 10 findings", "kind: parity, state, duplicate, drift",
                   "verdict: check, rule, split, owner, leave", "governance/ledger/audits/seam-<YYYY-MM-DD>.md",
                   "governance/tools/seam_audit.py check", "a finding from memory of a similar codebase is not a finding"):
        assert phrase in out, phrase
    assert "web/jobs.py:2: D-002  <- SUPERSEDED by D-003" in out
    assert "web/jobs.py:2: #31  <- CLOSED" in out
    assert "web/api.py:2: D-007  <- NOT IN THE DECISION LOG" in out
    assert "web/api.py:2: #40\n" in out                       # open or unknown: listed without a mark
    assert "extraction/isolate.py:1: D-001\n" in out            # known and current
    assert "#123" not in out                                    # a colour, not an issue
    assert seam(proj, "brief").stdout == seam(proj, "brief").stdout  # the same every time


def test_refs_and_a_group_whose_files_are_gone(proj):
    (proj.ws.parent / "extraction" / "pdf.py").unlink()
    (proj.ws.parent / "extraction" / "isolate.py").unlink()
    r = seam(proj, "refs")
    assert r.returncode == 0 and "web: 3 file(s)" in r.stdout and "extraction: 0 file(s), nothing matches extraction/*.py" in r.stdout
    assert "D-002  <- SUPERSEDED by D-003" in r.stdout and "CLOSED" not in r.stdout
    assert "no file matches extraction/*.py" in seam(proj, "brief").stdout


def test_tool_needs_groups_and_a_repository(w, tmp_path):
    assert w.generate().returncode == 0
    r = run("seam_audit.py", "brief", "--workspace", w.ws, "--repo", tmp_path)
    assert r.returncode == 2 and "no seam_groups in the config" in r.stderr and "not guessed" in r.stderr
    assert w.generate(None, f"seam_groups={GROUPS}").returncode == 0
    r = run("seam_audit.py", "brief", "--workspace", w.ws)
    assert r.returncode == 2 and "pass --repo" in r.stderr
    assert run("seam_audit.py", "brief", "--workspace", tmp_path / "nowhere").returncode == 2
    assert run("seam_audit.py", "brief", "--workspace", w.ws, "--repo", tmp_path, "--closed-issues", "x").returncode == 2


def test_the_tool_writes_nothing(proj):
    def snapshot():
        return {p: p.read_bytes() for p in proj.ws.parent.rglob("*") if p.is_file() and ".git/" not in p.as_posix()}
    before = snapshot()
    seam(proj, "brief")
    seam(proj, "refs")
    seam(proj, "check", str(report(proj, GOOD)))
    after = snapshot()
    added = set(after) - set(before)
    assert {p.name for p in added} == {"seam-2026-03-10.md"}  # only the report this test wrote itself
    assert all(after[p] == before[p] for p in before)


# ---- the report ----------------------------------------------------------------------------------------

def test_a_report_in_shape_passes(proj):
    r = seam(proj, "check", str(report(proj, GOOD)))
    assert r.returncode == 0 and "in shape" in r.stdout
    assert seam(proj, "check", str(report(proj, "none"))).returncode == 0
    assert seam(proj, "check", str(report(proj, GOOD + "\nLeft out: 3"))).returncode == 0
    assert seam(proj, "check", str(report(proj, GOOD, read="web", skipped="extraction (both files were deleted in #40)"))).returncode == 0
    assert seam(proj, "check", str(report(proj, GOOD + "\n\n## Notes\nfree text below the findings is fine"))).returncode == 0


@pytest.mark.parametrize("body, word", [
    ("1. style | check | web | Variable names are inconsistent across the two files | web/api.py:1, web/jobs.py:1", "a seam audit checks these four things only"),
    ("1. parity | fix | web | JobTimeout is not mapped by the route and becomes a 500 | web/jobs.py:3, web/api.py:5", "verdict 'fix' is not one of"),
    ("1. parity | check | web | JobTimeout is not mapped by the route and becomes a 500 | web/jobs.py:3", "is between files"),
    ("1. state | check | web | The route reads state then mutates without a lock | web/api.py:4, web/api.py:5", "is between files"),
    ("1. parity | check | web | JobTimeout is not mapped by the route and becomes a 500 | web/jobs.py, web/api.py:5", "<file>:<line>"),
    ("1. parity | check | web | JobTimeout is not mapped by the route and becomes a 500 | src/other.py:3, web/api.py:5", "src/other.py is not in the group 'web'"),
    ("1. parity | check | billing | JobTimeout is not mapped by the route and becomes a 500 | web/jobs.py:3, web/api.py:5", "unknown group 'billing'"),
    ("1. parity | check | web | bad | web/jobs.py:3, web/api.py:5", "say what is wrong in a sentence"),
    ("1. parity | check | web | JobTimeout is not mapped by the route", "needs five parts"),
    ("JobTimeout is not mapped anywhere, and several other things look odd.", "lines under `## Findings` that are not findings"),
    ("", "no finding and no `none`"),
])
def test_a_report_out_of_shape_is_refused(proj, body, word):
    r = seam(proj, "check", str(report(proj, body)))
    assert r.returncode == 1 and word in r.stdout, r.stdout


def test_report_size_groups_and_name_are_checked(proj):
    many = "\n".join(f"{i}. duplicate | check | web | Helper number {i} exists in both modules | web/api.py:{i}, web/jobs.py:{i}" for i in range(1, 12))
    r = seam(proj, "check", str(report(proj, many)))
    assert r.returncode == 1 and "11 findings; a seam audit reports at most 10" in r.stdout
    r = seam(proj, "check", str(report(proj, GOOD, read="web")))
    assert r.returncode == 1 and "group(s) neither read nor skipped: extraction" in r.stdout
    r = seam(proj, "check", str(report(proj, GOOD, read="web", skipped="extraction")))
    assert r.returncode == 1 and "gives its reason in brackets" in r.stdout
    r = seam(proj, "check", str(report(proj, GOOD, read="web, extraction, billing")))
    assert r.returncode == 1 and "unknown group(s): billing" in r.stdout
    r = seam(proj, "check", str(report(proj, GOOD, name="notes.md")))
    assert r.returncode == 1 and "file name must be seam-<YYYY-MM-DD>.md" in r.stdout
    assert seam(proj, "check").returncode == 2 and seam(proj, "check", str(proj.ws / "missing.md")).returncode == 2
    drift_one_file = "1. drift | rule | web | The comment cites D-002 but D-003 changed the timeout | web/jobs.py:2"
    assert seam(proj, "check", str(report(proj, drift_one_file))).returncode == 0  # drift can sit in one file


# ---- when it is due ------------------------------------------------------------------------------------

def test_due_is_counted_from_the_merge_entries(proj):
    assert proj.generate(None, "seam_audit_every_prs=5").returncode == 0
    assert "Seam audit: not due, 0 of 5 PRs merged and no seam audit has run yet." in ledger(proj, "stats").stdout
    for n in range(1, 5):
        merge(proj, n, f"2026-03-0{n}")
    assert "not due, 4 of 5 PRs merged" in ledger(proj, "stats").stdout
    assert "seam-audit-due" not in ledger(proj, "flags").stdout
    merge(proj, 5, "2026-03-05")
    stats = ledger(proj, "stats").stdout
    assert "Seam audit: DUE, 5 PRs merged and no seam audit has run yet (due every 5)" in stats and "seam_audit.py brief (ROLE-16)" in stats
    assert "flag: seam-audit-due | 5 PRs merged" in ledger(proj, "flags").stdout
    # the report of a seam audit resets the count; nobody edits a counter
    report(proj, "none", name="seam-2026-03-06.md")
    assert "not due, 0 of 5 PRs merged since the seam audit of 2026-03-06" in ledger(proj, "stats").stdout
    merge(proj, 6, "2026-03-07")
    assert "1 of 5 PRs merged since the seam audit of 2026-03-06" in ledger(proj, "stats").stdout
    # an unmerged PR does not count
    (proj.ws / "ledger" / "rounds" / "pr6-round1.yaml").write_text(
        (proj.ws / "ledger" / "rounds" / "pr6-round1.yaml").read_text().replace('merged: "5b7e1c9"', 'merged: ""'))
    assert "0 of 5 PRs merged" in ledger(proj, "stats").stdout


def test_no_seam_line_without_groups(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    merge(w, 1, "2026-03-01")
    assert "Seam audit" not in ledger(w, "stats").stdout and "seam" not in ledger(w, "flags").stdout


# ---- docs and the move ---------------------------------------------------------------------------------

def test_reference_and_skill_describe_it():
    model = (SKILL / "references" / "governance-model.md").read_text()
    for phrase in ("Seam audits: files that work together are read together", "ROLE-16", "seam_audit_every_prs", "seam_audit.py check",
                   "anchored by what it approved", "A group is only audited if someone named it"):
        assert phrase in model, phrase
    assert "`seam_groups`" in (SKILL / "init.md").read_text() and "do not guess them from file names" in (SKILL / "init.md").read_text()
    assert "seam_audit.py" in (SKILL / "SKILL.md").read_text()
    assert "| Seams |" in (SKILL / "references" / "audit-checklist.md").read_text()


def test_a_flat_download_places_seam_reports():
    sys.path.insert(0, str(SKILL / "scripts"))
    import move_workspace as m
    assert m.place("seam-2026-03-10.md", Path("x")) == "ledger/audits/seam-2026-03-10.md"
    assert m.place("seam_audit.py", Path("x")) == ""
