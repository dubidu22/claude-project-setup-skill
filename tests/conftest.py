"""Shared helpers: every test runs the skill's scripts the way a thread would, as subprocesses."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "project-governance-init"
SCRIPTS = SKILL / "scripts"
EVALS = SKILL / "evals"
sys.path.insert(0, str(SCRIPTS))

# Runs a script with PyYAML made unimportable, to exercise the built-in readers.
NO_YAML = (
    "import sys, runpy; sys.modules['yaml'] = None; "
    "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)


def run(script: str, *args: object, cwd: Path | None = None, no_yaml: bool = False, env: dict | None = None):
    cmd = [sys.executable]
    if no_yaml:
        cmd += ["-c", NO_YAML]
    cmd += [str(SCRIPTS / script), *map(str, args)]
    full_env = {**os.environ, "GOVERNANCE_TODAY": "2026-03-04", **(env or {})}
    return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)


class Workspace:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.ws = tmp / "ws"
        self.config = self.ws / "governance-config.json"
        self.rules = self.ws / "claude-project-rules.yaml"
        self.state = self.ws / "project-state.yaml"

    def generate(self, cfg: dict | None = None, *sets: str, extra: tuple = (), env: dict | None = None):
        """First call writes a config and generates; later calls regenerate from governance-config.json."""
        if cfg is not None or not self.config.exists():
            src = self.tmp / "input.json"
            src.write_text(json.dumps(cfg if cfg is not None else {"project_name": "demo"}))
        else:
            src = self.config
        args: list[object] = ["--from-json", src, "--out-dir", self.ws]
        for s in sets:
            args += ["--set", s]
        return run("generate_project_rules.py", *args, *extra, env=env)

    def audit(self, *extra: object, no_yaml: bool = False):
        return run("audit_rules.py", self.rules, "--state", self.state, *extra, no_yaml=no_yaml)

    def scaffold(self, *extra: object):
        return run("scaffold_workspace.py", "--from-json", self.config, "--out-dir", self.ws, *extra)

    def rules_text(self) -> str:
        return self.rules.read_text()

    def rule(self, rid: str) -> str:
        import yaml

        for section in yaml.safe_load(self.rules_text()).values():
            if isinstance(section, list):
                for item in section:
                    if isinstance(item, dict) and item.get("id") == rid:
                        return item["rule"]
        raise KeyError(rid)

    def rule_ids(self) -> list[str]:
        import re

        return re.findall(r"^  - id: (\S+)", self.rules_text(), re.M)


@pytest.fixture
def w(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def findings(result) -> list[dict]:
    """Findings of `audit_rules.py --json` or `contract_tool.py lint --json`."""
    data = json.loads(result.stdout)
    return data["findings"] if isinstance(data, dict) else data


def notable(result) -> list[dict]:
    """Findings without the standing notes on invariants: no enforcing check yet (A15), check never seen to fail (A16)."""
    return [f for f in findings(result) if f["code"] not in ("A15", "A16")]


def errors(result) -> list[dict]:
    return [f for f in findings(result) if f["severity"] == "ERROR"]
