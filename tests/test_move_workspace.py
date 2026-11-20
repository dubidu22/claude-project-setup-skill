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
    snippet = (target / "claude-md-snippet.md").read_text()
    assert "./governance/rules/<role>.yaml" in snippet and "ask the owner which one before you change any file" in snippet
    for phrase in ("Copied", "Audit: 0 error(s)", "A14 is expected now", "open a pull request into main", "The owner applies",
                   "claude-md-snippet.md into CLAUDE.md",
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


def test_refuses_a_folder_without_a_ruleset(project, repo, tmp_path):
    (project / "claude-project-rules.yaml").unlink()
    refused(move(project, repo, "--apply"), "there is no governance to move")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.md").write_text("hello\n")
    refused(move(empty, repo), "run init")
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
    for phrase in ("move_workspace.py --from", "move_workspace.py --in-place", "--apply", "Stop and wait for the owner's yes",
                   "Never ask for tokens", "The\n     chats in the Project stop", "A14", "changes nothing in git", "unsorted/",
                   "claude-md-snippet.md", "--instructions <file>", "not a move: run the normal init"):
        assert phrase in section, phrase


# ---- a flat download ------------------------------------------------------------------------------------

def flatten(project: Path, flat: Path) -> None:
    flat.mkdir()
    for p in sorted(project.rglob("*")):
        if p.is_file() and not (flat / p.name).exists():  # README.md exists three times; a flat list keeps one
            (flat / p.name).write_bytes(p.read_bytes())


def test_a_flat_download_is_placed_by_name(project, repo, tmp_path):
    (project / "plans" / "contract-001-import.yaml").write_text("id: contract-001\n")
    (project / "plans" / "review-pr12-round1.md").write_text("# round 1\n")
    (project / "ledger" / "overrides").mkdir()
    (project / "kb" / "features").mkdir(exist_ok=True)
    (project / "kb" / "features" / "import.md").write_text("# Import\n")
    before = tree(project)
    flat = tmp_path / "flat"
    flatten(project, flat)
    (flat / "old-ledger-table.md").write_text("| pr |\n")
    r = move(flat, repo)
    assert r.returncode == 0, r.stdout
    assert "from a flat file list" in r.stdout and "pr-12.yaml -> ledger/prs/pr-12.yaml" in r.stdout
    assert "CANNOT PLACE" in r.stdout and "import.md" in r.stdout and "old-ledger-table.md" in r.stdout
    assert not (repo / "governance").exists()
    r = move(flat, repo, "--apply")
    assert r.returncode == 0, r.stdout
    after = tree(repo / "governance")
    for name in ("project-state.yaml", "roadmap.yaml", "kb/decision-log.md", "kb/pending-decisions.md", "plans/plan-001-app_cli-import.md",
                 "plans/contract-001-import.yaml", "plans/review-pr12-round1.md", "ledger/prs/pr-12.yaml", "ledger/rounds/pr12-round1.yaml"):
        assert after[name] == before[name], name
    assert after["unsorted/import.md"] == b"# Import\n" and after["unsorted/old-ledger-table.md"] == b"| pr |\n"
    # generated files are written fresh, for the repository
    assert "/mnt/project-files" not in (repo / "governance" / "rules" / "review.yaml").read_text()
    assert (repo / "governance" / "tools" / "ledger_tool.py").is_file() and (repo / "governance" / "plans" / "README.md").is_file()
    assert "In ./governance/unsorted/ for the owner to sort (2): import.md, old-ledger-table.md" in r.stdout
    assert run("ledger_tool.py", "check", "--ledger", repo / "governance" / "ledger").returncode == 0


def test_flat_ledger_entries_are_told_apart_by_their_keys(tmp_path):
    import sys
    sys.path.insert(0, str(SKILL / "scripts"))
    import move_workspace as m

    def f(name, body):
        p = tmp_path / name
        p.write_text(body)
        return m.place(name.split("__")[-1], p)

    assert f("a__pr-12.yaml", "pr: 12\nopened: 2026-01-31\nthread: impl-1\n") == "ledger/prs/pr-12.yaml"
    assert f("b__pr-12.yaml", "pr: 12\ndate: 2026-02-03\nby: owner\nhead: 3f9c2ab\nreason: x\n") == "ledger/overrides/pr-12.yaml"
    assert f("c__pr-12.yaml", "pr: 12\ndate: 2026-02-03\nby: owner\nreason: x\n") == "ledger/reverts/pr-12.yaml"
    assert f("d__pr-12.yaml", "something: else\n") is None
    assert f("pr12-round2.yaml", "") == "ledger/rounds/pr12-round2.yaml"
    assert f("review.yaml", "") == "" and f("README.md", "") == "" and f("contract_tool.py", "") == ""
    assert f("batch-003.md", "") is None  # a batch file and an audit report share this name: not guessed
    assert f("decision-log.md", "") == "kb/decision-log.md" and f("issues-contract-001.md", "") == "plans/issues-contract-001.md"


def test_flat_download_warns_about_open_prs(project, repo, tmp_path):
    (project / "ledger" / "prs" / "pr-13.yaml").write_text('pr: 13\nopened: 2026-02-02\nthread: impl-1\nlane: app_cli\nlabels: "lane:cli"\ncritical: no\ncompactions: 0\n')
    flat = tmp_path / "flat"
    flatten(project, flat)
    r = move(flat, repo)
    assert r.returncode == 0 and "the ledger shows open PRs: #13." in r.stdout


# ---- files already in the repository --------------------------------------------------------------------

@pytest.fixture
def in_repo(project, repo):
    """The Project's governance files are already committed in the repository."""
    import shutil
    shutil.copytree(project, repo / "governance")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "governance files as the Project wrote them")
    return repo


def test_in_place_regenerates_without_copying(in_repo):
    target = in_repo / "governance"
    before = tree(target)
    head = git(in_repo, "rev-parse", "HEAD")
    r = run("move_workspace.py", "--in-place", "--repo", in_repo)
    assert r.returncode == 0 and "in place" in r.stdout and "Preview only" in r.stdout and "files to copy" not in r.stdout
    assert tree(target) == before
    r = run("move_workspace.py", "--in-place", "--repo", in_repo, "--apply")
    assert r.returncode == 0, r.stdout
    after = tree(target)
    for name in ("project-state.yaml", "kb/decision-log.md", "plans/plan-001-app_cli-import.md", "ledger/prs/pr-12.yaml", "roadmap.yaml"):
        assert after[name] == before[name], name
    prof = yaml.safe_load((target / "claude-project-rules.yaml").read_text())["project_profile"]
    assert prof["environment"] == "claude_code" and prof["workspace_root"] == "./governance"
    assert "Regenerated the ruleset for ./governance" in r.stdout and "Copied" not in r.stdout
    assert (target / "github-setup" / "CODEOWNERS").is_file() and (target / "claude-md-snippet.md").is_file()
    assert git(in_repo, "rev-parse", "HEAD") == head and git(in_repo, "diff", "--cached", "--name-only") == ""  # nothing committed or staged


def test_in_place_refuses_uncommitted_changes_and_a_missing_folder(in_repo, repo):
    (in_repo / "governance" / "project-state.yaml").write_text("changed: yes\n")
    r = run("move_workspace.py", "--in-place", "--repo", in_repo, "--apply")
    refused(r, "has uncommitted changes")
    assert (in_repo / "governance" / "project-state.yaml").read_text() == "changed: yes\n"
    r = run("move_workspace.py", "--in-place", "--repo", in_repo, "--to", "nowhere")
    refused(r, "--in-place needs the files to be there already")


def test_in_place_failure_says_how_to_undo(in_repo):
    target = in_repo / "governance"
    cfg = json.loads((target / "governance-config.json").read_text())
    cfg["escalate_after_round"] = "soon"
    (target / "governance-config.json").write_text(json.dumps(cfg))
    git(in_repo, "commit", "-q", "-am", "a config the generator refuses")
    r = run("move_workspace.py", "--in-place", "--repo", in_repo, "--apply")
    assert r.returncode == 1 and "git restore -- governance" in r.stdout and "git clean -fd -- governance" in r.stdout
    assert target.is_dir()  # in place, nothing is removed


def test_from_and_in_place_exclude_each_other(project, repo):
    assert run("move_workspace.py", "--repo", repo).returncode == 2
    assert run("move_workspace.py", "--from", project, "--in-place", "--repo", repo).returncode == 2
    (repo / "governance").mkdir()
    import shutil
    shutil.copytree(project, repo / "governance" / "inner")
    refused(move(repo / "governance" / "inner", repo), "use --in-place")


# ---- an older ruleset without a config ------------------------------------------------------------------

def test_a_ruleset_without_config_is_derived_first(project, repo):
    (project / "governance-config.json").unlink()
    rules = project / "claude-project-rules.yaml"
    text = rules.read_text()
    start = text.index("  - id: META-03")
    hand = text[:start] + '  - id: HAND-01\n    applies_to: all\n    rule: "Deploys happen on Fridays only."\n' + text[start:]
    rules.write_text(hand)
    r = move(project, repo)
    assert r.returncode == 0, r.stdout
    assert "it is derived from the ruleset. Go through this with the owner first" in r.stdout and "HAND-01" in r.stdout
    assert not (project / "governance-config.json").exists()  # the source is only read
    r = move(project, repo, "--apply")
    assert r.returncode == 0, r.stdout
    target = repo / "governance"
    cfg = json.loads((target / "governance-config.json").read_text())
    assert cfg["project_name"] == "demo" and cfg["environment"] == "claude_code"
    assert "HAND-01" not in (target / "claude-project-rules.yaml").read_text()
    assert "The config was derived from a hand-kept ruleset" in r.stdout and "list the dropped rules" in r.stdout


# ---- the Project's own instructions ---------------------------------------------------------------------

def test_instructions_are_kept_as_history_that_binds_nobody(project, repo, tmp_path):
    text = tmp_path / "instructions.txt"
    text.write_text("Always answer in German.\nNever touch the billing module.\nFiles are in /mnt/project-files.\n")
    r = move(project, repo, "--instructions", text)
    assert r.returncode == 0 and "kb/imported-project-instructions.md as history; they bind nobody" in r.stdout
    r = move(project, repo, "--instructions", text, "--apply")
    assert r.returncode == 0, r.stdout
    saved = (repo / "governance" / "kb" / "imported-project-instructions.md").read_text()
    assert "**It binds nobody.**" in saved and "Never touch the billing module." in saved and "Changing settings" in saved
    assert "Go through ./governance/kb/imported-project-instructions.md with the owner" in r.stdout
    # it is history: not listed among the files to correct
    other = r.stdout.split("correct them by hand:")[1].split("\n\n")[0]
    assert "kb/verification.md" in other and "imported-project-instructions" not in other


def test_instructions_with_a_secret_or_empty_are_refused(project, repo, tmp_path):
    text = tmp_path / "instructions.txt"
    text.write_text(f"push with {TOKEN}\n")
    r = move(project, repo, "--instructions", text, "--apply")
    refused(r, "looks like it holds a secret")
    assert TOKEN not in r.stdout
    text.write_text("  \n")
    refused(move(project, repo, "--instructions", text), "is empty")
    refused(move(project, repo, "--instructions", tmp_path / "missing.txt"), "cannot read --instructions")


# ---- the CLAUDE.md block --------------------------------------------------------------------------------

def test_claude_md_snippet_only_for_a_workspace_in_the_repository(w):
    assert w.generate().returncode == 0 and w.scaffold().returncode == 0
    assert not (w.ws / "claude-md-snippet.md").exists()  # a claude.ai Project has no CLAUDE.md
    assert w.generate(None, "workspace_root=./governance").returncode == 0 and w.scaffold("--refresh").returncode == 0
    snippet = (w.ws / "claude-md-snippet.md").read_text()
    for phrase in ("## Project governance", "./governance/rules/<role>.yaml", "./governance/project-state.yaml",
                   "the owner's newest message, then the ruleset", "never by editing this block"):
        assert phrase in snippet, phrase
    assert "{{" not in snippet and len(snippet.splitlines()) < 30
