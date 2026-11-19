"""move_workspace.py: a claude.ai Project's workspace moves into the repository; history and live state are kept."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import SKILL, Workspace, findings, run

TOKEN = "ghp_" + "a1B2" * 9  # the shape of a GitHub token, not a real one


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and ".git/" not in p.as_posix()}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A running Project workspace: generated, scaffolded, with live state, a decision, a plan and ledger entries."""
    (tmp_path / "download").mkdir()
    w = Workspace(tmp_path / "download")
    assert w.generate({"project_name": "demo", "repo_slug": "dubidu22/demo", "owner_gh": "dubidu22"}).returncode == 0
    assert w.scaffold().returncode == 0
    src = w.ws
    with (src / "project-state.yaml").open("a") as f:
        f.write("pause_flag: true   # live state set by the coordinator\n")
    with (src / "kb" / "decision-log.md").open("a") as f:
        f.write("\n## D-002\nPlans live in /mnt/project-files/plans. Decided by the owner.\n")
    (src / "plans" / "plan-001-app_cli-import.md").write_text("# Plan 001\nSee /mnt/project-files/roadmap.yaml\n")
    (src / "ledger" / "prs").mkdir(parents=True, exist_ok=True)
    (src / "ledger" / "rounds").mkdir(parents=True, exist_ok=True)
    (src / "ledger" / "prs" / "pr-12.yaml").write_text('pr: 12\nopened: 2026-01-31\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n')
    (src / "ledger" / "rounds" / "pr12-round1.yaml").write_text(
        'pr: 12\nround: 1\ndate: 2026-02-01\nthread: review-1\nhead: 3f9c2ab\ncritical: no\nverdict: approved\nmust_fix: 0\nshould_fix: 0\n'
        'kinds: ""\nreport: plans/review-pr12-round1.md\nmerged: "5b7e1c9"\n')
    return src


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print(1)\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "product code")
    return root


def move(project, repo, *extra):
    return run("move_workspace.py", "--from", project, "--repo", repo, *extra)


# ---- preview --------------------------------------------------------------------------------------------

def test_preview_writes_nothing_and_shows_what_changes(project, repo):
    before_src, before_repo = tree(project), tree(repo)
    r = move(project, repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert tree(project) == before_src and tree(repo) == before_repo and not (repo / "governance").exists()
    for phrase in ("Preview only, nothing was written", "environment: claude_ai_project -> claude_code",
                   "workspace_root: /mnt/project-files -> ./governance", "rules added: THR-11, THR-13, THR-14", "with --apply"):
        assert phrase in r.stdout, phrase
    assert "WARNING" not in r.stdout  # PR 12 is merged


def test_preview_warns_about_open_prs(project, repo):
    (project / "ledger" / "prs" / "pr-13.yaml").write_text('pr: 13\nopened: 2026-02-02\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n')
    r = move(project, repo)
    assert r.returncode == 0 and "the ledger shows open PRs: #13" in r.stdout and "#12" not in r.stdout.split("open PRs:")[1].split("\n")[0]


# ---- apply ----------------------------------------------------------------------------------------------

def test_apply_moves_keeps_history_and_regenerates(project, repo):
    before = tree(project)
    head = git(repo, "rev-parse", "HEAD")
    r = move(project, repo, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    target = repo / "governance"
    after = tree(target)
    assert tree(project) == before  # the source is only read
    # history and live state arrive byte for byte
    for name in ("project-state.yaml", "kb/decision-log.md", "plans/plan-001-app_cli-import.md", "ledger/prs/pr-12.yaml",
                 "ledger/rounds/pr12-round1.yaml", "roadmap.yaml"):
        assert after[name] == before[name], name
    assert b"pause_flag: true" in after["project-state.yaml"]
    # the ruleset is the one for a repository
    rules = yaml.safe_load((target / "claude-project-rules.yaml").read_text())
    prof = rules["project_profile"]
    assert prof["environment"] == "claude_code" and prof["workspace_root"] == "./governance" and prof["default_branch"] == "main"
    ids = {r["id"] for v in rules.values() if isinstance(v, list) for r in v if isinstance(r, dict) and "id" in r}
    assert {"THR-11", "THR-13", "THR-14"} <= ids
    cfg = json.loads((target / "governance-config.json").read_text())
    assert cfg["workspace_root"] == "./governance" and cfg["environment"] == "claude_code" and cfg["project_name"] == "demo"
    # extracts and generated instructions name the new place, not the old one
    for name in ("rules/implementation.yaml", "rules/review.yaml", "rules/coordinator.yaml", "project_instructions.md", "ledger/README.md"):
        text = (target / name).read_text()
        assert "/mnt/project-files" not in text, name
    assert "governance/" in (target / "rules" / "implementation.yaml").read_text()
    # the owner's GitHub files are there, including the review of governance files
    gh = target / "github-setup"
    assert "/governance/claude-project-rules.yaml" in (gh / "CODEOWNERS").read_text() and (gh / "pr-checks.json").is_file()
    # the audit ran; only the expected note about the default branch is left
    audit = run("audit_rules.py", target / "claude-project-rules.yaml", "--state", target / "project-state.yaml", "--json")
    assert not [f for f in findings(audit) if f["severity"] == "ERROR"]
    assert {f["code"] for f in findings(audit) if f["severity"] == "WARN"} <= {"A14"}
    # the ledger still reads
    assert run("ledger_tool.py", "check", "--ledger", target / "ledger").returncode == 0
    # no git command was run: same commit, nothing staged, the folder is simply untracked
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain").strip() == "?? governance/"
    assert git(repo, "branch", "--list").split() == ["*", "main"]
    for phrase in ("Copied", "Audit: 0 error(s)", "A14 is expected now", "open a pull request into main", "The owner applies",
                   "Start every thread fresh in Claude Code", "revokes them"):
        assert phrase in r.stdout, phrase


def test_apply_reports_files_that_still_name_the_old_place(project, repo):
    (project / "kb" / "verification.md").write_text("# Verification\nStart: see /mnt/project-files/tools\n")
    r = move(project, repo, "--apply")
    assert r.returncode == 0
    other = r.stdout.split("are not history; correct them by hand:")[1].split("\n\n")[0]
    assert "kb/verification.md (1)" in other and "decision-log" not in other and "plan-001" not in other
    assert "History files that name the old location /mnt/project-files (2)" in r.stdout
    # history is not rewritten
    assert "/mnt/project-files/plans" in (repo / "governance" / "kb" / "decision-log.md").read_text()


def test_after_the_pull_request_is_merged_the_audit_is_clean(project, repo, tmp_path):
    assert move(project, repo, "--apply").returncode == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "governance workspace, reviewed by the owner")
    bare = tmp_path / "origin.git"
    git(repo, "clone", "-q", "--bare", ".", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "main")
    target = repo / "governance"
    audit = run("audit_rules.py", target / "claude-project-rules.yaml", "--state", target / "project-state.yaml", "--json")
    assert not [f for f in findings(audit) if f["severity"] in ("ERROR", "WARN")], findings(audit)


def test_another_target_folder(project, repo):
    r = move(project, repo, "--to", "ops/governance/", "--apply")
    assert r.returncode == 0, r.stdout
    rules = yaml.safe_load((repo / "ops" / "governance" / "claude-project-rules.yaml").read_text())
    assert rules["project_profile"]["workspace_root"] == "./ops/governance"


def test_an_existing_empty_target_folder_is_fine(project, repo):
    (repo / "governance").mkdir()
    assert move(project, repo, "--apply").returncode == 0


# ---- refusals -------------------------------------------------------------------------------------------

def refused(r, word):
    assert r.returncode == 1 and "Refused, nothing was written" in r.stdout and word in r.stdout, r.stdout


def test_refuses_a_folder_that_is_not_a_generated_workspace(project, repo, tmp_path):
    (project / "governance-config.json").unlink()
    refused(move(project, repo, "--apply"), "Migrating an existing ruleset")
    empty = tmp_path / "empty"
    empty.mkdir()
    refused(move(empty, repo), "run init in the repository instead")
    refused(move(tmp_path / "nowhere", repo), "is not a folder")
    assert not (repo / "governance").exists()


def test_refuses_when_the_repo_is_not_a_checkout_or_the_target_is_taken(project, repo, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    refused(move(project, plain, "--apply"), "is not a git checkout")
    assert not (plain / "governance").exists()
    (repo / "governance").mkdir()
    (repo / "governance" / "notes.txt").write_text("mine\n")
    refused(move(project, repo, "--apply"), "already has files")
    assert tree(repo / "governance") == {"notes.txt": b"mine\n"}  # nothing is overwritten


@pytest.mark.parametrize("to", ["../outside", "/abs", ".git/hooks", "a b", ""])
def test_refuses_a_bad_target_name(project, repo, to):
    refused(move(project, repo, "--to", to, "--apply"), "must be a folder name inside the repository")


@pytest.mark.parametrize("name, content, kind", [
    (".env", "X=1\n", "the file name says credentials"),
    ("plans/deploy.pem", "x\n", "the file name says credentials"),
    ("kb/notes.md", f"push with {TOKEN}\n", "GitHub token"),
    ("plans/setup.md", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", "private key"),
    ("kb/api.md", "key sk-ant-" + "x" * 30 + "\n", "Anthropic API key"),
])
def test_refuses_secrets_and_never_prints_them(project, repo, name, content, kind):
    (project / name).parent.mkdir(parents=True, exist_ok=True)
    (project / name).write_text(content)
    for extra in ((), ("--apply",)):
        r = move(project, repo, *extra)
        refused(r, f"{name}: {kind}")
        assert TOKEN not in r.stdout + r.stderr and "sk-ant-xxx" not in r.stdout
    assert not (repo / "governance").exists()


def test_refuses_a_workspace_that_is_already_in_a_repository(project, repo, tmp_path):
    assert move(project, repo, "--apply").returncode == 0
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    refused(move(repo / "governance", other), "already set up for a repository")


def test_a_failed_step_removes_the_copy(project, repo):
    cfg = json.loads((project / "governance-config.json").read_text())
    cfg["escalate_after_round"] = "soon"  # the generator refuses this
    (project / "governance-config.json").write_text(json.dumps(cfg))
    r = move(project, repo, "--apply")
    assert r.returncode == 1 and "the copy was removed again" in r.stdout and "regenerate" in r.stdout
    assert not (repo / "governance").exists()
    assert git(repo, "status", "--porcelain").strip() == ""
    # the preview already says so, before anything is copied
    r = move(project, repo)
    assert r.returncode == 1 and "cannot be regenerated" in r.stdout


def test_symlinks_are_left_out(project, repo, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the workspace\n")
    (project / "plans" / "link.md").symlink_to(outside)
    r = move(project, repo, "--apply")
    assert r.returncode == 0 and "symlinks left out: plans/link.md" in r.stdout
    assert not (repo / "governance" / "plans" / "link.md").exists()


# ---- the skill points at it -----------------------------------------------------------------------------

def test_skill_routes_to_the_move_section():
    skill = (SKILL / "SKILL.md").read_text()
    assert 'section "Moving a Project\'s workspace into the repository"' in skill and "move_workspace.py" in skill
    init = (SKILL / "init.md").read_text()
    section = init.split("## Moving a Project's workspace into the repository")[1].split("\n## ")[0]
    for phrase in ("move_workspace.py --from", "--apply", "Stop and wait for the owner's yes", "Do not ask for tokens",
                   "The\n     chats in the Project stop", "A14", "runs no git command"):
        assert phrase in section, phrase
