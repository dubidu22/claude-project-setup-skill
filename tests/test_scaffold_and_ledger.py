"""scaffold_workspace.py and ledger_tool.py: optional parts, GitHub setup files, one file per PR and round."""
from __future__ import annotations

import re
import subprocess
import sys

from conftest import run

DANGLING = re.compile(r"\{\{|<!--|\bundefined\b")


def workspace_text(w) -> str:
    return "\n".join(p.read_text() for p in w.ws.rglob("*.md") if "tools" not in p.parts)


def test_default_scaffold_and_refresh(w):
    w.generate()
    r = w.scaffold("--github")
    assert r.returncode == 0 and r.stderr == "", r.stderr
    for rel in ("project_instructions.md", "dispatcher_instructions.md", "plans/README.md", "plans/contract-template.yaml",
                "tools/contract_tool.py", "tools/ledger_tool.py", "tools/acceptance-contracts.md", "roadmap.yaml",
                "kb/README.md", "kb/decision-log.md", "ledger/README.md", "github-setup/create-labels.sh", "github-setup/README.md"):
        assert (w.ws / rel).is_file(), rel
    assert not DANGLING.search(workspace_text(w))
    assert not (w.ws / "ledger" / "implementation.md").exists() and not (w.ws / ".github").exists()
    log = w.ws / "kb" / "decision-log.md"
    assert "D-001 (2026-03-04, owner)" in log.read_text() and "version 2.0.0" in log.read_text()
    log.write_text(log.read_text() + "\n## D-002\nkept\n")
    (w.ws / "project_instructions.md").write_text("stale")
    again = w.scaffold("--refresh")
    assert "D-002" in log.read_text() and (w.ws / "project_instructions.md").read_text() != "stale"
    assert f"kept     {log}" in again.stdout
    # the contract template lints as a template would: placeholders are reported, the label is a real one
    template = (w.ws / "plans" / "contract-template.yaml").read_text()
    assert 'label: "lane:core"' in template and "owner_message" in template and "decision:" not in template


def test_switched_off_features_leave_no_dangling_references(w):
    w.generate(None, "acceptance_contracts=false", "dispatcher=false", "workspace_root=./gov", "coordinator_compact_every_batches=0")
    assert w.scaffold("--github").returncode == 0
    text = workspace_text(w)
    for gone in ("specify", "PLAN-03", "PLAN-04", "PLAN-05", "REV-03", "ROLE-10", "ROLE-11", "THR-11", "/compact",
                 "contract_tool", "Dispatcher", "acceptance contract", "roadmap.yaml"):
        assert gone not in text, gone
    assert not DANGLING.search(text)
    for rel in ("plans/contract-template.yaml", "tools/contract_tool.py", "roadmap.yaml", "dispatcher_instructions.md"):
        assert not (w.ws / rel).exists(), rel
    assert (w.ws / "tools" / "ledger_tool.py").exists()
    # every rule id the instructions cite exists in the ruleset
    cited = set(re.findall(r"`([A-Z]{2,5}-\d{2})`", text))
    assert cited and cited <= set(w.rule_ids()), cited - set(w.rule_ids())


def test_every_cited_rule_exists_with_everything_on(w):
    w.generate(None, "workspace_root=./governance", "model_preset=economy")
    w.scaffold("--github")
    cited = set(re.findall(r"`([A-Z]{2,5}-\d{2})`", workspace_text(w)))
    assert cited <= set(w.rule_ids()), cited - set(w.rule_ids())
    coord = (w.ws / "project_instructions.md").read_text()
    assert "/compact Keep:" in coord and "branch `governance`" in coord and "claude --model" in coord
    assert "rules/coordinator.yaml" in coord and "The owner's newest message" in coord
    disp = (w.ws / "dispatcher_instructions.md").read_text()
    assert "you do not write them" in disp and "`critical: no`" in disp and "`must_fix: 0`" in disp and "REV-04" in disp


def test_claude_ai_project_instructions_have_no_git_or_compact(w):
    w.generate()
    w.scaffold()
    coord = (w.ws / "project_instructions.md").read_text()
    assert "/compact" not in coord and "THR-13" not in coord and "new chat in this Project" in coord


def test_github_setup_files(w):
    w.generate({"repo_slug": "kim/demo", "owner_gh": "kim", "workspace_root": "./governance",
                "ownership_labels": ["lane:app", "lane:web"], "lane_mapping_note": "app owns all.", "project_name": "it's demo",
                "critical_paths": ["src/core/**", "migrations/*.sql"]})
    assert w.scaffold("--github").returncode == 0
    gh = w.ws / "github-setup"
    script = (gh / "create-labels.sh").read_text()
    assert "gh label create 'lane:app' --repo \"$REPO\"" in script and "REPO=${1:-'kim/demo'}" in script
    assert "risk:high" in script and "--force" in script and "'lane:web'" in script
    assert subprocess.run(["bash", "-n", str(gh / "create-labels.sh")]).returncode == 0
    owners = (gh / "CODEOWNERS").read_text()
    for path in ("/governance/claude-project-rules.yaml", "/governance/plans/contract-*", "/governance/roadmap.yaml", "/governance/rules/"):
        assert re.search(re.escape(path) + r"\s+@kim", owners), path
    import yaml

    labeler = yaml.safe_load((gh / "labeler.yml").read_text())
    assert labeler["risk:high"][0]["changed-files"][0]["any-glob-to-any-file"] == ["src/core/**", "migrations/*.sql"]
    assert yaml.safe_load((gh / "labeler-workflow.yml").read_text())["permissions"]["pull-requests"] == "write"
    assert "risk:high label set by CI" in w.rule("CRIT-03")
    assert not (w.ws / ".github").exists()  # nothing pretends to be active configuration


def test_no_codeowners_outside_a_repo(w):
    w.generate()
    w.scaffold("--github")
    assert not (w.ws / "github-setup" / "CODEOWNERS").exists()


def test_scaffold_refuses_a_bad_config(w):
    w.ws.mkdir()
    w.config.write_text('{"project_name": "demo", "dispatcher": "yes"}')
    r = w.scaffold()
    assert r.returncode != 0 and "dispatcher must be true or false" in r.stderr and not (w.ws / "kb").exists()


def test_leftovers_from_an_older_setup_are_named_not_deleted(w):
    w.generate()
    (w.ws / "ledger").mkdir()
    (w.ws / "ledger" / "review.md").write_text("old table")
    (w.ws / ".github").mkdir()
    (w.ws / ".github" / "lanes.yml").write_text("labels: []")
    r = w.scaffold()
    assert "ledger/review.md is an older ledger table" in r.stdout and ".github/lanes.yml" in r.stdout
    assert (w.ws / "ledger" / "review.md").read_text() == "old table"


# ---- ledger --------------------------------------------------------------------

def ledger(w, *args):
    return subprocess.run([sys.executable, str(w.ws / "tools" / "ledger_tool.py"), *args], capture_output=True, text=True)


def write_entries(w):
    prs, rounds = w.ws / "ledger" / "prs", w.ws / "ledger" / "rounds"
    prs.mkdir(parents=True)
    rounds.mkdir(parents=True)
    for n, thread, comp in ((12, "impl-1", 0), (13, "impl-1", 1), (14, "impl-2", 0)):
        (prs / f"pr-{n}.yaml").write_text(
            f'pr: {n}\nopened: 2026-01-31\nthread: {thread}\nlane: app_cli\nlabels: "lane:cli"\npackage: import\n'
            f"plan: plans/p.md\ncritical: no   # the author's statement\ncompactions: {comp}\n")
    for n, k, must, merged in ((12, 1, 2, ""), (12, 2, 1, ""), (12, 3, 0, "5b7e1c9"), (13, 1, 0, "")):
        crit = "critical: no\n" if k == 1 else ""
        (rounds / f"pr{n}-round{k}.yaml").write_text(
            f"pr: {n}\nround: {k}\ndate: 2026-02-0{k}\nthread: review-1\nhead: abc{k}\n{crit}"
            f"verdict: {'approved' if must == 0 else 'changes_requested'}\nmust_fix: {must}\nshould_fix: 0\n"
            f'report: plans/review-pr{n}-round{k}.md\nmerged: "{merged}"\n')
    return prs, rounds


def test_ledger_tables_stats_and_check(w):
    w.generate()
    w.scaffold()
    assert "No PR entries yet." in ledger(w, "stats").stdout
    prs, rounds = write_entries(w)
    assert ledger(w, "check").returncode == 0
    table = ledger(w, "table").stdout
    assert "| #12 | 2026-01-31 | impl-1 |" in table and "merged 5b7e1c9" in table and "open, not reviewed" in table
    assert "no / no" in table  # author's statement / reviewer's finding
    stats = ledger(w, "stats").stdout
    assert "PRs: 3; reviewed: 2; merged: 1." in stats and "2.0 on average, 3 at most" in stats
    assert "PRs with three or more rounds: #12." in stats and "impl-1: 2" in stats and "review-1 [review]: 2" in stats
    assert "PRs with one or more: #13." in stats

    (rounds / "pr13-round1.yaml").write_text((rounds / "pr13-round1.yaml").read_text().replace("critical: no\n", ""))
    (rounds / "pr12-round3.yaml").write_text((rounds / "pr12-round3.yaml").read_text().replace("must_fix: 0", "must_fix: 1"))
    (prs / "pr-14.yaml").write_text((prs / "pr-14.yaml").read_text().replace("compactions: 0", "compactions: none"))
    bad = ledger(w, "check")
    assert bad.returncode == 1
    for needle in ("round 1 must record the reviewer's `critical: yes|no`", "merged with open must-fix findings",
                   "`compactions` must be a whole number"):
        assert needle in bad.stdout, needle
