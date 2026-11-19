#!/usr/bin/env python3
"""
Move a project's governance workspace from a claude.ai Project into its repository, so the threads can run
in Claude Code and the rules get the checks that need a git checkout.

    python3 move_workspace.py --from <folder with the Project's files> --repo <repository checkout> [--to governance]
    python3 move_workspace.py --from <folder> --repo <checkout> [--to governance] --apply

Without --apply nothing is written: it checks, lists what would be copied and shows what the ruleset would
change. With --apply (only after the owner has seen the preview and said yes) it

    1. copies the files into <repo>/<to>/ (history is kept as it is: decision log, plans, contracts,
       roadmap, ledger, project-state.yaml),
    2. regenerates the ruleset for the new place (workspace_root=./<to>, environment claude_code),
    3. refreshes the generated files and writes github-setup/,
    4. audits the result and lists files that still name the old location.

It refuses, before copying anything, when
    - the source has no governance-config.json (not set up with the generator: migrate or init first),
    - the repository path is not a git checkout, or the target folder already has files,
    - a file looks like it holds a secret (a token, a private key, a .env file). Secrets do not go into
      a repository; the name of the file and the kind of secret are printed, never the secret.

It never runs git: branches, commits and the pull request are the thread's and the owner's (THR-13, THR-14).
If a step after the copy fails, the copied folder is removed again, so a second try starts clean.

Exit code: 0 done (or preview without problems), 1 refused, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKIP_NAMES = {".git", "__pycache__", ".DS_Store", "Thumbs.db"}
SECRET_NAMES = re.compile(r"(^\.env(\..+)?$|\.pem$|\.key$|\.p12$|\.pfx$|^id_(rsa|dsa|ecdsa|ed25519)$|^credentials.*\.json$|^\.netrc$|^\.npmrc$)", re.IGNORECASE)
SECRET_PATTERNS = [
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
MAX_SCAN_BYTES = 2_000_000
HISTORY = ("kb/decision-log.md", "kb/pending-decisions.md", "plans/", "ledger/")


def files_of(root: Path) -> tuple[list[Path], list[Path]]:
    """(files to copy, symlinks that are left out), relative to root, sorted."""
    keep: list[Path] = []
    links: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_NAMES and not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if name in SKIP_NAMES:
                continue
            (links if p.is_symlink() else keep).append(p.relative_to(root))
    return keep, links


def secrets_in(root: Path, files: list[Path]) -> list[str]:
    """`<file>: <kind>` for files that look like they hold a secret. The secret itself is never returned."""
    out: list[str] = []
    for rel in files:
        if SECRET_NAMES.search(rel.name):
            out.append(f"{rel.as_posix()}: the file name says credentials")
            continue
        p = root / rel
        try:
            if p.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                out.append(f"{rel.as_posix()}: {kind}")
    return out


def open_prs(source: Path) -> list[str]:
    """PR numbers that the ledger shows as opened and not merged."""
    sys.path.insert(0, str(SCRIPT_DIR))
    import ledger_tool

    ledger = source / "ledger"
    if not ledger.is_dir():
        return []
    prs, rounds = ledger_tool.load(ledger)
    merged = {r.get("pr") for r in rounds if r.get("merged")}
    return sorted({e.get("pr", "") for e in prs if e.get("pr") and e.get("pr") not in merged}, key=ledger_tool.num)


def problems(source: Path, repo: Path, to: str) -> tuple[list[str], dict | None]:
    out: list[str] = []
    cfg = None
    if not source.is_dir():
        return [f"--from {source} is not a folder"], None
    config = source / "governance-config.json"
    if not config.is_file():
        hint = ("it has a claude-project-rules.yaml, so bring it onto the generator first (init.md, \"Migrating an existing "
                "ruleset\")" if (source / "claude-project-rules.yaml").is_file()
                else "run init in the repository instead: there is no governance to move")
        out.append(f"{source} has no governance-config.json; {hint}")
    else:
        try:
            cfg = json.loads(config.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as exc:
            out.append(f"cannot read {config}: {exc}")
            cfg = None
    if not (source / "claude-project-rules.yaml").is_file():
        out.append(f"{source} has no claude-project-rules.yaml: the folder does not look like a governance workspace. "
                   "Files downloaded from a Project have to keep the workspace layout (plans/, kb/, ledger/, rules/)")
    elif not (source / "rules").is_dir() or not (source / "kb" / "decision-log.md").is_file():
        out.append(f"{source} has the ruleset but not the workspace layout (no rules/ folder or no kb/decision-log.md). Files "
                   "downloaded flat from a Project have to be sorted into plans/, kb/, ledger/ and rules/ first; this script "
                   "does not guess where a file belongs")
    if not repo.is_dir() or not (repo / ".git").exists():
        out.append(f"--repo {repo} is not a git checkout (no .git there)")
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", to) or ".." in to.split("/") or to.startswith(".git"):
        out.append(f"--to '{to}' must be a folder name inside the repository, e.g. governance")
    else:
        target = repo / to
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            out.append(f"{target} already has files; choose another folder or empty it first. Nothing is overwritten")
        try:
            if repo.is_dir() and source.resolve() == target.resolve():
                out.append("--from and the target are the same folder")
            elif repo.is_dir() and target.resolve() in source.resolve().parents:
                out.append("--from lies inside the target folder")
        except OSError:
            pass
    if cfg is not None and str(cfg.get("environment") or "") == "claude_code":
        out.append(f"this workspace is already set up for a repository (workspace_root {cfg.get('workspace_root')}); nothing to move")
    return out, cfg


def run(script: str, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT_DIR / script), *map(str, args)], capture_output=True, text=True)


def stale_references(target: Path, old_root: str) -> tuple[list[str], list[str]]:
    """Files under target that still name the old workspace location: (history files, other files)."""
    history: list[str] = []
    other: list[str] = []
    if not old_root or old_root in (".", "/"):
        return history, other
    files, _ = files_of(target)
    for rel in files:
        try:
            if (target / rel).stat().st_size > MAX_SCAN_BYTES:
                continue
            n = (target / rel).read_text(encoding="utf-8", errors="ignore").count(old_root)
        except OSError:
            continue
        if n:
            name = rel.as_posix()
            (history if name.startswith(HISTORY) and not name.endswith("README.md") else other).append(f"{name} ({n})")
    return history, other


def main() -> int:
    ap = argparse.ArgumentParser(description="Move a governance workspace from a claude.ai Project into the repository")
    ap.add_argument("--from", dest="source", type=Path, required=True, help="folder with the Project's files, in the workspace layout")
    ap.add_argument("--repo", type=Path, required=True, help="the repository checkout")
    ap.add_argument("--to", default="governance", help="folder inside the repository (default: governance)")
    ap.add_argument("--apply", action="store_true", help="copy and regenerate; without it only the preview is printed")
    args = ap.parse_args()
    source, repo, to = args.source, args.repo, args.to.rstrip("/")

    found, cfg = problems(source, repo, to)
    files, links = files_of(source) if source.is_dir() else ([], [])
    secrets = secrets_in(source, files)
    if secrets:
        found.append("files that look like they hold a secret; remove them from the folder (and from the Project), a secret does "
                     "not go into a repository:\n    " + "\n    ".join(secrets))
    if found:
        print("Refused, nothing was written:")
        print("\n".join(f"  - {p}" for p in found))
        return 1
    assert cfg is not None
    target = repo / to
    old_root = str(cfg.get("workspace_root") or "")
    still_open = open_prs(source)

    print(f"Move the workspace of '{cfg.get('project_name', '?')}' from {source} to {target}")
    print(f"  files to copy: {len(files)}" + (f"; symlinks left out: {', '.join(l.as_posix() for l in links)}" if links else ""))
    if still_open:
        print("  WARNING: the ledger shows open PRs: " + ", ".join("#" + n for n in still_open)
              + ". Finish or park them first; a thread in the middle of a review round loses its footing in a move.")

    if not args.apply:
        dry = run("generate_project_rules.py", "--from-json", source / "governance-config.json", "--out-dir", source,
                  "--set", f"workspace_root=./{to}", "--dry-run")
        if dry.returncode != 0:
            print("Refused: the ruleset cannot be regenerated for the new place:\n" + (dry.stderr or dry.stdout).strip())
            return 1
        print("\nWhat the ruleset would change:")
        print("\n".join("  " + line for line in dry.stdout.strip().splitlines()))
        print("\nPreview only, nothing was written. Show this to the owner; after their yes, run the same command with --apply.")
        return 0

    created = not target.exists()
    try:
        target.mkdir(parents=True, exist_ok=True)
        for rel in files:
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, dest)
        steps = [
            ("regenerate", run("generate_project_rules.py", "--from-json", target / "governance-config.json", "--out-dir", target,
                               "--set", f"workspace_root=./{to}")),
            ("refresh", run("scaffold_workspace.py", "--from-json", target / "governance-config.json", "--out-dir", target,
                            "--refresh", "--github")),
        ]
        failed = next(((name, r) for name, r in steps if r.returncode != 0), None)
        if failed is None:
            # scaffold_workspace.py reports a config it cannot read on stderr with exit 0 on some paths; make sure it ran
            if not (target / "github-setup" / "README.md").is_file():
                failed = ("refresh", steps[1][1])
        if failed:
            raise RuntimeError(f"step '{failed[0]}' failed:\n{(failed[1].stderr or failed[1].stdout).strip()}")
    except (OSError, RuntimeError) as exc:
        if created:
            shutil.rmtree(target, ignore_errors=True)
        else:
            for child in target.iterdir():
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
        print(f"Refused, the copy was removed again: {exc}")
        return 1

    print(f"\nCopied {len(files)} files, regenerated the ruleset for ./{to} and refreshed the generated files.")
    audit = run("audit_rules.py", target / "claude-project-rules.yaml", "--state", target / "project-state.yaml", "--json")
    try:
        data = json.loads(audit.stdout)
        findings = data["findings"] if isinstance(data, dict) else data
        errors = [f for f in findings if f.get("severity") == "ERROR"]
        warns = [f for f in findings if f.get("severity") == "WARN"]
        print(f"Audit: {len(errors)} error(s), {len(warns)} warning(s).")
        for f in errors + warns:
            print(f"  {f.get('severity')} {f.get('code')}: {f.get('message')}")
        if any(f.get("code") == "A14" for f in warns + errors):
            print("  (A14 is expected now: the files are not on the default branch yet. It must be gone after the pull request below.)")
    except (ValueError, KeyError, TypeError):
        print("Audit could not be read; run audit_rules.py on the new ruleset by hand:\n" + (audit.stderr or audit.stdout).strip())

    history, other = stale_references(target, old_root)
    if other:
        print(f"\nFiles that still name the old location {old_root} and are not history; correct them by hand:")
        print("\n".join(f"  {name}" for name in other))
    if history:
        print(f"\nHistory files that name the old location {old_root} ({len(history)}): left as they are. "
              "They record what was true then; the ruleset says where things are now.")

    branch = str(json.loads((target / "governance-config.json").read_text(encoding="utf-8")).get("default_branch") or "main")
    print(f"""
Next, in this order:
  1. Commit ./{to} on a branch and open a pull request into {branch}. The owner reviews and merges it: that
     copy is the one that counts from then on (THR-14). Until it is merged, `contract_tool.py goal` and
     `pickup` refuse, because there is no reviewed copy to compare with.
  2. The owner applies ./{to}/github-setup/ (labels, pull-request checks, CODEOWNERS, branch protection).
     No thread does that (ROLE-14).
  3. Start every thread fresh in Claude Code from ./{to}/rules/<role>.yaml. Chats in the Project stop: two
     sets of threads on one repository is the one thing this move must not produce.
  4. Record the move in the decision log (one entry: moved to ./{to}, ruleset version, date).
  5. Tokens the Project used to push are not needed any more; the owner revokes them.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
