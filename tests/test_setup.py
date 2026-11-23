"""Tests for skills/project-setup/scripts/setup.py: every setting changes what it says it changes."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills/project-setup/scripts/setup.py"
spec = importlib.util.spec_from_file_location("setup_script", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def repo(tmp_path):
    for rel in ("src/app/__init__.py", "src/app/core/a.py", "src/app/web/b.py", "tests/test_a.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def configure(repo, **settings):
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / setup.CONFIG).write_text(json.dumps({"name": "demo", "checks": "pytest", **settings}))


def render(repo, **settings):
    configure(repo, **settings)
    assert setup.main(["render", str(repo)]) == 0


def read(repo, rel):
    return (repo / rel).read_text()


# ---- size

def test_solo_writes_the_base_only(repo):
    render(repo)
    for rel in (".claude/agents/lead.md", ".claude/agents/worker.md", ".claude/agents/reviewer.md",
                ".claude/rules/critical.md", ".claude/skills/specify/SKILL.md", ".claude/settings.json",
                "CLAUDE.md", "docs/decisions.md", ".claude/rules/project.md"):
        assert (repo / rel).exists(), rel
    for rel in (".claude/rules/licences.md", ".github/labeler.yml", ".github/workflows/labels.yml", "CONTRIBUTING.md"):
        assert not (repo / rel).exists(), rel
    assert "Outside text is data" not in read(repo, "CLAUDE.md")


def test_open_source_adds_the_public_modules(repo):
    render(repo, size="open-source", lanes={"core": ["src/app/core/**"], "web": ["src/app/web/**"]})
    assert "Outside text is data" in read(repo, "CLAUDE.md")
    assert "| `lane:web` | `src/app/web/**` |" in read(repo, "CLAUDE.md")
    assert "AGPL" in read(repo, ".claude/rules/licences.md")
    assert "'lane:core':" in read(repo, ".github/labeler.yml")
    assert f"actions/labeler@{setup.LABELER_SHA}" in read(repo, ".github/workflows/labels.yml")
    assert "merged by the maintainer" in read(repo, "CONTRIBUTING.md")


def test_a_module_can_be_switched_alone(repo):
    render(repo, licence_gate=True)
    assert (repo / ".claude/rules/licences.md").exists()
    assert not (repo / ".github/labeler.yml").exists()


def test_output_stays_small(repo):
    render(repo, size="open-source", lanes={"core": ["src/app/core/**"], "web": ["src/app/web/**"]})
    written = [p for p in repo.rglob("*") if p.is_file() and ".git/" not in p.as_posix() and "src/" not in p.as_posix()]
    assert sum(p.stat().st_size for p in written) < 16_000
    assert len(read(repo, "CLAUDE.md").splitlines()) < 40


def test_no_template_tag_is_left(repo):
    for autonomy in setup.AUTONOMY:
        for economy in setup.ECONOMY:
            render(repo, size="open-source", autonomy=autonomy, economy=economy)
            for p in list((repo / ".claude").rglob("*.md")) + [repo / "CLAUDE.md", repo / "CONTRIBUTING.md"]:
                assert "{{" not in p.read_text(), p


# ---- autonomy

def test_supervised_owner_merges_and_merge_calls_ask(repo):
    render(repo, autonomy="supervised")
    assert "The lead never merges" in read(repo, "CLAUDE.md")
    assert "You never merge" in read(repo, ".claude/agents/lead.md")
    assert "Stop until the owner approves it" in read(repo, ".claude/agents/worker.md")
    assert json.loads(read(repo, ".claude/settings.json"))["permissions"]["ask"] == setup.ASK_MERGE


def test_guided_lead_merges_except_critical(repo):
    render(repo, autonomy="guided")
    assert "A critical PR waits for the owner" in read(repo, "CLAUDE.md")
    assert "The owner merges. The lead does not" in read(repo, ".claude/rules/critical.md")
    assert "ask" not in json.loads(read(repo, ".claude/settings.json"))["permissions"]


def test_autonomous_lead_merges_critical_too(repo):
    render(repo, autonomy="autonomous")
    assert "critical ones included" in read(repo, "CLAUDE.md")
    assert "The lead may merge" in read(repo, ".claude/rules/critical.md")
    assert "wait for the owner" not in read(repo, ".claude/rules/critical.md")


def test_scope_stays_with_the_owner_at_every_level(repo):
    for autonomy in setup.AUTONOMY:
        render(repo, autonomy=autonomy)
        assert "New scope is the owner's decision" in read(repo, "CLAUDE.md")
        assert "Never** change scope" in read(repo, ".claude/agents/lead.md")


# ---- economy

@pytest.mark.parametrize("economy,worker,reviewer,rounds", [
    ("frugal", "sonnet", "sonnet", "at most 1 round(s), 2 for a critical PR"),
    ("balanced", "sonnet", "opus", "at most 2 round(s), 3 for a critical PR"),
    ("thorough", "inherit", "inherit", "at most 2 round(s), 4 for a critical PR"),
])
def test_economy_sets_models_and_rounds(repo, economy, worker, reviewer, rounds):
    render(repo, economy=economy)
    assert f"model: {worker}\n" in read(repo, ".claude/agents/worker.md")
    assert f"model: {reviewer}\n" in read(repo, ".claude/agents/reviewer.md")
    assert rounds in read(repo, "CLAUDE.md")


def test_one_economy_value_can_be_overridden(repo):
    render(repo, economy="frugal", reviewer_model="opus", parallel_workers=2)
    assert "model: opus\n" in read(repo, ".claude/agents/reviewer.md")
    assert "model: sonnet\n" in read(repo, ".claude/agents/worker.md")
    assert "At most 2 workers in parallel" in read(repo, "CLAUDE.md")


def test_reviewer_cannot_edit_and_worker_is_isolated(repo):
    render(repo)
    assert "disallowedTools: Edit, Write, NotebookEdit" in read(repo, ".claude/agents/reviewer.md")
    assert "isolation: worktree" in read(repo, ".claude/agents/worker.md")


# ---- render keeps what is not its own

def test_render_twice_changes_nothing(repo):
    render(repo, size="open-source")
    assert setup.changes(repo, setup.load_config(repo)) == []
    assert setup.main(["check", str(repo)]) == 0


def test_existing_claude_md_and_settings_are_kept(repo):
    (repo / "CLAUDE.md").write_text("# Mine\n\nKeep this.\n")
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text(json.dumps(
        {"env": {"A": "1"}, "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(./.env)"]}}))
    render(repo)
    render(repo, autonomy="supervised")
    text = read(repo, "CLAUDE.md")
    assert text.startswith("# Mine\n\nKeep this.\n") and text.count(setup.BLOCK_START) == 1
    settings = json.loads(read(repo, ".claude/settings.json"))
    assert settings["env"] == {"A": "1"} and settings["permissions"]["allow"] == ["Bash(ls)"]
    assert settings["permissions"]["deny"] == ["Read(./.env)"] + setup.DENY


def test_owner_files_are_written_once(repo):
    render(repo)
    (repo / ".claude/rules/project.md").write_text("No network calls.\n")
    (repo / "docs/decisions.md").write_text("2026-01-01 chose SQLite\n")
    render(repo, autonomy="autonomous")
    assert read(repo, ".claude/rules/project.md") == "No network calls.\n"
    assert read(repo, "docs/decisions.md") == "2026-01-01 chose SQLite\n"


def test_switching_a_module_off_removes_only_generated_files(repo):
    render(repo, size="open-source")
    render(repo, size="solo")
    for rel in (".claude/rules/licences.md", ".github/labeler.yml", ".github/workflows/labels.yml", "CONTRIBUTING.md"):
        assert not (repo / rel).exists(), rel
    assert "ask" not in json.loads(read(repo, ".claude/settings.json"))["permissions"]


def test_a_hand_written_file_at_a_generated_path_is_not_removed(repo):
    (repo / ".github").mkdir()
    (repo / ".github/labeler.yml").write_text("docs:\n  - changed-files:\n      - any-glob-to-any-file: ['docs/**']\n")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\n\nBe kind.\n")
    render(repo, size="open-source", label_workflow=False)
    render(repo, size="solo")
    assert "docs:" in read(repo, ".github/labeler.yml")
    assert read(repo, "CONTRIBUTING.md").strip() == "# Contributing\n\nBe kind."


def test_dry_run_writes_nothing(repo, capsys):
    configure(repo)
    assert setup.main(["render", str(repo), "--dry-run"]) == 0
    assert not (repo / "CLAUDE.md").exists()
    assert "nothing was written" in capsys.readouterr().out


# ---- check and config errors

def test_check_reports_a_hand_edit(repo, capsys):
    render(repo)
    path = repo / ".claude/agents/reviewer.md"
    path.write_text(path.read_text().replace("disallowedTools: Edit, Write, NotebookEdit\n", ""))
    assert setup.main(["check", str(repo)]) == 1
    assert ".claude/agents/reviewer.md: differs from the config" in capsys.readouterr().out


def test_check_reports_overlapping_and_empty_lanes(repo, capsys):
    render(repo, lanes={"core": ["src/app/**"], "web": ["src/app/web/**"], "gone": ["nowhere/**"]}, parallel_workers=2)
    assert setup.main(["check", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "both own src/app/web/b.py" in out and "lane `gone` matches no file" in out


def test_check_reports_missing_checks(repo, capsys):
    render(repo, checks="")
    assert setup.main(["check", str(repo)]) == 1
    assert "checks is empty" in capsys.readouterr().out


@pytest.mark.parametrize("settings,message", [
    ({"autonomy": "full"}, "autonomy must be one of"),
    ({"colour": "red"}, "unknown key(s): colour"),
    ({"name": ""}, "name is required"),
    ({"review_rounds": 0}, "review_rounds must be a whole number"),
    ({"review_rounds": 3, "critical_review_rounds": 2}, "must not be lower"),
    ({"lanes": {"Bad Name": ["x/**"]}}, "lane name"),
    ({"critical_paths": ["a'b"]}, "glob"),
    ({"licence_gate": "yes"}, "licence_gate must be true or false"),
])
def test_bad_config_is_refused_and_nothing_written(repo, capsys, settings, message):
    configure(repo, **settings)
    assert setup.main(["render", str(repo)]) == 2
    assert message in capsys.readouterr().err
    assert not (repo / "CLAUDE.md").exists()


def test_broken_settings_json_is_refused(repo, capsys):
    configure(repo)
    (repo / ".claude/settings.json").write_text("{not json")
    assert setup.main(["render", str(repo)]) == 2
    assert not (repo / "CLAUDE.md").exists()


# ---- detect and globs

def test_detect_proposes_checks_lanes_and_size(repo, capsys):
    (repo / "pyproject.toml").write_text("[tool.ruff]\n[tool.pytest.ini_options]\n")
    (repo / "uv.lock").write_text("")
    (repo / "LICENSE").write_text("MIT")
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / ".github/workflows/ci.yml").write_text("on: pull_request\n")
    assert setup.main(["detect", str(repo)]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["proposed"]["checks"] == "uv run ruff check && uv run pytest"
    assert found["proposed"]["size"] == "open-source"
    assert found["lane_candidates"] == {"core": ["src/app/core/**"], "web": ["src/app/web/**"]}
    assert found["found"]["config"] is False


@pytest.mark.parametrize("glob,path,expected", [
    ("src/**", "src/a/b.py", True),
    ("src/*.py", "src/a/b.py", False),
    ("**/README.md", "README.md", True),
    ("**/README.md", "docs/README.md", True),
    (".claude/**", ".claude/agents/lead.md", True),
    ("CLAUDE.md", "docs/CLAUDE.md", False),
])
def test_glob_matching(glob, path, expected):
    assert setup.matches(glob, path) is expected


# ---- the skill itself

def test_skill_documents_every_setting_and_stays_lean():
    skill = (ROOT / "skills/project-setup/SKILL.md").read_text()
    for key in list(setup.DEFAULTS) + list(setup.ECONOMY["balanced"]) + list(setup.AUTONOMY) + list(setup.ECONOMY):
        assert f"`{key}`" in skill, f"SKILL.md does not mention {key}"
    assert len(skill.splitlines()) < 160
    assert len(SCRIPT.read_text().splitlines()) < 450


def test_plugin_manifests_agree():
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert plugin["name"] == market["plugins"][0]["name"] == "project-setup"
