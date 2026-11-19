#!/usr/bin/env python3
"""
Look at a repository before governance is set up on it: are the foundations there that agents need?

    python3 repo_readiness.py <repo dir> [--json]

Many threads working at once only multiply what one thread produces. If nothing in the repository tells a
thread that its change is wrong (no tests, no linter, no CI), adding lanes adds unchecked changes. This script
reads the repository and reports which foundations exist, and what that means for the setup. It reads only,
and it reports what it found, not whether the checks are any good: a test folder with one test counts.

Foundations looked for:
    ci            a CI configuration that runs on pull requests
    tests         test files or a test command
    lint          a linter or formatter configuration
    types         a type checker or a compiled, statically typed language
    run           a documented way to start or build the product (needed to verify behaviour at runtime)
    agent_docs    instructions for agents or contributors (CLAUDE.md, AGENTS.md, CONTRIBUTING.md)

Exit code: 0 always when the folder can be read (the result is advice), 2 when it cannot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__", ".tox", ".mypy_cache", "vendor"}
MAX_FILES = 20000


def walk(root: Path) -> list[Path]:
    out: list[Path] = []
    stack = [root]
    while stack and len(out) < MAX_FILES:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.name in SKIP:
                continue
            if e.is_dir() and not e.is_symlink():
                stack.append(e)
            elif e.is_file():
                out.append(e)
    return out


def text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def assess(root: Path) -> dict:
    files = walk(root)
    rel = {f.relative_to(root).as_posix(): f for f in files}
    names = {f.name for f in files}
    pyproject = text(root / "pyproject.toml")
    package = text(root / "package.json")
    try:
        pkg = json.loads(package) if package else {}
    except json.JSONDecodeError:
        pkg = {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})} if isinstance(pkg, dict) else {}
    makefile = text(root / "Makefile")
    readme = next((text(f) for n, f in rel.items() if "/" not in n and n.lower().startswith("readme")), "")

    found: dict[str, list[str]] = {k: [] for k in ("ci", "tests", "lint", "types", "run", "agent_docs")}

    # ci
    workflows = [n for n in rel if re.match(r"\.github/workflows/[^/]+\.ya?ml$", n)]
    on_pr = [n for n in workflows if re.search(r"pull_request", text(rel[n]))]
    if on_pr:
        found["ci"] += on_pr
    for other in (".gitlab-ci.yml", ".circleci/config.yml", "azure-pipelines.yml", "Jenkinsfile", ".buildkite/pipeline.yml"):
        if other in rel:
            found["ci"].append(other)
    ci_note = ""
    if workflows and not on_pr:
        ci_note = "workflows exist but none runs on pull_request"

    # tests
    test_files = [n for n in rel if re.search(r"(^|/)(tests?|__tests__|spec)/[^/]+\.[A-Za-z]+$|(^|/)test_[^/]+\.py$|[._](test|spec)\.[jt]sx?$|_test\.(go|rs|py)$", n)
                  and not n.endswith(("__init__.py", "conftest.py"))]
    if test_files:
        found["tests"].append(f"{len(test_files)} test file(s), e.g. {test_files[0]}")
    test_script = scripts.get("test", "")
    if test_script and "no test specified" not in test_script:
        found["tests"].append("package.json script: test")
    if re.search(r"^\[tool\.pytest", pyproject, re.M) or "pytest.ini" in names:
        found["tests"].append("pytest configuration")

    # lint
    lint_files = ["ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
                  "eslint.config.js", "eslint.config.mjs", "eslint.config.ts", "biome.json", "biome.jsonc", ".golangci.yml", ".golangci.yaml",
                  "clippy.toml", ".rubocop.yml", ".prettierrc", ".prettierrc.json", "stylelint.config.js", ".pre-commit-config.yaml", ".editorconfig"]
    found["lint"] += [n for n in lint_files if n in rel and n != ".editorconfig"]
    for tool in ("ruff", "black", "flake8", "pylint", "isort"):
        if re.search(rf"^\[tool\.{tool}", pyproject, re.M):
            found["lint"].append(f"pyproject.toml [tool.{tool}]")
    for dep in ("eslint", "@biomejs/biome", "prettier"):
        if dep in deps:
            found["lint"].append(f"package.json: {dep}")
    if re.search(r"import-linter|\[tool\.importlinter", pyproject) or ".importlinter" in names:
        found["lint"].append("import-linter (layer boundaries)")

    # types
    for marker, label in (("tsconfig.json", "TypeScript (tsconfig.json)"), ("mypy.ini", "mypy"), ("pyrightconfig.json", "pyright"),
                          ("Cargo.toml", "Rust"), ("go.mod", "Go")):
        if marker in rel:
            found["types"].append(label)
    for tool in ("mypy", "pyright"):
        if re.search(rf"^\[tool\.{tool}", pyproject, re.M):
            found["types"].append(f"pyproject.toml [tool.{tool}]")
    if "typescript" in deps and "TypeScript (tsconfig.json)" not in found["types"]:
        found["types"].append("package.json: typescript")

    # run
    for key in ("dev", "start", "build"):
        if key in scripts:
            found["run"].append(f"package.json script: {key}")
    if re.search(r"^\[project\.scripts\]|^\[tool\.poetry\.scripts\]", pyproject, re.M):
        found["run"].append("pyproject.toml entry point")
    if re.search(r"^(run|dev|start|serve|build):", makefile, re.M):
        found["run"].append("Makefile target")
    for marker in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "Dockerfile", "Procfile"):
        if marker in rel:
            found["run"].append(marker)
    if re.search(r"^#+\s*(getting started|usage|quick ?start|install|running|development)\b", readme, re.I | re.M):
        found["run"].append("README section on running or installing")

    # agent docs
    found["agent_docs"] += [n for n in ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", ".cursor/rules", ".github/copilot-instructions.md") if n in rel or (root / n).is_dir()]

    missing = [k for k, v in found.items() if not v]
    core_missing = [k for k in ("ci", "tests", "lint") if k in missing]
    if not files:
        level, advice = "empty", [
            "The repository is empty. Make the first milestone the foundations: a test runner, a linter, CI on pull requests, a documented way to run the product.",
            "Until they exist: max_concurrent_lanes 1, an autonomy horizon of one milestone, every PR treated as critical.",
        ]
    elif len(core_missing) >= 2:
        level, advice = "foundations missing", [
            f"Missing: {', '.join(core_missing)}. Without them nothing tells a thread that its change is wrong, and more threads only produce more unchecked changes.",
            "Set governance up small: max_concurrent_lanes 1, autonomy per milestone. Make the first work package the missing foundations, then widen.",
        ]
    elif core_missing:
        level, advice = "one gap", [
            f"Missing: {core_missing[0]}. Add it in the first batch, before work that depends on it.",
            "Start with at most 2 lanes until it is in place.",
        ]
    else:
        level, advice = "ready", ["CI, tests and a linter are present. The profile defaults fit."]
    if "run" in missing and files:
        advice.append("No documented way to start or build the product was found. Runtime verification (kb/verification.md) needs one: ask the owner, or make it part of the first batch.")
    if "types" in missing and files and not core_missing:
        advice.append("No type checker found. Optional, but types catch a class of mistakes for free.")
    if ci_note:
        advice.append(f"CI: {ci_note}; fast checks have to run on pull requests (PR-02, CI-01).")
    return {"repository": str(root), "files_seen": len(files), "found": found, "missing": missing, "level": level, "advice": advice,
            "caveat": "This reports what exists, not how good it is: read the CI workflow and a few tests before relying on them."}


def main() -> int:
    ap = argparse.ArgumentParser(description="Report which foundations for agent work a repository has")
    ap.add_argument("repo", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = args.repo.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    result = assess(root)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"# Repository readiness: {root.name}\n\nLevel: {result['level']}\n")
    for key, items in result["found"].items():
        print(f"- {key}: {'; '.join(items[:4]) if items else 'not found'}")
    print("\nWhat this means for the setup:")
    for line in result["advice"]:
        print(f"- {line}")
    print(f"\n{result['caveat']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
