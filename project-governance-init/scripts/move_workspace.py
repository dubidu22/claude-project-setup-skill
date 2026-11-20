#!/usr/bin/env python3
"""
Move a project's governance workspace from a claude.ai Project into its repository, so the threads can run
in Claude Code and the rules get the checks that need a git checkout.

    # the files are in a folder outside the repository (downloaded from the Project)
    python3 move_workspace.py --from <folder> --repo <repository checkout> [--to governance]
    # the files are already in the repository (the Project only read them from there)
    python3 move_workspace.py --in-place --repo <repository checkout> [--to governance]
    # either way, once the owner has seen the preview and said yes:
    ... the same command with --apply
    # optional: the Project's own instructions text, saved next to the knowledge base for the owner to go through
    ... --instructions <file>

Without --apply nothing is written: it checks, lists what would go where and shows what the ruleset would
change. With --apply it

    1. copies the files into <repo>/<to>/ (not with --in-place); history is kept as it is: decision log,
       plans, contracts, roadmap, ledger, project-state.yaml,
    2. regenerates the ruleset for the new place (workspace_root=./<to>, environment claude_code),
    3. refreshes the generated files and writes github-setup/ and claude-md-snippet.md,
    4. audits the result and lists files that still name the old location.

What the source may look like:

    layout    the workspace as the skill wrote it (plans/, kb/, ledger/, rules/). Copied as it is.
    flat      all files in one folder, as a Project's file list downloads. Each file is placed by its name
              (and, for ledger entries, by its keys). Files it cannot place go to <to>/unsorted/ and are
              listed; nothing is dropped and nothing is guessed. Generated files (README.md, tools,
              role extracts) are left out, they are written fresh.
    no governance-config.json, but a claude-project-rules.yaml (an older or hand-edited ruleset)
              The config is derived from the ruleset first. The preview prints what could not be found
              and every rule the generator does not produce and would therefore drop; the owner goes
              through that list before saying yes (init.md, "Migrating an existing ruleset").
    no ruleset at all
              Refused: there is no governance to move. Run init in the repository instead.

It refuses, before writing anything, when
    - the repository path is not a git checkout, or the target folder already has files (without
      --in-place), or has uncommitted changes (with --in-place: they could not be told apart from this
      script's changes if a step fails),
    - two files would land on the same place,
    - a file looks like it holds a secret (a token, a private key, a .env file). Secrets do not go into
      a repository; the name of the file and the kind of secret are printed, never the secret.

It changes nothing in git: no branch, no commit, no pull request (THR-13, THR-14). It only asks git whether
the target folder is clean. If a step after the copy fails, the copied folder is removed again; with
--in-place it prints the two git commands that restore the folder.

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
import tempfile
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
IMPORTED_INSTRUCTIONS = "kb/imported-project-instructions.md"
HISTORY = ("kb/decision-log.md", "kb/pending-decisions.md", IMPORTED_INSTRUCTIONS, "plans/", "ledger/", "unsorted/")

# ---- placing the files of a flat download ----------------------------------------------------------------

ROOT_FILES = {"claude-project-rules.yaml", "governance-config.json", "project-state.yaml", "roadmap.yaml"}
ROLE_FILES = {f"{r}.yaml" for r in ("assist", "audit", "coordinator", "dispatcher", "implementation", "kb", "review", "specify")}
KB_FILES = {"decision-log.md", "pending-decisions.md", "verification.md"}
# written fresh by the generator and the scaffold, so a copy from the Project is not needed
REGENERATED = ROLE_FILES | {"README.md", "contract_tool.py", "ledger_tool.py", "acceptance-contracts.md", "project_instructions.md",
                           "dispatcher_instructions.md", "contract-template.yaml", "claude-md-snippet.md"}
PLAN_PATTERNS = (r"plan-.+\.md", r"review-pr\d+-round\d+\.md", r"contract-.+\.ya?ml", r"issues-.+\.md")


def keys_of(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return set(re.findall(r"^([A-Za-z_]+):", text, flags=re.MULTILINE))


def place(name: str, path: Path) -> str | None:
    """Where a file from a flat download belongs: a path in the workspace, '' for 'written fresh', None for 'cannot tell'."""
    if name in ROOT_FILES:
        return name
    if name in REGENERATED:
        return ""
    if name in KB_FILES:
        return f"kb/{name}"
    if any(re.fullmatch(p, name) for p in PLAN_PATTERNS):
        return f"plans/{name}"
    if re.fullmatch(r"pr\d+-round\d+\.ya?ml", name):
        return f"ledger/rounds/{name}"
    if re.fullmatch(r"pr\d+-\d+\.ya?ml", name):
        return f"ledger/deferred/{name}"
    if name == "since.txt":
        return "ledger/deferred/since.txt"
    if re.fullmatch(r"pr-\d+\.ya?ml", name):
        keys = keys_of(path)
        if "opened" in keys and "thread" in keys:
            return f"ledger/prs/{name}"
        if {"head", "reason", "by"} <= keys:
            return f"ledger/overrides/{name}"
        if {"reason", "by"} <= keys:
            return f"ledger/reverts/{name}"
    return None


# ---- reading the source ----------------------------------------------------------------------------------

def files_of(root: Path) -> tuple[list[Path], list[Path]]:
    """(files, symlinks that are left out), relative to root, sorted."""
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


def is_flat(source: Path, files: list[Path]) -> bool:
    """A Project's file list in one folder: no sub-folders at all."""
    return bool(files) and all(len(rel.parts) == 1 for rel in files)


def copy_plan(source: Path, files: list[Path], flat: bool) -> tuple[list[tuple[Path, str]], list[str], list[str], list[str]]:
    """(what goes where, written fresh and left out, placed in unsorted/, clashes)."""
    plan: list[tuple[Path, str]] = []
    fresh: list[str] = []
    unsorted: list[str] = []
    for rel in files:
        if not flat:
            plan.append((rel, rel.as_posix()))
            continue
        dest = place(rel.name, source / rel)
        if dest == "":
            fresh.append(rel.name)
        elif dest is None:
            unsorted.append(rel.name)
            plan.append((rel, f"unsorted/{rel.name}"))
        else:
            plan.append((rel, dest))
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for rel, dest in plan:
        if dest in seen:
            clashes.append(f"{seen[dest]} and {rel.as_posix()} would both become {dest}")
        seen[dest] = rel.as_posix()
    return plan, fresh, unsorted, clashes


def open_prs(placed: dict[str, Path]) -> list[str]:
    """PR numbers that the ledger entries show as opened and not merged."""
    merged: set[str] = set()
    opened: set[str] = set()
    for dest, path in placed.items():
        m = re.fullmatch(r"ledger/rounds/pr(\d+)-round\d+\.ya?ml", dest)
        if m and re.search(r'^merged:\s*"?[0-9a-fA-F]{4,}', path.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE):
            merged.add(m.group(1))
        m = re.fullmatch(r"ledger/prs/pr-(\d+)\.ya?ml", dest)
        if m:
            opened.add(m.group(1))
    return sorted(opened - merged, key=int)


def run(script: str, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT_DIR / script), *map(str, args)], capture_output=True, text=True)


def git_dirty(repo: Path, to: str) -> str | None:
    """Uncommitted or untracked files under <to>, as git prints them; None if git cannot say."""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", to], cwd=repo, capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def stale_references(target: Path, old_root: str) -> tuple[list[str], list[str]]:
    """Files under target that still name the old workspace location: (history files, other files)."""
    history: list[str] = []
    other: list[str] = []
    if not old_root or old_root in (".", "/") or old_root.startswith("./"):
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


def imported_text(text: str, project: str) -> str:
    return (f"# Instructions imported from the claude.ai Project of {project}\n\n"
            "This is the instructions text the Project had before the move, kept as history. **It binds nobody.** "
            "The ruleset and the role extracts say what applies now. The owner and the coordinator go through it once: "
            "a line that still matters becomes a setting (`owner_prefs`, `custom_invariants`, `critical_areas`) through "
            "\"Changing settings\"; the rest is dropped on purpose. Note the outcome in the decision log.\n\n---\n\n"
            + text.rstrip() + "\n")


def refuse(found: list[str]) -> int:
    print("Refused, nothing was written:")
    print("\n".join(f"  - {p}" for p in found))
    return 1


# ---- main --------------------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Move a governance workspace from a claude.ai Project into the repository")
    ap.add_argument("--from", dest="source", type=Path, help="folder with the Project's files (workspace layout, or all files flat)")
    ap.add_argument("--in-place", action="store_true", help="the files are already in <repo>/<to>; nothing is copied")
    ap.add_argument("--repo", type=Path, required=True, help="the repository checkout")
    ap.add_argument("--to", default="governance", help="folder inside the repository (default: governance)")
    ap.add_argument("--instructions", type=Path, help="text file with the Project's own instructions; saved as history under kb/")
    ap.add_argument("--apply", action="store_true", help="write; without it only the preview is printed")
    args = ap.parse_args()
    if bool(args.source) == bool(args.in_place):
        ap.error("give either --from <folder> (files outside the repository) or --in-place (files already in <repo>/<to>)")
    repo, to = args.repo, args.to.rstrip("/")
    found: list[str] = []

    to_ok = bool(re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", to)) and ".." not in to.split("/") and not to.startswith(".git")
    if not to_ok:
        found.append(f"--to '{to}' must be a folder name inside the repository, e.g. governance")
    repo_ok = repo.is_dir() and (repo / ".git").exists()
    if not repo_ok:
        found.append(f"--repo {repo} is not a git checkout (no .git there)")
    target = repo / to if to_ok else repo / "governance"
    source = target if args.in_place else args.source
    if not source.is_dir():
        found.append(f"{source} is not a folder" + (" (--in-place needs the files to be there already)" if args.in_place else ""))
        return refuse(found)

    files, links = files_of(source)
    flat = not args.in_place and is_flat(source, files)
    plan, fresh, unsorted, clashes = copy_plan(source, files, flat)
    placed = {dest: source / rel for rel, dest in plan}
    ruleset = placed.get("claude-project-rules.yaml")
    config = placed.get("governance-config.json")
    state = placed.get("project-state.yaml")
    cfg: dict | None = None
    derive_report = ""
    instructions: str | None = None

    scratch = Path(tempfile.mkdtemp(prefix="move-workspace-"))
    try:
        if ruleset is None:
            found.append(f"{source} has no claude-project-rules.yaml: there is no governance to move. Clone the repository, run init "
                         "there, and give init the Project's instructions as input")
        elif config is None:
            derived = scratch / "governance-config.json"
            d = run("generate_project_rules.py", "--derive-config", ruleset, *(["--state", state] if state else []), "--out", derived)
            if d.returncode != 0 or not derived.is_file():
                found.append("there is no governance-config.json and it cannot be derived from the ruleset:\n    "
                             + (d.stderr or d.stdout).strip().replace("\n", "\n    "))
            else:
                config = derived
                derive_report = d.stdout.strip()
        if config is not None:
            try:
                cfg = json.loads(config.read_text(encoding="utf-8"))
                if not isinstance(cfg, dict):
                    raise ValueError("not a JSON object")
            except (OSError, ValueError) as exc:
                found.append(f"cannot read {config}: {exc}")
                cfg = None
        if clashes:
            found.append("two files would land on the same place:\n    " + "\n    ".join(clashes))
        if cfg is not None and str(cfg.get("environment") or "") == "claude_code":
            found.append(f"this workspace is already set up for a repository (workspace_root {cfg.get('workspace_root')}); nothing to move")
        if to_ok and repo_ok:
            if args.in_place:
                dirty = git_dirty(repo, to)
                if dirty is None:
                    found.append("git could not say whether the folder is clean; --in-place needs that")
                elif dirty:
                    found.append(f"{target} has uncommitted changes; commit or stash them first, so a failed step can be undone "
                                 "with git:\n    " + dirty.replace("\n", "\n    "))
            else:
                if target.exists() and (not target.is_dir() or any(target.iterdir())):
                    found.append(f"{target} already has files; choose another folder, empty it, or use --in-place if these are the "
                                 "Project's files. Nothing is overwritten")
                try:
                    s, t = source.resolve(), target.resolve()
                    if s == t or t in s.parents or s in t.parents:
                        found.append("--from and the target folder overlap; for files that are already in the repository use --in-place")
                except OSError:
                    pass
        if args.instructions:
            try:
                instructions = args.instructions.read_text(encoding="utf-8")
                if not instructions.strip():
                    found.append(f"--instructions {args.instructions} is empty")
                elif any(p.search(instructions) for _, p in SECRET_PATTERNS):
                    found.append(f"--instructions {args.instructions} looks like it holds a secret; remove it first")
            except (OSError, UnicodeDecodeError) as exc:
                found.append(f"cannot read --instructions {args.instructions} as text: {exc}")
            if IMPORTED_INSTRUCTIONS in placed:
                found.append(f"{IMPORTED_INSTRUCTIONS} exists already; the instructions were imported before")
        secrets = secrets_in(source, files)
        if secrets:
            found.append("files that look like they hold a secret; remove them from the folder (and from the Project), a secret does "
                         "not go into a repository:\n    " + "\n    ".join(secrets))
        if found:
            return refuse(found)
        assert cfg is not None and config is not None and ruleset is not None

        old_root = str(cfg.get("workspace_root") or "")
        still_open = open_prs(placed)
        how = "in place" if args.in_place else ("from a flat file list" if flat else "from the workspace layout")
        print(f"Move the workspace of '{cfg.get('project_name', '?')}' {how}: {source} -> {target}")
        if not args.in_place:
            print(f"  files to copy: {len(plan)}" + (f"; symlinks left out: {', '.join(l.as_posix() for l in links)}" if links else ""))
        if flat:
            print("  placed by name: " + ", ".join(f"{rel.name} -> {dest}" for rel, dest in plan if not dest.startswith("unsorted/")))
            if fresh:
                print("  left out, written fresh: " + ", ".join(sorted(fresh)))
            if unsorted:
                print(f"  CANNOT PLACE, go to {to}/unsorted/ for the owner to sort: " + ", ".join(sorted(unsorted)))
        if derive_report:
            print("\n  There is no governance-config.json; it is derived from the ruleset. Go through this with the owner first:")
            print("\n".join("    " + line for line in derive_report.splitlines()))
        if instructions is not None:
            print(f"  the Project's instructions go to {to}/{IMPORTED_INSTRUCTIONS} as history; they bind nobody")
        if still_open:
            print("  WARNING: the ledger shows open PRs: " + ", ".join("#" + n for n in still_open)
                  + ". Finish or park them first; a thread in the middle of a review round loses its footing in a move.")

        if not args.apply:
            # a dry run compares with the ruleset in --out-dir; a scratch copy makes that work for a flat or derived source too
            stage = scratch / "stage"
            stage.mkdir()
            shutil.copy2(ruleset, stage / "claude-project-rules.yaml")
            if state:
                shutil.copy2(state, stage / "project-state.yaml")
            dry = run("generate_project_rules.py", "--from-json", config, "--out-dir", stage, "--set", f"workspace_root=./{to}", "--dry-run")
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
            if not args.in_place:
                for rel, dest in plan:
                    out = target / dest
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / rel, out)
            if config.parent == scratch:
                shutil.copy2(config, target / "governance-config.json")
            if instructions is not None:
                (target / "kb").mkdir(exist_ok=True)
                (target / IMPORTED_INSTRUCTIONS).write_text(
                    imported_text(instructions, str(cfg.get("project_name", "the project"))), encoding="utf-8")
            steps = [
                ("regenerate", run("generate_project_rules.py", "--from-json", target / "governance-config.json", "--out-dir", target,
                                   "--set", f"workspace_root=./{to}")),
                ("refresh", run("scaffold_workspace.py", "--from-json", target / "governance-config.json", "--out-dir", target,
                                "--refresh", "--github")),
            ]
            failed = next(((name, r) for name, r in steps if r.returncode != 0), None)
            if failed is None and not (target / "github-setup" / "README.md").is_file():
                failed = ("refresh", steps[1][1])
            if failed:
                raise RuntimeError(f"step '{failed[0]}' failed:\n{(failed[1].stderr or failed[1].stdout).strip()}")
        except (OSError, RuntimeError) as exc:
            if args.in_place:
                print(f"Refused: {exc}\nThe folder was clean in git before, so this undoes whatever was written:\n"
                      f"  git restore -- {to}\n  git clean -fd -- {to}")
                return 1
            if created:
                shutil.rmtree(target, ignore_errors=True)
            else:
                for child in target.iterdir():
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
            print(f"Refused, the copy was removed again: {exc}")
            return 1

        print(("\nRegenerated" if args.in_place else f"\nCopied {len(plan)} files, regenerated")
              + f" the ruleset for ./{to} and refreshed the generated files.")
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
                print("  (A14 is expected now: the regenerated files are not on the default branch yet. It must be gone after "
                      "the pull request below.)")
        except (ValueError, KeyError, TypeError):
            print("Audit could not be read; run audit_rules.py on the new ruleset by hand:\n" + (audit.stderr or audit.stdout).strip())

        history, other = stale_references(target, old_root)
        if other:
            print(f"\nFiles that still name the old location {old_root} and are not history; correct them by hand:")
            print("\n".join(f"  {name}" for name in other))
        if history:
            print(f"\nHistory files that name the old location {old_root} ({len(history)}): left as they are. "
                  "They record what was true then; the ruleset says where things are now.")
        if unsorted:
            print(f"\nIn ./{to}/unsorted/ for the owner to sort ({len(unsorted)}): " + ", ".join(sorted(unsorted))
                  + ". Feature notes belong in kb/features/, old ledger tables in ledger/, anything else where the owner says.")

        branch = str(json.loads((target / "governance-config.json").read_text(encoding="utf-8")).get("default_branch") or "main")
        todo = [
            f"Commit ./{to} on a branch and open a pull request into {branch}. The owner reviews and merges it: that\n"
            "     copy is the one that counts from then on (THR-14). Until it is merged, `contract_tool.py goal` and\n"
            "     `pickup` refuse, because there is no reviewed copy to compare with.",
            f"In the same pull request, put the block from ./{to}/claude-md-snippet.md into CLAUDE.md at the repository\n"
            "     root (create the file if there is none). It is how a new Claude Code session finds its rules.",
            f"The owner applies ./{to}/github-setup/ (labels, pull-request checks, CODEOWNERS, branch protection).\n"
            "     No thread does that (ROLE-14).",
            f"Start every thread fresh in Claude Code from ./{to}/rules/<role>.yaml. Chats in the Project stop: two\n"
            "     sets of threads on one repository is the one thing this move must not produce.",
            f"Record the move in the decision log (one entry: moved to ./{to}, ruleset version, date).",
            "Tokens the Project used to push are not needed any more; the owner revokes them.",
        ]
        if instructions is not None:
            todo.insert(4, f"Go through ./{to}/{IMPORTED_INSTRUCTIONS} with the owner: each line becomes a setting or is dropped.")
        if derive_report:
            todo.insert(0, "The config was derived from a hand-kept ruleset. Read the reworded rules the owner cares about side by\n"
                           "     side before the pull request, and list the dropped rules in the decision-log entry.")
        print("\nNext, in this order:")
        print("\n".join(f"  {i}. {s}" for i, s in enumerate(todo, 1)))
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
