#!/usr/bin/env python3
"""
Project rules generator for multi-thread Claude projects.

Writes, from one config:
  1. `claude-project-rules.yaml`  static rules, project profile, model routing, token economy
  2. `rules/<role>.yaml`          per-role extracts: what one thread type reads at its start
  3. `project-state.yaml`         volatile runtime state (kept on regeneration unless --reset-state)
  4. `governance-config.json`     the normalized config; the rules are regenerated from it

Usage:
    python3 generate_project_rules.py --from-json config.json --out-dir <workspace>
    python3 generate_project_rules.py --from-json <ws>/governance-config.json --out-dir <ws> --set KEY=VALUE --dry-run
    python3 generate_project_rules.py --derive-config <old rules.yaml> [--state <state.yaml>] [--out derived.json]
    python3 generate_project_rules.py --dump-schema | --model-presets
    python3 generate_project_rules.py            (interactive terminal wizard)

Every value is type-checked before anything is written (exit 2 on a bad value), every
free-text value is quoted, and the generated YAML is parsed again before it is saved
(exit 3 if it does not parse). `--dump-schema` lists the config keys and their defaults.
Unknown keys are ignored with a warning on stderr.

Exit codes: 0 written (or dry run), 2 bad config or arguments, 3 the output failed its own check.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


TOKEN_PROFILES: dict[str, dict[str, Any]] = {
    "frugal": {
        "description": "Minimizes token spend on coordination while keeping strong models on critical paths and two review rounds.",
        "max_concurrent_lanes": 2,
        "replace_at_compressions": 1,
        "replace_after_prs": 2,
        "watchdog_interval_minutes": 120,
        "watchdog_max_nudges": 3,
        "non_critical_max_review_rounds": 2,
        "critical_max_review_rounds": 4,
        "batch_audit_mode": "critical_only",
        "kb_pr_cadence": "per_milestone_or_batch",
        "reporting_verbosity": "ultra_terse",
        "offload_heavy_checks_to_ci": True,
        "goal_turn_cap": 20,
    },
    "balanced": {
        "description": "Recommended balance of velocity, quality gates, and token efficiency.",
        "max_concurrent_lanes": 3,
        "replace_at_compressions": 2,
        "replace_after_prs": 3,
        "watchdog_interval_minutes": 60,
        "watchdog_max_nudges": 3,
        "non_critical_max_review_rounds": 2,
        "critical_max_review_rounds": 4,
        "batch_audit_mode": "light_every_batch",
        "kb_pr_cadence": "daily",
        "reporting_verbosity": "terse_batched",
        "offload_heavy_checks_to_ci": True,
        "goal_turn_cap": 30,
    },
    "max_velocity": {
        "description": "Maximum parallel throughput and full continuous auditing.",
        "max_concurrent_lanes": 3,
        "replace_at_compressions": 2,
        "replace_after_prs": 4,
        "watchdog_interval_minutes": 30,
        "watchdog_max_nudges": 4,
        "non_critical_max_review_rounds": 2,
        "critical_max_review_rounds": 4,
        "batch_audit_mode": "full_every_batch",
        "kb_pr_cadence": "daily",
        "reporting_verbosity": "standard",
        "offload_heavy_checks_to_ci": True,
        "goal_turn_cap": 40,
    },
}


STACK_PRESETS: dict[str, dict[str, Any]] = {
    "python_cli_or_service": {
        "execution_lanes": ["core_pipeline", "text_or_data", "app_cli", "docs_release"],
        "file_ownership_labels": [
            "lane:core",
            "lane:pipeline",
            "lane:data",
            "lane:app",
            "lane:cli",
            "lane:infra",
            "lane:docs",
        ],
        "lane_mapping_note": (
            "core_pipeline owns pipeline; text_or_data owns data; app_cli owns app and cli. "
            "core is cross-cutting and critical (requires lane:infra). docs may be edited by any lane."
        ),
        "fast_checks": "lint, format check, import-linter, dependency check, fast unit tests",
        "layer_boundary_check": "import linting",
    },
    "fullstack_web": {
        "execution_lanes": ["backend_api", "frontend_ui", "infra_data", "docs_release"],
        "file_ownership_labels": [
            "lane:core",
            "lane:backend",
            "lane:frontend",
            "lane:db",
            "lane:infra",
            "lane:docs",
        ],
        "lane_mapping_note": (
            "backend_api owns backend; frontend_ui owns frontend; infra_data owns db and infra. "
            "core is cross-cutting and critical (requires lane:infra). docs may be edited by any lane."
        ),
        "fast_checks": "lint, typecheck, unit tests, browser smoke tests on UI changes",
        "layer_boundary_check": "",
    },
    "custom": {
        "execution_lanes": ["lane_a", "lane_b", "app_release"],
        "file_ownership_labels": ["lane:core", "lane:a", "lane:b", "lane:app", "lane:infra", "lane:docs"],
        "lane_mapping_note": (
            "Define explicit mapping from file-ownership labels to execution lanes. "
            "core is cross-cutting and critical (requires lane:infra). docs may be edited by any lane."
        ),
        "fast_checks": "lint, format check, fast test suite",
        "layer_boundary_check": "",
    },
}


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer if answer else default


def ask_bool(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = ask(f"{prompt} ({hint})", "y" if default else "n").lower()
    return raw in {"y", "yes", "j", "ja", "1", "true"}


def ask_choice(prompt: str, options: list[str], default: str) -> str:
    opts_str = " / ".join(options)
    while True:
        val = ask(f"{prompt} ({opts_str})", default).strip()
        if val in options:
            return val
        print(f"  Invalid choice '{val}'. Choose one of: {opts_str}")


def ask_list(prompt: str, default_items: list[str]) -> list[str]:
    default_str = ", ".join(default_items)
    raw = ask(f"{prompt} (comma-separated)", default_str)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items if items else default_items


def one_line(text: Any) -> str:
    """Collapse a value to one line of text (YAML scalars and comments stay on one line)."""
    return " ".join(str(text).split())


def yaml_quote(text: Any) -> str:
    """Double-quoted YAML scalar. Every free-text value goes through this, so ':' or '#' cannot break the file."""
    out = []
    for ch in str(text):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def yaml_list(items: list[Any]) -> str:
    """Inline YAML list with every item quoted."""
    return "[" + ", ".join(yaml_quote(i) for i in items) + "]"


def header(stage_num: int, title: str, explanation: str) -> None:
    print("\n" + "=" * 72)
    print(f"STAGE {stage_num}/6: {title}")
    print("-" * 72)
    print(explanation)
    print("=" * 72)


# Model routing presets. Names carry no version numbers on purpose: versions go
# stale, and the owner types the names their model picker shows.
MODEL_SLOTS = (
    ("coordinator_model", "coordinator", "Coordinator (lives for the whole project)"),
    ("specify_model", "specify", "Specify threads (interview, research, acceptance criteria)"),
    ("critical_model", "critical_work", "Critical work: implementation and review of critical PRs, escalations"),
    ("implementation_model", "implementation", "Routine implementation"),
    ("review_model", "review_kb_audit", "Routine review, KB and audit threads"),
    ("ops_model", "operations", "Dispatcher and assist threads"),
)
MODEL_PRESETS: dict[str, dict[str, str]] = {
    "economy": {
        "coordinator_model": "Opus",
        "specify_model": "Opus (high effort)",
        "critical_model": "Opus (high effort)",
        "implementation_model": "Sonnet (high effort)",
        "review_model": "Sonnet (high effort)",
        "ops_model": "Sonnet",
    },
    "balanced": {
        "coordinator_model": "Opus",
        "specify_model": "Opus (high effort)",
        "critical_model": "Opus (high effort)",
        "implementation_model": "Opus (medium effort)",
        "review_model": "Opus (medium effort)",
        "ops_model": "Sonnet",
    },
    "max": {
        "coordinator_model": "Fable",
        "specify_model": "Fable",
        "critical_model": "Opus (high effort)",
        "implementation_model": "Opus (high effort)",
        "review_model": "Opus (medium effort)",
        "ops_model": "Sonnet",
    },
}
DEFAULT_MODEL_PRESET = "balanced"


ENVIRONMENTS = ("claude_ai_project", "claude_code")
# Where a pull request may add markdown files (PR-05). Everything else needs the plan or an exemption.
DEFAULT_DOC_PATHS = ["docs/**", "**/README.md", "CHANGELOG.md", "CONTRIBUTING.md", ".github/**"]
DEFAULT_CRITICAL_AREAS = [
    "layer contracts",
    "core data structures",
    "KB process/architecture docs (excluding daily decision-log batch PRs)",
    "packaging/release/CI",
    "safety mechanisms",
    "licences",
    "network calls",
]
# Keys older generator versions wrote into governance-config.json. They are read and mapped, never warned about.
LEGACY_KEYS = {"today", "round4_hard_stop", "coordinator_compact_at_tokens", "critical_worker_model", "standard_worker_model"}
# Options that used to be written into every ruleset. A config from before they became options gets a note.
FORMER_HABITS = {
    "owner_prefs": 'owner_prefs=["Shell commands contain no inline comments inside code blocks; explanations go outside."]',
    "local_ui_loopback_only": "local_ui_loopback_only=true (local web UIs bind to 127.0.0.1)",
    "github_rest_only": "github_rest_only=true (use REST where GraphQL is blocked)",
    "critical_areas": 'critical_areas with "golden/regression files" and "user-file deletion paths" added',
}


class ConfigError(ValueError):
    """One or more config values have the wrong type or an unknown choice."""


def derive_environment(workspace_root: str) -> str:
    return "claude_ai_project" if str(workspace_root).rstrip("/").startswith("/mnt/project-files") else "claude_code"


def default_config(project_name: str = "my-project") -> dict[str, Any]:
    stack_key = "python_cli_or_service"
    preset = STACK_PRESETS[stack_key]
    profile_key = "balanced"
    return {
        "ruleset_version": "2.0.0",
        "project_name": project_name,
        "repo_slug": f"owner/{project_name}",
        "is_public": True,
        "owner_name": "Project Owner",
        "owner_gh": "owner",
        "timezone": "UTC",
        "local_os_shell": "unspecified",
        "local_clone_path": f"~/projects/{project_name}",
        "workspace_root": "/mnt/project-files",
        "environment": "",
        "default_branch": "main",
        "governance_branch": "governance",
        "stack_key": stack_key,
        "fast_checks": preset["fast_checks"],
        "layer_boundary_check": preset["layer_boundary_check"],
        "target_platforms": ["ubuntu-latest", "macos-latest", "windows-latest"],
        "model_preset": DEFAULT_MODEL_PRESET,
        **MODEL_PRESETS[DEFAULT_MODEL_PRESET],
        "escalate_after_round": 2,
        "rounds_after_escalation": 2,
        "profile_key": profile_key,
        "token_cfg": dict(TOKEN_PROFILES[profile_key]),
        "autonomy_horizon": "until v1.0 is finished",
        "owner_hand_steps": [
            "listening or manual UX/accessibility pass",
            "local hardware benchmark run",
            "pushing release tags and package registry publishing",
            "repository settings, rulesets and milestone creation",
        ],
        "notify_triggers": [
            "first usable build ready for personal testing",
            "target autonomy milestone complete",
        ],
        "execution_lanes": list(preset["execution_lanes"]),
        "ownership_labels": list(preset["file_ownership_labels"]),
        "lane_mapping_note": preset["lane_mapping_note"],
        "allow_parallel_release_branch": True,
        "critical_areas": list(DEFAULT_CRITICAL_AREAS),
        "critical_paths": [],
        "no_telemetry": True,
        "local_ui_loopback_only": False,
        "github_rest_only": False,
        "banned_licences": ["AGPL", "SSPL", "non-commercial", "unclear"],
        "licence_check": "",
        "telemetry_check": "",
        "custom_invariants": [],
        "label_paths": [],
        "seam_groups": [],
        "seam_audit_every_prs": 15,
        "doc_paths": list(DEFAULT_DOC_PATHS),
        "runtime_verification": True,
        "owner_prefs": [],
        "acceptance_contracts": True,
        "dispatcher": True,
        "advisor": False,
        "advisor_model": "",
        "governance_paths": [],
        "promised_tests_check": "",
        "cache_ttl_minutes": 60,
        "coordinator_compact_every_batches": 1,
        "active_milestones": ["v0.1"],
    }


# Lower bounds for integer settings. Everything else that is an int must be >= 0.
INT_MIN = {
    "cache_ttl_minutes": 1,
    "max_concurrent_lanes": 1,
    "replace_at_compressions": 1,
    "replace_after_prs": 1,
    "watchdog_interval_minutes": 1,
    "non_critical_max_review_rounds": 1,
    "critical_max_review_rounds": 1,
    "goal_turn_cap": 1,
    "rounds_after_escalation": 1,
    "seam_audit_every_prs": 5,
}
CHOICES = {
    "stack_key": tuple(STACK_PRESETS),
    "profile_key": tuple(TOKEN_PROFILES),
    "model_preset": (*MODEL_PRESETS, "custom"),
    "environment": ENVIRONMENTS,
}
NON_EMPTY_LISTS = {"execution_lanes", "ownership_labels", "target_platforms"}
NON_EMPTY_STRINGS = {"project_name", "repo_slug", "owner_name", "workspace_root", "default_branch", "governance_branch",
                     *(k for k, _, _ in MODEL_SLOTS)}


def _type_problem(name: str, value: Any, template: Any) -> str | None:
    """Return a message when value does not have the type of template (taken from the defaults)."""
    if isinstance(template, bool):
        if not isinstance(value, bool):
            return f"{name} must be true or false, got {value!r}"
    elif isinstance(template, int):
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be a whole number, got {value!r}"
        low = INT_MIN.get(name.split(".")[-1], 0)
        if value < low:
            return f"{name} must be at least {low}, got {value}"
    elif isinstance(template, list):
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            return f"{name} must be a list of non-empty strings, e.g. [\"a\", \"b\"], got {value!r}"
        if name in NON_EMPTY_LISTS and not value:
            return f"{name} must not be empty"
    elif isinstance(template, str):
        if not isinstance(value, str):
            return f"{name} must be text, got {value!r}"
        if name in NON_EMPTY_STRINGS and not value.strip():
            return f"{name} must not be empty"
        if name in CHOICES and value not in CHOICES[name]:
            return f"{name} must be one of: {', '.join(CHOICES[name])}; got {value!r}"
    return None


def validate_config(cfg: dict[str, Any]) -> None:
    """Raise ConfigError listing every value with a wrong type, range or choice."""
    base = default_config()
    base["environment"] = "claude_code"  # a non-empty template so the choice check applies
    problems: list[str] = []
    for key, template in base.items():
        if key == "token_cfg":
            continue
        msg = _type_problem(key, cfg.get(key), template)
        if msg:
            problems.append(msg)
    tok = cfg.get("token_cfg")
    if not isinstance(tok, dict):
        problems.append("token_cfg must be an object")
    else:
        for key, template in TOKEN_PROFILES["balanced"].items():
            if key == "description":
                continue
            msg = _type_problem(f"token_cfg.{key}", tok.get(key), template)
            if msg:
                problems.append(msg)
        nc, cr = tok.get("non_critical_max_review_rounds"), tok.get("critical_max_review_rounds")
        if isinstance(nc, int) and isinstance(cr, int) and not isinstance(nc, bool) and nc > cr:
            problems.append(f"token_cfg.non_critical_max_review_rounds ({nc}) must not exceed critical_max_review_rounds ({cr})")
    for label in cfg.get("ownership_labels") or []:
        if isinstance(label, str) and not re.fullmatch(r"lane:[a-z0-9_-]+", label):
            problems.append(f"ownership_labels: '{label}' must look like lane:<name> (lower case, digits, - or _)")
    labels = cfg.get("ownership_labels") if isinstance(cfg.get("ownership_labels"), list) else []
    for glob in cfg.get("governance_paths") if isinstance(cfg.get("governance_paths"), list) else []:
        if isinstance(glob, str) and (glob.startswith("/") or ".." in glob.split("/") or glob.strip() in ("*", "**", "**/*")):
            problems.append(f"governance_paths: '{glob}': a glob is a path from the repository root, without a leading / "
                            "or .., and not everything")
    if cfg.get("advisor") is True and isinstance(cfg.get("advisor_model"), str) and cfg.get("advisor_model") \
            and cfg.get("advisor_model") == cfg.get("coordinator_model"):
        problems.append("advisor_model is the coordinator's model: an advisor on the same model adds a session and no judgment. "
                        "Use a stronger model for the advisor, or leave advisor off")
    seen_groups: set[str] = set()
    for entry in cfg.get("seam_groups") if isinstance(cfg.get("seam_groups"), list) else []:
        if not isinstance(entry, str):
            continue
        name, sep, rest = entry.partition("=")
        paths = [x.strip() for x in rest.split(",")]
        if not sep or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) or not all(paths):
            problems.append(f"seam_groups: '{entry}' must look like <name>=<path>,<path>, e.g. web=web/api.py,web/jobs.py")
            continue
        if name in seen_groups:
            problems.append(f"seam_groups: the group name '{name}' is used twice")
        seen_groups.add(name)
        if any(x.startswith("/") or ".." in x.split("/") or x in ("*", "**", "**/*") for x in paths):
            problems.append(f"seam_groups: '{entry}': each path is a file or glob from the repository root, without a leading / "
                            "or .., and not everything")
        elif len(paths) < 2 and "*" not in rest:
            problems.append(f"seam_groups: '{entry}' names one file; a seam is between files, so name at least two (or a glob)")
    for entry in cfg.get("label_paths") if isinstance(cfg.get("label_paths"), list) else []:
        if not isinstance(entry, str):
            continue
        label, sep, glob = entry.partition("=")
        if not sep or not glob.strip() or label.strip() != label or glob.strip() != glob:
            problems.append(f"label_paths: '{entry}' must look like lane:<name>=<glob>, e.g. lane:cli=src/cli/**")
        elif label not in labels:
            problems.append(f"label_paths: '{entry}' names a label that is not in ownership_labels")
        elif glob.startswith("/") or ".." in glob.split("/"):
            problems.append(f"label_paths: '{entry}': the glob is a path from the repository root, without a leading / or ..")
    for glob in cfg.get("doc_paths") if isinstance(cfg.get("doc_paths"), list) else []:
        if isinstance(glob, str) and (not glob.strip() or glob.strip() != glob or glob.startswith("/") or ".." in glob.split("/")):
            problems.append(f"doc_paths: '{glob}': a glob is a path from the repository root, without a leading / or ..")
        elif isinstance(glob, str) and glob in ("*", "**", "**/*", "**/*.md", "*.md"):
            problems.append(f"doc_paths: '{glob}' allows new markdown files everywhere or all over the root, which is what PR-05 forbids; "
                            "name the folders and file names instead, e.g. docs/** and **/README.md")
    for key in ("default_branch", "governance_branch"):
        v = cfg.get(key)
        if isinstance(v, str) and v and not re.fullmatch(r"[A-Za-z0-9._/-]+", v):
            problems.append(f"{key} '{v}' is not a plain branch name")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(cfg.get("ruleset_version", ""))):
        problems.append(f"ruleset_version must look like 2.0.0, got {cfg.get('ruleset_version')!r}")
    if problems:
        raise ConfigError("\n".join(problems))


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults, map legacy keys, then validate. Raises ConfigError on a bad value."""
    if not isinstance(raw, dict):
        raise ConfigError("the config must be a JSON object")
    raw = dict(raw)
    name = raw.get("project_name", "my-project")
    base = default_config(name if isinstance(name, str) and name.strip() else "my-project")

    # --- legacy keys -------------------------------------------------------
    legacy_config = "today" in raw and "ruleset_version" not in raw  # written by a generator before 2.1
    raw.pop("today", None)  # the date is stamped at every run, never stored
    if "round4_hard_stop" in raw:
        if raw.pop("round4_hard_stop") is not True:
            raise ConfigError(
                "round4_hard_stop can no longer be turned off: a critical PR that has not converged at its last "
                "review round always stops for the owner (invariant 5). To change the round, set "
                "token_cfg.critical_max_review_rounds."
            )
    if "coordinator_compact_at_tokens" in raw:
        old = raw.pop("coordinator_compact_at_tokens")
        if isinstance(old, bool) or not isinstance(old, int) or old < 0:
            raise ConfigError(f"coordinator_compact_at_tokens must be a whole number >= 0, got {old!r}")
        raw.setdefault("coordinator_compact_every_batches", 1 if old > 0 else 0)
    if legacy_config:
        missing = [text for key, text in FORMER_HABITS.items() if key not in raw]
        if missing:
            print(
                "note: this config was written before some rules became options; they are now off. "
                "To keep one, set: " + "; ".join(missing),
                file=sys.stderr,
            )

    # A named preset fills the six model slots; explicit slot keys below still win.
    preset = raw.get("model_preset")
    if preset in MODEL_PRESETS:
        base.update(MODEL_PRESETS[preset])
    elif preset not in (None, "custom"):
        raise ConfigError(f"model_preset must be one of: {', '.join(MODEL_PRESETS)}, custom; got {preset!r}")
    # Configs written before the routing was split had two worker models.
    old_critical = raw.pop("critical_worker_model", None)
    old_standard = raw.pop("standard_worker_model", None)
    if old_critical or old_standard:
        raw.setdefault("model_preset", "custom")
        if old_critical:
            for k in ("critical_model", "implementation_model", "specify_model"):
                raw.setdefault(k, old_critical)
        if old_standard:
            for k in ("review_model", "ops_model"):
                raw.setdefault(k, old_standard)

    stack_key = raw.get("stack_key", base["stack_key"])
    if stack_key in STACK_PRESETS:
        sp = STACK_PRESETS[stack_key]
        base["fast_checks"] = sp["fast_checks"]
        base["layer_boundary_check"] = sp["layer_boundary_check"]
        base["execution_lanes"] = list(sp["execution_lanes"])
        base["ownership_labels"] = list(sp["file_ownership_labels"])
        base["lane_mapping_note"] = sp["lane_mapping_note"]
    if legacy_config and "layer_boundary_check" not in raw:
        # Older rulesets always carried the layer-boundary rule (INV-02); keep it for them.
        base["layer_boundary_check"] = "import linting"

    profile_key = raw.get("profile_key", base["profile_key"])
    if profile_key in TOKEN_PROFILES:
        base["token_cfg"] = dict(TOKEN_PROFILES[profile_key])

    for k, v in raw.items():
        if k == "token_cfg":
            if not isinstance(v, dict):
                raise ConfigError("token_cfg must be an object")
            unknown_t = sorted(set(v) - set(base["token_cfg"]))
            if unknown_t:
                print(f"warning: unknown token_cfg keys ignored: {', '.join(unknown_t)}", file=sys.stderr)
            base["token_cfg"].update({tk: tv for tk, tv in v.items() if tk in base["token_cfg"]})
        elif k not in base:
            print(f"warning: unknown config key ignored: {k}", file=sys.stderr)
        elif v is not None:
            base[k] = v

    if isinstance(base.get("workspace_root"), str):
        base["workspace_root"] = base["workspace_root"].rstrip("/") or "/"
    if base.get("environment") in ("", None):
        base["environment"] = derive_environment(str(base.get("workspace_root", "")))
    validate_config(base)
    if base["model_preset"] in MODEL_PRESETS and any(base[k] != v for k, v in MODEL_PRESETS[base["model_preset"]].items()):
        base["model_preset"] = "custom"
    base["token_cfg"].pop("description", None)
    return base


def ask_int(prompt: str, default: int, minimum: int = 0) -> int:
    while True:
        raw = ask(prompt, str(default))
        if re.fullmatch(r"\d+", raw) and int(raw) >= minimum:
            return int(raw)
        print(f"  Please enter a whole number of at least {minimum}.")


def run_wizard() -> dict[str, Any]:
    header(
        1,
        "PROJECT IDENTITY & ENVIRONMENT",
        "Sets repository identity, visibility (public repos get free GitHub Actions),\n"
        "target OS matrix, and your local workspace conventions.",
    )
    project_name = ask("Project name", "my-project")
    repo_slug = ask("GitHub repository (owner/repo)", f"owner/{project_name}")
    is_public = ask_bool("Is the repository public (free GitHub Actions)?", True)
    owner_name = ask("Project owner name", "Project Owner")
    owner_gh = ask("Owner GitHub handle", "owner")
    timezone = ask("Owner timezone (IANA name)", "UTC")
    local_os_shell = ask("Owner local OS & shell", "unspecified")
    local_clone_path = ask("Local clone path", f"~/projects/{project_name}")
    workspace_root = ask(
        "Shared workspace root (claude.ai Project: /mnt/project-files; repo checkout: e.g. ./governance)",
        "/mnt/project-files",
    )

    print("\nStack presets:")
    for key, preset in STACK_PRESETS.items():
        print(f"  - {key}: lanes={preset['execution_lanes']}")
    stack_key = ask_choice(
        "Select stack preset",
        list(STACK_PRESETS.keys()),
        "python_cli_or_service",
    )
    preset = STACK_PRESETS[stack_key]
    fast_checks = ask("Fast local/PR checks", preset["fast_checks"])
    target_platforms = ask_list(
        "Target CI platforms for critical/release checks",
        ["ubuntu-latest", "macos-latest", "windows-latest"],
    )

    header(
        2,
        "MODEL ROUTING VS. TOKEN ECONOMY (DECOUPLED)",
        "Assigns intelligence tiers to roles independently from token-saving controls\n"
        "(concurrency, compression replacement threshold, watchdog interval, audit scope).",
    )
    print("\nModel presets (every slot can be changed afterwards):")
    for name, slots in MODEL_PRESETS.items():
        print(f"  {name:9s} " + "; ".join(f"{label}: {slots[key]}" for key, label, _ in MODEL_SLOTS))
    model_preset = ask_choice("Model preset", [*MODEL_PRESETS, "custom"], DEFAULT_MODEL_PRESET)
    preset_models = MODEL_PRESETS.get(model_preset, MODEL_PRESETS[DEFAULT_MODEL_PRESET])
    print("Type each model as your model picker shows it, or press Enter to keep the suggestion.")
    models = {key: ask(desc, preset_models[key]) for key, _, desc in MODEL_SLOTS}
    if model_preset != "custom" and models != preset_models:
        model_preset = "custom"
    escalate_after_round = 2
    if models["implementation_model"] != models["critical_model"]:
        escalate_after_round = ask_int(
            "Hand a routine PR to the critical-work model after this many review rounds with must-fix findings (0 = never)", 2
        )

    print("\nToken Economy Profiles:")
    for key, prof in TOKEN_PROFILES.items():
        print(
            f"  - {key}: {prof['description']}\n"
            f"      lanes={prof['max_concurrent_lanes']}, "
            f"replace_at_compressions={prof['replace_at_compressions']}, "
            f"watchdog={prof['watchdog_interval_minutes']}m, "
            f"audit={prof['batch_audit_mode']}"
        )
    profile_key = ask_choice(
        "Select token profile",
        list(TOKEN_PROFILES.keys()),
        "balanced",
    )
    token_cfg = dict(TOKEN_PROFILES[profile_key])
    coordinator_compact_every_batches = ask_int(
        "Claude Code only: the coordinator suggests a planned /compact at a pause and after every N batches (0 = never)", 1
    )
    cache_ttl_minutes = int(
        ask_choice(
            "Prompt cache lifetime in minutes (60 on a Pro/Max subscription, 5 on an API key or usage credits)",
            ["60", "5"],
            "60",
        )
    )

    if ask_bool("Customize individual token profile numbers?", False):
        token_cfg["max_concurrent_lanes"] = ask_int("Max concurrent implementation lanes", token_cfg["max_concurrent_lanes"], 1)
        token_cfg["replace_at_compressions"] = ask_int("Replace thread at N context compressions", token_cfg["replace_at_compressions"], 1)
        token_cfg["watchdog_interval_minutes"] = ask_int("Watchdog check interval (minutes)", token_cfg["watchdog_interval_minutes"], 1)
        token_cfg["watchdog_max_nudges"] = ask_int("Max watchdog nudges before replacing stalled thread", token_cfg["watchdog_max_nudges"], 0)
        token_cfg["non_critical_max_review_rounds"] = ask_int("Max review rounds for non-critical PRs", token_cfg["non_critical_max_review_rounds"], 1)

    header(
        3,
        "AUTONOMY & HUMAN ESCALATION GATES",
        "Defines how far the Coordinator may execute autonomously, what always stops\n"
        "for you (e.g. scope changes, Round-4 critical deadlocks), and your manual steps.",
    )
    autonomy_horizon = ask(
        "Autonomous execution horizon (e.g. 'until v1.0 is finished' or 'per milestone')",
        "until v1.0 is finished",
    )
    token_cfg["critical_max_review_rounds"] = ask_int(
        "Review round at which a critical PR stops for your sign-off (the hard stop itself cannot be turned off)",
        token_cfg["critical_max_review_rounds"],
        token_cfg["non_critical_max_review_rounds"],
    )
    owner_hand_steps = ask_list(
        "Physical / account hand steps reserved strictly for owner",
        [
            "listening or manual UX/accessibility pass",
            "local hardware benchmark run",
            "pushing release tags and package registry publishing",
            "repository settings, rulesets and milestone creation",
        ],
    )
    notify_triggers = ask_list(
        "Milestone/event triggers that notify owner in chat",
        ["first usable build ready for personal testing", "target autonomy milestone complete"],
    )

    header(
        4,
        "EXECUTION LANES & FILE OWNERSHIP",
        "Separates concurrent execution lanes from granular file-ownership labels.\n"
        "If you keep 'lane:infra', cross-cutting core changes require it and it acts as a single-thread lock.",
    )
    execution_lanes = ask_list("Execution lanes", preset["execution_lanes"])
    ownership_labels = ask_list("File-ownership labels", preset["file_ownership_labels"])
    lane_mapping_note = ask("Lane-to-label ownership mapping summary", preset["lane_mapping_note"])
    allow_parallel_release_branch = ask_bool(
        "Allow one release-branch thread to run in addition to the lane threads while release/* is open?",
        True,
    )
    dispatcher = ask_bool(
        "Add a dispatcher thread for per-PR operations (recommended: it is what keeps the long-lived coordinator from compressing)?",
        True,
    )

    header(
        5,
        "QUALITY GATES, LICENCES & DOMAIN INVARIANTS",
        "Configures mandatory engineering gates (tests-first, licence gate, network isolation)\n"
        "and project-specific hard rules that no PR may violate.",
    )
    no_telemetry = ask_bool("Enforce zero telemetry / local-only network rule?", True)
    banned_licences = ask_list(
        "Banned dependency/content licences",
        ["AGPL", "SSPL", "non-commercial", "unclear"],
    )
    custom_invariants: list[str] = []
    print("Add project-specific hard invariants (leave empty to finish):")
    while True:
        inv = ask("  Hard invariant rule (or Enter to skip)", "")
        if not inv:
            break
        custom_invariants.append(inv)

    acceptance_contracts = ask_bool(
        "Require an owner-approved acceptance contract (researched, sourced criteria) per milestone?",
        True,
    )

    return normalize_config({
        "project_name": project_name,
        "repo_slug": repo_slug,
        "is_public": is_public,
        "owner_name": owner_name,
        "owner_gh": owner_gh,
        "timezone": timezone,
        "local_os_shell": local_os_shell,
        "local_clone_path": local_clone_path,
        "workspace_root": workspace_root,
        "stack_key": stack_key,
        "fast_checks": fast_checks,
        "target_platforms": target_platforms,
        "model_preset": model_preset,
        **models,
        "escalate_after_round": escalate_after_round,
        "profile_key": profile_key,
        "cache_ttl_minutes": cache_ttl_minutes,
        "coordinator_compact_every_batches": coordinator_compact_every_batches,
        "token_cfg": token_cfg,
        "autonomy_horizon": autonomy_horizon,
        "owner_hand_steps": owner_hand_steps,
        "notify_triggers": notify_triggers,
        "execution_lanes": execution_lanes,
        "ownership_labels": ownership_labels,
        "lane_mapping_note": lane_mapping_note,
        "allow_parallel_release_branch": allow_parallel_release_branch,
        "no_telemetry": no_telemetry,
        "banned_licences": banned_licences,
        "custom_invariants": custom_invariants,
        "acceptance_contracts": acceptance_contracts,
        "dispatcher": dispatcher,
        "active_milestones": ["v0.1"],
    })


CHECK_SUFFIX = re.compile(r"\s*\[check:\s*(.*?)\s*\]\s*$")


def split_check(text: str) -> tuple[str, str]:
    """'Rule text [check: tests/x.py]' -> ('Rule text', 'tests/x.py'); no suffix -> (text, '')."""
    m = CHECK_SUFFIX.search(text)
    if not m:
        return text.strip(), ""
    return text[: m.start()].strip(), m.group(1).strip().rstrip(".")


def enforced_by(check: str) -> str:
    """The sentence that says what enforces an invariant. Rule prose alone is the weakest form."""
    check = one_line(check).rstrip(".")
    return " Enforced by: " + (check if check and check.lower() not in ("none", "review", "review only") else "review only") + "."


def with_period(text: str) -> str:
    text = one_line(text)
    return text if text.endswith((".", "!", "?")) else text + "."


def today_iso() -> str:
    """Generation date. GOVERNANCE_TODAY overrides it so tests are reproducible."""
    return os.environ.get("GOVERNANCE_TODAY") or datetime.date.today().isoformat()


def effective_escalation(cfg: dict[str, Any]) -> int:
    """Round after which REV-04 escalates; 0 when there is no escalation rule."""
    esc = int(cfg.get("escalate_after_round", 0))
    # Escalation cannot wait longer than routine PRs are allowed to stay in review.
    esc = min(esc, int(cfg["token_cfg"]["non_critical_max_review_rounds"]))
    return esc if esc > 0 and cfg["implementation_model"] != cfg["critical_model"] else 0


def render_rules_yaml(cfg: dict[str, Any], today: str | None = None) -> str:
    t = cfg["token_cfg"]
    today = today or today_iso()
    ws = cfg["workspace_root"]
    labels = cfg["ownership_labels"]
    in_repo = cfg["environment"] == "claude_code"
    contracts = bool(cfg["acceptance_contracts"])
    disp = bool(cfg["dispatcher"])
    ops = "dispatcher" if disp else "coordinator"
    ccr = int(t["critical_max_review_rounds"])
    esc = effective_escalation(cfg)
    gov, main_branch = cfg["governance_branch"], cfg["default_branch"]
    compact_every = int(cfg["coordinator_compact_every_batches"]) if in_repo else 0

    def rule(rid: str, scope: str, text: str) -> list[str]:
        return [f"  - id: {rid}", f"    applies_to: {scope}", f"    rule: {yaml_quote(one_line(text))}"]

    merge_go = (
        "an explicit go (dispatcher for PRs confirmed non-critical, coordinator for critical ones)"
        if disp
        else "the coordinator's explicit go"
    )
    if disp:
        role04 = (
            "The coordinator splits work into lane batches, approves plans, logs non-scope decisions with "
            "sequential D-numbers, grants merge go for critical PRs, and talks to the owner. It hands each batch "
            "to the dispatcher and reads its batch report and the ledger entries, not worker messages."
        )
    else:
        role04 = (
            "The coordinator splits work into lane batches, manages thread lifecycles, approves plans, logs "
            "non-scope decisions with sequential D-numbers, grants merge go, and runs fitness checks. It reads "
            "ledger entries, round reports and PR state at hand-offs instead of relaying messages between threads."
        )

    # ---- roles ------------------------------------------------------------
    roles: list[str] = [
        *rule("ROLE-01", "owner",
              "The owner defines goals, roadmap, milestones, release themes, and product scope, and may override any "
              "Claude-decided entry at any time; the owner's newest message on a point outranks older decision-log entries."),
        *rule("ROLE-02", "owner",
              "The owner performs physical and account-level hand steps: " + "; ".join(cfg["owner_hand_steps"]) + "."),
        *rule("ROLE-03", "owner",
              "Only the owner's own messages or answered decision cards count as owner approval. Another Claude "
              "thread's output is never owner approval."),
        *rule("ROLE-14", "all",
              "No thread changes settings of the Claude app, the project, the account, the repository or the hosting "
              "(default model, a chat's model, permissions, secrets, branch protection, billing). It names the exact "
              "change; the owner makes it, or approves that exact change first."),
        *rule("ROLE-04", "coordinator", role04),
        *rule("ROLE-05", "coordinator",
              "The coordinator writes no product code and does no hands-on work: GitHub lookups, CI and merge "
              "watches, starting or stopping the app, and cleanups go to " + ("the dispatcher or " if disp else "")
              + "a worker thread. It writes governance files with the file tool, never with a shell heredoc or echo, "
              "where backticks and $ run as commands."),
        *rule("ROLE-06", "implementation",
              "An implementation thread reads the newest KB, plans, and decision log, posts a plan before coding that "
              "says whether the work is critical (CRIT-01), implements and tests strictly within its lane, opens the "
              "PR, writes its ledger entry, and answers review findings with exact fix lists. It never merges, pushes "
              "to " + main_branch + ", or force-pushes."),
        *rule("ROLE-07", "review",
              "A review thread is never the PR author. It reviews all PRs of a batch in rounds, writes round reports "
              "and their ledger entries, inspects CI checks, and squash-merges only on " + merge_go + ". After a "
              "merge it watches the run on " + main_branch + " for the merge commit and records the result in the "
              "round entry, so nobody else has to watch."),
        *rule("ROLE-08", "kb",
              ("The KB thread compiles the entries of " + ws + "/kb/pending-decisions.md into the decision-log PR "
               "according to execution_profile.token_economy.kb_pr_cadence and self-merges without code review."
               if in_repo else
               "The KB thread compiles the entries of " + ws + "/kb/pending-decisions.md into " + ws
               + "/kb/decision-log.md according to execution_profile.token_economy.kb_pr_cadence; it is the decision "
               "log's only writer and writes it without code review.")
              + " It never edits the pending file."),
        *rule("ROLE-09", "audit",
              "When triggered by execution_profile.token_economy.batch_audit_mode, an audit thread inspects the merged "
              "batch diff for cross-PR inconsistencies, contract touches, and workarounds or patterns the project "
              "has moved away from that appear in more than one PR (later threads copy what they find), and writes its findings to "
              + ws + "/ledger/audits/."),
        *rule("ROLE-15", "audit",
              "An audit starts from the output of " + ws + "/tools/ledger_tool.py flags, not from thread chats. Each flag "
              "and each finding gets one verdict: check (a lint rule, test or CI check would have caught it; name it), "
              "rule (a rule is wrong or missing; it goes to the owner), split (the plan or PR was too large), owner (needs "
              "the owner's decision), or leave (the cost is the work itself; say why). The audit proposes and builds nothing."),
        *(rule("ROLE-16", "audit",
               "A seam audit is a fresh, read-only session, started when ledger_tool.py stats says it is due or a "
               "milestone closes. Its brief is the output of " + ws + "/tools/seam_audit.py brief: each group in "
               "project_profile.seam_groups read together, four checks only (error and status mapping, state read "
               "before a mutator, duplicated helpers, comments citing a changed invariant), at most ten findings in "
               "ledger/audits/seam-<date>.md, no edits.")
          if cfg["seam_groups"] else []),
    ]
    if contracts:
        roles += rule("ROLE-10", "specify",
                      "A specify thread turns the owner's feature idea or plan change into an acceptance-contract "
                      "version, work packages and a roadmap update, following " + ws + "/tools/acceptance-contracts.md. "
                      "It shows the owner every criterion with its verify step, records approval only on the owner's "
                      "own message that quotes the contract hash, creates issues only on the owner's yes, and never "
                      "touches rules, state, code or D-numbers.")
    roles += rule("ROLE-12", "assist",
                  "An assist thread walks the owner through one hand step (account, hosting, key or repository "
                  "settings) one step at a time and checks the result where it can. It never has a secret pasted into "
                  "chat: secrets go straight into the service that stores them. When the step is done it tells the "
                  "coordinator the step's title and ends.")
    if cfg["advisor"]:
        roles += rule("ROLE-18", "coordinator,advisor",
                      "The advisor is a fresh, read-only session on the advisor model. The coordinator asks it only about "
                      "a decision it would otherwise put to the owner, or a real open choice in a critical plan; the brief "
                      "names the question, the options and the evidence. The advisor answers with one recommendation and "
                      "its reasons, and decides nothing. The coordinator records the answer in " + ws
                      + "/kb/pending-decisions.md.")
    roles += rule("ROLE-17", "coordinator",
              "Act on few events: a plan or contract to approve, a verdict or gate that needs you (critical, escalated, "
              "refused), a blocked or question hand-back, " + ("the batch report" if disp else "the end of a batch")
              + ", and the owner's messages. Everything else ends in the thread it belongs to. Report one line per "
              "event, PRs by number only, never their titles, and no list of what is pending: ledger_tool.py status "
              "prints that when asked.")
    roles += rule("ROLE-13", "coordinator",
                  "Answer the owner's short questions directly. Keep open hand steps in owner_open_steps in " + ws +
                  "/project-state.yaml and remove one when its assist thread reports it done; asked what is open, list "
                  "them by title only. When the owner wants to do one, or an answer needs more than a few lines of "
                  "instructions, start an assist thread for it instead of walking through it here.")
    if disp:
        roles += rule("ROLE-11", "dispatcher",
                      "The dispatcher runs one batch at a time for the coordinator: it starts, fitness-checks, watches "
                      "and replaces worker threads, keeps " + ws + "/plans/batch-<NNN>.md current, reads ledger "
                      "entries but writes none, and grants merge go only for PRs the review thread confirmed "
                      "non-critical, with green CI and no open must-fix finding. It never approves plans or touches "
                      "scope, and reports to the coordinator once per batch or on escalation.")

    # ---- lanes ------------------------------------------------------------
    lane03 = "A PR modifies files within its mapped file-ownership labels only."
    if "lane:infra" in labels:
        lane03 += " Touching shared core files requires lane:infra and acts as a single-threaded lock across lanes."
    else:
        lane03 += " Shared files that no label owns are changed by one PR at a time, with coordinator plan approval."
    if "lane:docs" in labels:
        lane03 += " Docs may be updated by any lane."
    lanes = [
        *rule("LANE-01", "coordinator",
              "PRs are batched by execution lane rather than single issues; small follow-ups fold into the lane's next PR."),
        *rule("LANE-02", ops,
              "Concurrent implementation threads must not exceed execution_profile.token_economy.max_concurrent_lanes "
              "(at most one active thread per execution lane)."),
        *rule("LANE-03", "implementation", lane03),
    ]
    if cfg["allow_parallel_release_branch"]:
        lanes += rule("LANE-04", "coordinator",
                      "Exception: while a release/X.Y branch is open, one dedicated release thread may run in addition "
                      "to the lane threads.")

    # ---- threads ----------------------------------------------------------
    threads = [
        *rule("THR-01", ops,
              "Every new thread reads its extract " + ws + "/rules/<role>.yaml and then the KB, plans and decision-log "
              "entries its task needs, before acting. Before a thread gets a second batch it passes a fitness check: "
              "it states its current plan and open items from memory, and the answer is compared with its files; a "
              "mismatch means replacement."),
        *rule("THR-02", "all",
              "A worker thread (including the KB thread) is replaced once it has handled "
              "execution_profile.token_economy.replace_after_prs PRs, counted from its ledger entries, or noticed "
              "replace_at_compressions compressions, whichever comes first. It finishes its current atomic step "
              "(review round, fix commit, or KB PR) and is replaced at the next hand-off, never mid-step. The "
              "coordinator is never replaced."),
        *rule("THR-03", ops,
              "Watchdog: each time you are active, take the time from a tool, never from memory, and for every thread "
              "that owes output compare its newest commit or file change with watchdog_interval_minutes. Only when "
              "nothing moved: within cache_ttl_minutes nudge it (at most watchdog_max_nudges), after that replace it "
              "from its files or escalate to the " + ("coordinator" if disp else "owner") + ". A check while nobody is "
              "active needs a scheduled task the owner sets up."),
        *rule("THR-04", "all",
              "Threads write plans and round reports under " + ws + "/plans/ and post one line per hand-off in chat "
              "(what was written, where). Fix lists travel through round reports, not through the coordinator. Every "
              "file has one writer: a thread writes its own plan, reports and ledger entries and no other thread's; "
              "project-state.yaml is the coordinator's."),
    ]
    if disp:
        threads += rule("THR-05", "dispatcher",
                        "The dispatcher keeps its whole working state in " + ws + "/plans/batch-<NNN>.md, so it is "
                        "replaced at its first compression or after one batch, at the next hand-off.")
    threads += rule("THR-06", "coordinator",
                    "The coordinator lives for the whole project and keeps its context small: it reads summaries, "
                    "ledger entries and state files, never diffs, logs, research or whole contracts, and hands lookups "
                    "to a running thread. At each hand-off it writes state to " + ws + "/project-state.yaml and new "
                    "decisions to " + ws + "/kb/pending-decisions.md, which only it writes, and re-reads them and "
                    "its rules after any compression.")
    threads += rule("THR-10", "coordinator,dispatcher" if disp else "coordinator",
                    "Starting a thread: if you have a tool that opens a thread or session, use it and set the model "
                    "from execution_profile.model_routing there. If you have none, or it cannot set the model, write a "
                    "starter block (role, model, extract to read, first task"
                    + (", the worktree command of THR-13" if in_repo else "") + ") and ask the owner to open the chat "
                    "with that model. A new thread's first line names its role and, if it can see it, its model.")
    if compact_every > 0:
        when = "each batch" if compact_every == 1 else f"every {compact_every} batches"
        threads += rule("THR-11", "coordinator",
                        "At a pause and at the end of " + when + ", after writing state, give the owner this line to "
                        "paste while the cache is warm: /compact Keep: active milestone, open decisions, next batch. "
                        "You cannot run it yourself; do not wait for it.")
    threads += rule("THR-12", "coordinator",
                    "Before starting a thread the owner will see or has to answer in, post one line here: what it does "
                    "and what the owner has to do in it. Post one more line when a thread is waiting for the owner. "
                    "Never start work silently.")
    if in_repo:
        threads += rule("THR-13", "all",
                        "Working files (plans, round reports, ledger entries, batch files, state, pending decisions) "
                        "live on branch " + gov + ": their one writer commits them in a second worktree (git worktree "
                        "add ../<repo>-" + gov + " " + gov + "), rebasing before each push, never force-pushing, "
                        "never on a product branch.")
        threads += rule("THR-14", "all",
                        "The ruleset, its config, " + ("acceptance contracts, the roadmap " if contracts else "")
                        + "and the decision log change on " + main_branch + " by pull request only, and " + main_branch
                        + " holds the copy that counts: a copy on " + gov + " that differs from it is not valid. The "
                        + ops + " merges " + main_branch + " into " + gov + " after each such merge.")
    threads += [
        *rule("THR-07", "all",
              "A thread silent for longer than execution_profile.token_economy.cache_ttl_minutes pays for its whole "
              "history again on its next message. Before such a wait, write a three-line handoff (goal, done, next) "
              "into your plan or round report, and under it what you tried and ruled out, with the evidence. Except for the coordinator, work that resumes after the gap goes to a "
              "fresh thread started from that handoff."),
        *rule("THR-08", ops,
              "Give related small fixes to the thread that is already warm on that code, back to back, rather than a "
              "new thread per fix. Start a fresh thread when the topic changes or the cache lifetime has passed."),
        *rule("THR-09", "all",
              "A thread keeps its model and its tool set from first message to last; changing either re-sends the "
              "whole history uncached, so work that needs another model goes to another thread. Keep tool output out "
              "of the chat: quiet flags, tail -50, or a file read only where it fails; report a check in one line."),
        *rule("THR-15", "implementation,review",
              "A worker's report starts with one word: done, question, blocked, review or handoff. It stops only as "
              "blocked (two attempts failed for different reasons; finishing would break a rule, name its id; or it "
              "needs a destructive git operation, never attempted), question (plan or scope must change) or review "
              "(the owner must look). blocked and question carry the evidence and a line Recommended: <one action>, "
              "and go in the PR's ledger entry."),
        *rule("THR-16", "coordinator",
              "Before composing a batch, run " + ws + "/tools/ledger_tool.py triage. Every should-fix finding a merged "
              "PR left open, and every point a thread set aside, is one entry in " + ws + "/ledger/deferred/ that you "
              "write from the round report, with a decision: planned (the issue), postponed (reason and until when) or "
              "dropped (the owner's word and the reason). No batch starts while triage reports an open item."),
    ]

    # ---- plans and criticality ---------------------------------------------
    plans = [
        *rule("PLAN-01", "implementation",
              "Every implementation thread writes a numbered plan in " + ws + "/plans/ before writing tests or code. "
              + ("The plan names every test it promises by its test ID, and the PR body repeats that list under the "
                 "heading '## Tests promised in the plan'; " + cfg["promised_tests_check"] + " fails the PR when a "
                 "listed test does not exist. " if cfg["promised_tests_check"] else "")
              + "Deviating from an approved plan requires a new coordinator D-number."),
        *rule("PLAN-02", "coordinator",
              "Critical work always waits for explicit coordinator plan approval; non-critical work may proceed "
              "immediately when confidence is high."),
    ]
    if contracts:
        plans += [
            *rule("PLAN-03", "coordinator",
                  "Work on a milestone starts only from an owner-approved acceptance contract written by a specify "
                  "thread. Pick one up only on the owner's message naming its hash: run contract_tool.py pickup with "
                  "that hash, record the printed line in approved_contracts in " + ws + "/project-state.yaml and in "
                  "the pending decisions, and mirror the roadmap's active milestones there. Nobody edits an approved "
                  "contract; a change is a new version from specify."),
            *rule("PLAN-04", "implementation",
                  "One work package is one plan and one PR. Plans cite the acceptance-contract criterion ids they "
                  "cover (read them with contract_tool.py brief); the PR body lists each covered criterion with the "
                  "command run and its result, or the evidence file for a runtime step. A /goal loop on criteria stops at "
                  "execution_profile.token_economy.goal_turn_cap turns."),
            *rule("PLAN-05", "coordinator",
                  "A milestone closes only when every must criterion and the core probe pass and every should "
                  "criterion passes or has a deferred issue; log it as a D-entry. When the roadmap drops a milestone "
                  "or a new contract version removes a criterion, start no new work on it, let open PRs finish their "
                  "round, and ask the owner per open PR: merge or close."),
        ]
    plans += [
        *rule("CRIT-01", "all",
              "A change is critical if it touches " + ", ".join(cfg["critical_areas"]) + ", or carries risk:high."),
        *rule("CRIT-02", "all",
              "Critical work requires coordinator plan approval, implementation and review on the critical_work "
              "model, exact fix lists, issues for all deferred items, and full multi-platform CI on the final round."),
        *rule("CRIT-03", "review",
              "In round 1, decide from the diff whether the PR is critical (CRIT-01), whatever the plan says, and "
              "record critical: yes or no in the round report and its ledger entry; in doubt it is critical. A PR "
              "found critical without an approved plan stops for the coordinator."
              + (" A risk:high label set by CI from project_profile.critical_paths is never removed by a thread."
                 if cfg["critical_paths"] else "")),
    ]

    # ---- PRs and reviews ---------------------------------------------------
    must_fix_route = "REV-04 applies" if esc else "they stop the PR for the coordinator"
    reviews = [
        *rule("PR-01", "implementation",
              "PR title format: '<area>: <outcome> (#N)'. Closing keywords (Closes #N) belong in the PR body only, "
              "never in branch commit messages."),
        *rule("PR-02", "implementation",
              "Run local fast checks before opening a PR. A PR enters review only after fast CI is green; critical PRs "
              "also require a green full-matrix dispatch first."),
        *rule("PR-03", "implementation",
              "Freeze the branch during an active review round except for requested fix commits (one fix commit per "
              "round). Never force-push."),
        *rule("PR-04", "implementation,review",
              "Where the repository runs pr_checks.py: a file that has to break one of its checks is listed in "
              "pr-check-exemptions.json as sanctioned (permanent, with the reason) or debt (with the reason and "
              "the issue that removes it), in a PR the owner reviews. Never widen a path glob, drop a label or "
              "skip the check to get a PR through; an exemption whose issue is closed is removed."),
        *rule("PR-05", "implementation,review",
              "A comment says why the code is as it is, never what it does, what changed or who asked; add no other. "
              "The reviewer treats a narrating or change-history comment as a finding (kind narrating-comment). "
              "Create no file the rules, the approved plan or the owner did not name: no summary, notes or report "
              "files, and new markdown only under project_profile.doc_paths. Reports go in the PR body or the "
              "ledger."),
        *rule("PR-06", "review",
              "A PR does the task at the size it was asked: a feature, option, abstraction or test the plan does not "
              "name is a finding. A new dependency, tool or service needs three lines in the PR body: what it does, "
              "what the project already has for that, and the difference that justifies it."),
        *rule("REV-01", "review",
              "Non-critical PRs run up to execution_profile.token_economy.non_critical_max_review_rounds rounds; "
              "should-fix leftovers are then deferred to issues, must-fix findings never (" + must_fix_route + "). "
              f"Critical PRs run up to round {ccr}, then hit a hard stop requiring owner sign-off."),
        *rule("REV-02", "review",
              "Round reports go to " + ws + "/plans/review-pr<N>-round<K>.md with head SHA, verdict, verified checks, "
              "and numbered findings (B/M must-fix, S should-fix, N note); each round also gets a ledger entry (" + ws
              + "/ledger/README.md). Every finding must be answered as fixed (with test proof), deferred (with issue "
              "link), or declined (with reason)."),
    ]
    if contracts:
        reviews += rule("REV-03", "review",
                        "Read the diff and the acceptance contract before the plan and PR description. Confirm each "
                        "criterion the PR claims from CI output, by re-running its verify step, or from the evidence "
                        "of a runtime step; a claimed criterion without passing proof is a must-fix finding.")
    reviews += rule("REV-05", "review",
                    "A finding is fixed at its root. A code comment, a document or a new rule that explains a "
                    "workaround is not a fix and leaves the finding open. Name each finding's kind in the round's "
                    "ledger entry; a kind already seen in an earlier PR is fixed together with a check that stops it "
                    "from coming back (lint rule, type, test or CI check) or a design change that removes it.")
    reviews += rule("REV-06", "implementation,review",
                    "A retry, a timeout or deadline, a cache, or a raised limit added to make a failure go away is a "
                    "workaround until the PR names the cause it removes; the reviewer treats it as a finding (REV-05). "
                    "A PR that claims to remove a finding kind for good names it in fixes_kinds of its ledger entry. If "
                    "the kind comes back, ledger_tool.py stats marks the fix regressed and the next fix goes one step "
                    "up (META-03).")
    if esc:
        after = int(cfg["rounds_after_escalation"])
        reviews += rule("REV-04", ops,
                        f"A non-critical PR that still has must-fix findings after review round {esc} goes to a fresh "
                        "implementation thread on the critical_work model, started from the round reports; the "
                        "previous thread stops. This comes before the round cap in REV-01. The new thread gets "
                        f"{after} more round{'s' if after != 1 else ''}; must-fix findings still open after that stop "
                        "the PR for the coordinator. A running thread never changes its model (THR-09).")
    reviews += rule("MRG-01", "review",
                    "Squash-merge only on " + merge_go + ", pinned to the reviewed head SHA, with no open B/M finding "
                    "in the latest round report (ledger_tool.py gate <N> passes) and required CI green (and all "
                    "target_platforms green for critical PRs). If behind " + main_branch + ", update via merge commit "
                    "(never force-push), re-verify diff and CI, and merge on the new SHA.")
    reviews += rule("MRG-02", "coordinator,review",
                    "Only the owner can let a PR merge that the gate stops, and only once: the coordinator records the "
                    "owner's reason and the head SHA it is for in " + ws + "/ledger/overrides/pr-<N>.yaml. The override "
                    "holds for that head only; a changed PR needs a new decision. It is never turned into a setting or "
                    "a standing exception. The same reason a second time means the rule itself changes (META-01).")

    # ---- invariants ---------------------------------------------------------
    inv: list[str] = rule("INV-01", "implementation",
                          "Licence gate: every new dependency, asset, model, or sample names its licence in the PR "
                          "body and licence manifest. Banned licences: " + ", ".join(cfg["banned_licences"]) + "."
                          + enforced_by(cfg["licence_check"]))
    inv_idx = 2
    if cfg["layer_boundary_check"].strip():
        inv += rule(f"INV-{inv_idx:02d}", "implementation",
                    "Architectural layer boundaries are enforced automatically (" + cfg["layer_boundary_check"].strip()
                    + "); fix the design, never bypass the contract.")
        inv_idx += 1
    if cfg["no_telemetry"]:
        inv += rule(f"INV-{inv_idx:02d}", "implementation",
                    "Zero telemetry, analytics, crash uploads, or unrequested network calls."
                    + (" Local web UIs bind strictly to 127.0.0.1." if cfg["local_ui_loopback_only"] else "")
                    + enforced_by(cfg["telemetry_check"]))
        inv_idx += 1
    for custom_rule in cfg["custom_invariants"]:
        custom_text, custom_check = split_check(custom_rule)
        inv += rule(f"INV-{inv_idx:02d}", "implementation", with_period(custom_text) + enforced_by(custom_check))
        inv_idx += 1
    inv += rule("PREF-01", "all",
                " ".join(["Report times to " + cfg["owner_name"] + " in " + cfg["timezone"] + ".", *cfg["owner_prefs"]]))

    profile = [
        "project_profile:",
        f"  stack_preset: {cfg['stack_key']}",
        f"  environment: {cfg['environment']}",
        f"  target_platforms: {yaml_list(cfg['target_platforms'])}",
        f"  fast_checks: {yaml_quote(cfg['fast_checks'])}",
        f"  local_environment: {yaml_quote(cfg['local_os_shell'])}",
        f"  local_clone_path: {yaml_quote(cfg['local_clone_path'])}",
        f"  execution_lanes: {yaml_list(cfg['execution_lanes'])}",
        f"  file_ownership_labels: {yaml_list(labels)}",
        f"  lane_mapping_note: {yaml_quote(cfg['lane_mapping_note'])}",
        *([f"  critical_paths: {yaml_list(cfg['critical_paths'])}"] if cfg["critical_paths"] else []),
        *([f"  label_paths: {yaml_list(cfg['label_paths'])}"] if cfg["label_paths"] else []),
        *([f"  seam_groups: {yaml_list(cfg['seam_groups'])}", f"  seam_audit_every_prs: {int(cfg['seam_audit_every_prs'])}"]
          if cfg["seam_groups"] else []),
        f"  doc_paths: {yaml_list(cfg['doc_paths'])}",
        *([f"  governance_paths: {yaml_list(cfg['governance_paths'])}"] if cfg["governance_paths"] else []),
        *([f"  promised_tests_check: {yaml_quote(cfg['promised_tests_check'])}"] if cfg["promised_tests_check"] else []),
        f"  workspace_root: {yaml_quote(ws)}",
        f"  state_file: {yaml_quote(ws + '/project-state.yaml')}",
        f"  plans_dir: {yaml_quote(ws + '/plans')}",
        f"  rules_by_role: {yaml_quote(ws + '/rules/<role>.yaml')}",
        *([f"  roadmap_file: {yaml_quote(ws + '/roadmap.yaml')}"] if contracts else []),
        *([f"  default_branch: {yaml_quote(main_branch)}", f"  governance_branch: {yaml_quote(gov)}"] if in_repo else []),
        "",
        "execution_profile:",
        "  model_routing:",
        *[f"    {label}: {yaml_quote(cfg[key])}" for key, label, _ in MODEL_SLOTS],
        *([f"    advisor: {yaml_quote(cfg['advisor_model'] or cfg['critical_model'])}"] if cfg["advisor"] else []),
        "  token_economy:",
        f"    profile_name: {cfg['profile_key']}",
        f"    max_concurrent_lanes: {t['max_concurrent_lanes']}",
        f"    replace_after_prs: {t['replace_after_prs']}",
        f"    replace_at_compressions: {t['replace_at_compressions']}",
        f"    watchdog_interval_minutes: {t['watchdog_interval_minutes']}",
        f"    watchdog_max_nudges: {t['watchdog_max_nudges']}",
        f"    non_critical_max_review_rounds: {t['non_critical_max_review_rounds']}",
        f"    critical_max_review_rounds: {ccr}",
        *([f"    rounds_after_escalation: {cfg['rounds_after_escalation']}"] if esc else []),
        f"    batch_audit_mode: {yaml_quote(t['batch_audit_mode'])}",
        f"    kb_pr_cadence: {yaml_quote(t['kb_pr_cadence'])}",
        f"    reporting_verbosity: {yaml_quote(t['reporting_verbosity'])}",
        f"    offload_heavy_checks_to_ci: {str(t['offload_heavy_checks_to_ci']).lower()}",
        f"    goal_turn_cap: {t['goal_turn_cap']}",
        f"    cache_ttl_minutes: {cfg['cache_ttl_minutes']}",
        *([f"    coordinator_compact_every_batches: {compact_every}"] if in_repo else []),
        "",
    ]

    lines: list[str] = [
        f"# {one_line(cfg['project_name'])}: reusable project rules for multi-thread Claude execution",
        "# Generated by project-governance-init. Do not edit by hand: change governance-config.json and regenerate.",
        "#",
        "# SCHEMA",
        "#   version:           semver of this ruleset; the minor number goes up whenever a regeneration changes it",
        "#   date:              date of the last generation (YYYY-MM-DD)",
        "#   authority:         precedence order when sources conflict (first wins)",
        "#   project_profile:   project-specific stack, paths, lanes, and CI checks",
        "#   execution_profile: decoupled model routing and token-economy settings",
        "#   <section>:         active rules with id, applies_to, rule",
        "",
        f"version: {cfg['ruleset_version']}",
        f"date: {today}",
        f"project: {yaml_quote(cfg['project_name'])}",
        f"repository: {yaml_quote(cfg['repo_slug'])}",
        f"public_repo: {str(cfg['is_public']).lower()}",
        f"owner: {yaml_quote(cfg['owner_name'] + ' (GitHub ' + cfg['owner_gh'] + ')')}",
        f"time_zone_owner: {yaml_quote(cfg['timezone'])}",
        "",
        "authority:",
        "  - owner_messages         # the owner's newest message on a point; one that contradicts this ruleset"
        + (" or an approved contract" if contracts else "") + " starts a change through the governance skill, it is not applied silently",
        "  - this_ruleset           # and the project instructions generated from it",
        *(["  - approved_acceptance_contracts"] if contracts else []),
        "  - kb_decision_log        # newest D-entry first",
        "  - pending_kb_batch       # kb/pending-decisions.md: decided, not yet compiled into the decision log",
        "  - project_memory",
        "  - repo_claude_md",
        "",
        *profile,
        "meta:",
        *rule("META-01", "all",
              "Modifying this ruleset file is critical and requires explicit owner approval; threads never alter "
              "governance rules unilaterally."),
        *rule("META-02", "coordinator",
              "Volatile runtime state (active milestones, pause flags, notification triggers, autonomy message IDs) "
              "lives in project-state.yaml, never hardcoded into static rules."),
        *rule("META-03", "all",
              "A correction that has to be given a second time becomes a check in the product repository or a design "
              "change, one step up this order of strength: a design that makes the mistake impossible; a type; a lint "
              "rule, test or CI check; a loud failure at runtime. Prose is the last resort: a new rule here needs the "
              "owner (META-01), and comments or notes do not bind the next thread."),
        "",
        "roles:",
        *roles,
        "",
        "autonomy:",
        *rule("AUTO-01", "coordinator",
              "Coordinator reviews, approves merges, and makes technical/process decisions autonomously "
              + cfg["autonomy_horizon"] + ", keeping all testing and review gates intact."),
        *rule("AUTO-02", "coordinator",
              "Any decision altering product scope, external contracts, or roadmap waits for explicit owner approval."),
        *rule("AUTO-03", "coordinator",
              "Work beyond the active milestone may start in unblocked lanes when current milestone work is waiting "
              "or complete."),
        "",
        "lanes:",
        *lanes,
        "",
        "threads_and_watchdog:",
        *threads,
        "",
        "plans_and_criticality:",
        *plans,
        "",
        "pull_requests_and_reviews:",
        *reviews,
        "",
        "testing_and_ci:",
        *rule("TST-01", "implementation",
              "Tests come first: failing test for bugs, characterisation test before refactoring, and regression test "
              "before behaviour changes. Every safety mechanism must have a test that fails without it."),
        *rule("TST-02", "implementation",
              "Never weaken, skip, or delete a failing test to turn CI green. Flaky tests without code cause are "
              "quarantined same-day with a linked GitHub issue and must be fixed before release."),
        *rule("VER-02", "review,audit",
              "A check counts only after it has failed once on a case known to be wrong; until then green proves "
              "nothing (pr_checks.py --self-test does this for the pull-request checks). A result that looks too good "
              "is a measurement error until shown otherwise. A summary from another thread, a tool or an older note is "
              "a claim: check it against the file, the diff or the output before a decision rests on it."),
        *(rule("VER-01", "implementation",
               "Behaviour a user can see is proven by running the product the way a user would, following " + ws
               + "/kb/verification.md: the real path, no test-only shortcut or internal setter, with the evidence "
               "file kept and named in the PR body. A PR that adds or changes such a feature updates " + ws
               + "/kb/features/ in the same change. A journey that fails is reported, never weakened to pass.")
          if cfg["runtime_verification"] else []),
        *rule("CI-01", "all",
              "Fast checks run automatically on PRs; full target_platforms matrix runs on " + main_branch
              + ", release/**, and via explicit full-CI dispatch/label on critical PRs (including critical PRs into "
              "release branches). Offload heavy suites to CI actions whenever possible."),
        "",
        "github_kb_and_release:",
        *rule("GH-01", "all",
              "Every deferred item or flaky test gets a GitHub issue with milestone, lane label, and risk label the "
              "same day." + (" Where GraphQL is blocked, use REST API endpoints exclusively." if cfg["github_rest_only"] else "")),
        *rule("KB-01", "all",
              "All decisions (owner and Claude) are logged sequentially in the KB decision log. An entry that records "
              "an owner decision quotes the owner's message and its date; without the quote it ranks as a Claude "
              "decision. KB PRs reference code PRs without closing keywords."),
        *rule("REL-01", "all",
              "Cut release/X.Y from the release-ready " + main_branch + " merge commit. Release fixes land via PR on "
              "release/X.Y and port verbatim to " + main_branch + ". No quarantined tests may remain at tag time."),
        "",
        "hard_invariants_and_owner_prefs:",
        *inv,
        "",
    ]
    return "\n".join(lines)


_RULE_RE = re.compile(r"^  - id: (\S+)\n    applies_to: (\S+)\n    rule: (.*)$", re.MULTILINE)
EXTRACT_DIR = "rules"


def reading_lists(ws: str, contracts: bool) -> dict[str, tuple[list[str], list[str]]]:
    """Per role: (what to read when the thread starts, what to leave unread). Small context is the cheapest saving."""
    brief = [f"the contract brief for your work package: python3 {ws}/tools/contract_tool.py brief"] if contracts else []
    summary = [f"the contract summary: python3 {ws}/tools/contract_tool.py summary"] if contracts else []
    return {
        "coordinator": (
            [f"{ws}/project-state.yaml", f"{ws}/kb/pending-decisions.md", f"the output of python3 {ws}/tools/ledger_tool.py stats and triage"],
            ["diffs, logs and research", "whole plans and whole contracts (a summary is enough)",
             f"the whole decision log (search {ws}/kb/decision-log.md for the D-number you need)"]),
        "dispatcher": (
            [f"{ws}/plans/batch-<NNN>.md", f"{ws}/project-state.yaml"],
            ["diffs and product code", "plans of work that is not in the batch"]),
        "implementation": (
            ["the issue and your plan in " + ws + "/plans/", *brief, "the files your plan names, by range where they are long"],
            ["other lanes' plans and code", "other threads' round reports and the ledger history",
             f"older entries of {ws}/kb/decision-log.md (read the newest, search for a D-number you need)", "the full ruleset (this extract is enough)"]),
        "review": (
            ["the pull request's diff", "the plan it implements", *summary, "the previous round report for this pull request"],
            ["the implementation thread's chat", "other pull requests", "code outside the diff, unless a finding needs it"]),
        "kb": (
            [f"{ws}/kb/pending-decisions.md", f"the last entries of {ws}/kb/decision-log.md"],
            ["product code", "plans and round reports"]),
        "audit": (
            [f"the output of python3 {ws}/tools/ledger_tool.py flags", "the merged batch diff"],
            ["thread chats", "round reports, unless a flag names one"]),
        "specify": (
            [f"{ws}/roadmap.yaml", f"the contracts in {ws}/plans/", f"{ws}/tools/acceptance-contracts.md"],
            ["product code beyond what a criterion needs", "the ledger"]),
        "advisor": (
            ["the brief the coordinator gives you", "the files and decision-log entries the brief names"],
            ["thread chats", "diffs and code the brief does not name", "the ledger", "the full ruleset (this extract is enough)"]),
        "assist": (
            [f"the hand step named for you in {ws}/project-state.yaml"],
            ["everything else"]),
    }


def role_extracts(rules_text: str) -> dict[str, str]:
    """Per-role extracts of a generated ruleset: profile blocks plus the rules scoped to that role or to all."""
    header = "\n".join(l for l in rules_text.split("\nauthority:")[0].splitlines() if l and not l.startswith("#"))
    m = re.search(r"^project_profile:\n.*?(?=^meta:)", rules_text, re.MULTILINE | re.DOTALL)
    profile = m.group(0).rstrip() if m else ""
    found = _RULE_RE.findall(rules_text)
    roles = sorted({s for _, scope, _ in found for s in scope.split(",")} - {"all", "owner"})
    m = re.search(r'^  workspace_root: "?([^"\n]+)"?$', rules_text, re.MULTILINE)
    lists = reading_lists(m.group(1).strip() if m else ".", "specify" in roles)
    out: dict[str, str] = {}
    for role in roles:
        mine = [(rid, scope, body) for rid, scope, body in found if {role, "all"} & set(scope.split(","))]
        lines = [
            f"# Extract for {role} threads. Generated with claude-project-rules.yaml; do not edit.",
            "# It holds the rules scoped to this role or to all. If it and the full file ever differ, the full file wins.",
            f"extract_for: {role}",
            header,
            "",
            profile,
            "",
        ]
        if role in lists:
            first, skip = lists[role]
            lines += ["# Read only this when you start; ask a running thread or search for anything else.",
                      "start_reading:", *[f"  - {yaml_quote(x)}" for x in first],
                      "leave_unread:", *[f"  - {yaml_quote(x)}" for x in skip], ""]
        lines.append("rules:")
        for rid, scope, body in mine:
            lines += [f"  - id: {rid}", f"    applies_to: {scope}", f"    rule: {body}"]
        out[role] = "\n".join(lines) + "\n"
    return out


def render_state_yaml(cfg: dict[str, Any], today: str | None = None) -> str:
    triggers_yaml = "\n".join(f"  - {yaml_quote(one_line(t))}" for t in cfg["notify_triggers"]) or "  []"
    lines = [
        f"# {one_line(cfg['project_name'])}: volatile runtime state (separated from static rules)",
        "# One writer: the coordinator. Other threads read it and report changes to the coordinator (THR-04).",
        f"date: {today or today_iso()}",
        f"project: {yaml_quote(cfg['project_name'])}",
        "",
        "active_now:",
        f"  autonomy_horizon: {yaml_quote(cfg['autonomy_horizon'])}",
        "  paused: false",
        "  slow_down: false",
        "  thread_freeze: false",
        f"  active_milestones: {yaml_list(cfg['active_milestones'])}",
        "  owner_autonomy_message_ids: []",
        "  owner_open_steps: []   # hand steps waiting for the owner, titles only (ROLE-13)",
        "",
    ]
    if cfg["acceptance_contracts"]:
        lines += [
            "# One line per picked-up contract version, written by the coordinator (PLAN-03). contract_tool.py",
            "# compares a contract with its line here, so an approved contract cannot change unnoticed.",
            '# Format: "C-001 v1 D-012 hash 0123456789ab"',
            "approved_contracts: []",
            "closed_milestones: []   # \"v0.1 D-034\" when a milestone closes (PLAN-05)",
            "",
        ]
    lines += [
        "notifications_pending:" if cfg["notify_triggers"] else "notifications_pending: []",
        *([triggers_yaml] if cfg["notify_triggers"] else []),
        "",
        "control_commands_reference:",
        "  pause: '\"pause all threads\" / \"stop\"'",
        "  slow_down: '\"slow down\" (finish running batches, start no new ones)'",
        "  freeze_new_threads: '\"dont start new threads\"'",
        "  resume: '\"continue\" / \"continue as usual\"'",
        "",
    ]
    return "\n".join(lines)


STACK_DEPENDENT_KEYS = ("fast_checks", "layer_boundary_check", "execution_lanes", "ownership_labels", "lane_mapping_note")


def parse_override(key: str, text: str, template: Any) -> Any:
    """Turn the VALUE of --set KEY=VALUE into the type the key needs. Raises ValueError with the fix."""
    text = text.strip()
    if isinstance(template, bool):
        if text not in ("true", "false"):
            raise ValueError(f"{key} must be true or false (lower case), got '{text}'")
        return text == "true"
    if isinstance(template, int):
        if not re.fullmatch(r"-?\d+", text):
            raise ValueError(f"{key} must be a whole number, got '{text}'")
        return int(text)
    if isinstance(template, list):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a JSON list, e.g. --set '{key}=[\"a\", \"b\"]', got '{text}'")
        return value
    if isinstance(template, str):
        if len(text) >= 2 and text[0] == text[-1] == '"':
            try:
                value = json.loads(text)
                if isinstance(value, str):
                    return value
            except json.JSONDecodeError:
                pass
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def apply_overrides(raw: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    """Apply --set KEY=VALUE pairs to a raw config. Raises ValueError on a bad key or value."""
    raw = dict(raw)
    defaults = default_config()
    legacy_templates = {"round4_hard_stop": True, "coordinator_compact_at_tokens": 0,
                        "critical_worker_model": "", "standard_worker_model": ""}
    slot_keys = [k for k, _, _ in MODEL_SLOTS]
    parsed: list[tuple[str, Any]] = []
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got '{item}'")
        key, text = item.split("=", 1)
        key = key.strip()
        if key.startswith("token_cfg."):
            name = key.split(".", 1)[1]
            known_t = {k: v for k, v in TOKEN_PROFILES["balanced"].items() if k != "description"}
            if name not in known_t:
                raise ValueError(f"unknown token setting '{name}'; known: {', '.join(sorted(known_t))}")
            parsed.append((key, parse_override(key, text, known_t[name])))
            continue
        if key == "today":
            raise ValueError("today is no longer a setting: the date is stamped at every run")
        if key in legacy_templates:
            parsed.append((key, parse_override(key, text, legacy_templates[key])))
            continue
        if key not in defaults or key == "token_cfg":
            raise ValueError(f"unknown config key '{key}'; see --dump-schema for the keys")
        parsed.append((key, parse_override(key, text, defaults[key])))
    set_keys = {k for k, _ in parsed}
    for key, value in parsed:
        if key.startswith("token_cfg."):
            name = key.split(".", 1)[1]
            raw["token_cfg"] = {**(raw.get("token_cfg") or {}), name: value}
            continue
        if key == "model_preset":
            if value not in MODEL_PRESETS and value != "custom":
                raise ValueError(f"unknown model preset '{value}'; choose one of: {', '.join(MODEL_PRESETS)}, custom")
            # a new preset replaces the stored slot models, except slots set in this same call
            for sk in slot_keys + ["critical_worker_model", "standard_worker_model"]:
                if sk not in set_keys:
                    raw.pop(sk, None)
        if key == "profile_key":
            if value not in TOKEN_PROFILES:
                raise ValueError(f"unknown token profile '{value}'; choose one of: {', '.join(TOKEN_PROFILES)}")
            # a new profile replaces the stored token numbers, except those set in this same call
            keep = {k.split(".", 1)[1] for k in set_keys if k.startswith("token_cfg.")}
            raw["token_cfg"] = {k: v for k, v in (raw.get("token_cfg") or {}).items() if k in keep}
        if key == "stack_key":
            if value not in STACK_PRESETS:
                raise ValueError(f"unknown stack preset '{value}'; choose one of: {', '.join(STACK_PRESETS)}")
            # a new stack replaces lanes, labels, mapping note and checks, except those set in this same call
            for dk in STACK_DEPENDENT_KEYS:
                if dk not in set_keys:
                    raw.pop(dk, None)
        if key == "workspace_root" and "environment" not in set_keys:
            raw.pop("environment", None)  # re-derived from the new root
        raw[key] = value
    return raw


_SETTING_RE = re.compile(r"^( {0,4})([a-z_]+): (.+)$")


def change_summary(old_text: str, new_text: str) -> list[str]:
    """Plain-language diff between two generated rulesets: header and profile settings, then rule ids."""

    def settings(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        section = ""
        authority: list[str] = []
        for line in text.split("\nmeta:")[0].splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if re.fullmatch(r"[a-z_]+:", line):
                section = line[:-1]
                continue
            if section == "authority" and line.startswith("  - "):
                authority.append(line[4:].split("#")[0].strip())
                continue
            m = _SETTING_RE.match(line)
            if m and m.group(2) != "date":
                if not m.group(1):
                    section = ""
                out[m.group(2)] = m.group(3).strip()
        if authority:
            out["authority"] = " > ".join(authority)
        return out

    def rules(text: str) -> dict[str, tuple[str, str]]:
        return {rid: (scope, body) for rid, scope, body in _RULE_RE.findall(text)}

    def show(v: str) -> str:
        """A value as the owner would write it: no quotes, lists as a, b, c (older files were not quoted)."""
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            return ", ".join(show(x) for x in re.split(r",\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", v[1:-1]) if x.strip())
        if len(v) >= 2 and v[0] == v[-1] == '"':
            return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return v

    out: list[str] = []
    so, sn = settings(old_text), settings(new_text)
    for k in [*so, *[k for k in sn if k not in so]]:
        before, after = show(so[k]) if k in so else "(not set)", show(sn[k]) if k in sn else "(removed)"
        if before != after:
            out.append(f"  setting {k}: {before} -> {after}")
    ro, rn = rules(old_text), rules(new_text)
    added, removed = sorted(set(rn) - set(ro)), sorted(set(ro) - set(rn))
    rescoped = sorted(r for r in set(ro) & set(rn) if ro[r][0] != rn[r][0])
    reworded = sorted(r for r in set(ro) & set(rn) if ro[r][0] == rn[r][0] and ro[r][1] != rn[r][1])
    if added:
        out.append("  rules added: " + ", ".join(added))
    if removed:
        out.append("  rules removed: " + ", ".join(removed))
    for r in rescoped:
        out.append(f"  rule {r} now binds {rn[r][0]} (was {ro[r][0]})")
    if reworded:
        out.append("  rules reworded: " + ", ".join(reworded))
    return out or ["  nothing: the ruleset is identical"]


def decision_summary(summary: list[str]) -> str:
    """The change list boiled down to what belongs in a decision-log entry."""
    settings = [s.strip()[len("setting "):] for s in summary if s.strip().startswith("setting ") and not s.strip().startswith("setting version")]
    other = [s.strip() for s in summary if not s.strip().startswith("setting ") and not s.strip().startswith("rules reworded")]
    reworded = next((s.split(":", 1)[1].count(",") + 1 for s in summary if s.strip().startswith("rules reworded")), 0)
    parts = []
    if settings:
        parts.append("; ".join(settings) if len(settings) <= 6 else f"{len(settings)} settings changed (see the preview)")
    parts += other
    if reworded:
        parts.append(f"{reworded} rule{'s' if reworded != 1 else ''} reworded")
    return "; ".join(parts) or "none"


def _body(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not re.match(r"(version|date): ", l))


def _version_tuple(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v.strip().strip("\"'"))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def file_version(text: str) -> str:
    m = re.search(r"^version: *(\S+)", text, re.MULTILINE)
    return m.group(1).strip("\"'") if m else ""


def check_output(rules_text: str, state_text: str, extracts: dict[str, str], cfg: dict[str, Any]) -> str | None:
    """Parse what was just rendered. Returns a problem description, or None when the output is sound."""
    expected = len(_RULE_RE.findall(rules_text))
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            data = yaml.safe_load(rules_text)
            state = yaml.safe_load(state_text)
            for role, text in extracts.items():
                if not isinstance(yaml.safe_load(text), dict):
                    return f"the extract for {role} is not a YAML mapping"
        except yaml.YAMLError as exc:
            return f"generated YAML does not parse: {one_line(exc)}"
        if not isinstance(data, dict) or not isinstance(state, dict):
            return "generated YAML is not a mapping at the top level"
        got = sum(len(v) for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0])
        if state.get("project") != cfg["project_name"]:
            return "project name did not survive in project-state.yaml"
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import audit_rules  # type: ignore

        data, rules = audit_rules.fallback_parse(rules_text)
        got = len(rules)
    if data.get("project") != cfg["project_name"]:
        return f"project name did not survive the round trip (got {data.get('project')!r})"
    if got != expected:
        return f"{expected} rules were rendered but {got} can be read back"
    return None


# ----------------------------------------------------------------------------
# Migration: derive a config from an existing (older or hand-edited) ruleset
# ----------------------------------------------------------------------------

def split_enforced(text: str) -> tuple[str, str]:
    """'Rule. Enforced by: X.' -> ('Rule.', 'X'); 'review only' and a missing sentence give ''."""
    m = re.search(r"\s*Enforced by:\s*(.+?)\.?\s*$", text)
    if not m:
        return text.strip(), ""
    check = m.group(1).strip()
    return text[: m.start()].strip(), "" if check.lower() == "review only" else check


def derive_config(rules_path: Path, state_path: Path | None) -> tuple[dict[str, Any], list[str]]:
    """Read an existing ruleset and return (config, notes). Nothing is written."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import audit_rules  # type: ignore

    text = rules_path.read_text(encoding="utf-8")
    data = audit_rules.load_yaml_or_none(rules_path)
    if data is None:
        data, rules = audit_rules.fallback_parse(text)
    else:
        rules = audit_rules.rules_from_data(data, text)
    by_id = {r.id: r for r in rules if r.id}
    notes: list[str] = []
    cfg: dict[str, Any] = {}

    def put(key: str, value: Any, kind: type) -> None:
        if value is None or value == "":
            notes.append(f"not found, default used: {key}")
        elif kind is list and isinstance(value, list):
            cfg[key] = [str(x) for x in value if str(x).strip()]
        elif kind is int:
            if isinstance(value, int) and not isinstance(value, bool):
                cfg[key] = value
            else:
                notes.append(f"not a number, default used: {key} ({value!r})")
        elif kind is bool:
            if isinstance(value, bool):
                cfg[key] = value
            else:
                notes.append(f"not true/false, default used: {key} ({value!r})")
        else:
            cfg[key] = str(value)

    def text_of(rid: str) -> str:
        return by_id[rid].text if rid in by_id else ""

    put("project_name", data.get("project"), str)
    put("repo_slug", data.get("repository"), str)
    put("is_public", data.get("public_repo"), bool)
    put("timezone", data.get("time_zone_owner"), str)
    m = re.fullmatch(r"(.*?)\s*\(GitHub\s+(.+?)\)", str(data.get("owner") or ""))
    if m:
        cfg["owner_name"], cfg["owner_gh"] = m.group(1), m.group(2)
    elif data.get("owner"):
        cfg["owner_name"] = str(data["owner"])
        notes.append("owner GitHub handle not found, default used: owner_gh")
    version = file_version(text)
    cfg["ruleset_version"] = version if _version_tuple(version) != (0, 0, 0) else "2.0.0"

    prof = data.get("project_profile") if isinstance(data.get("project_profile"), dict) else {}
    stack = prof.get("stack_preset")
    cfg["stack_key"] = stack if stack in STACK_PRESETS else "custom"
    if stack not in STACK_PRESETS:
        notes.append(f"stack preset {stack!r} is not known; using 'custom' with the lanes and labels found")
    put("target_platforms", prof.get("target_platforms"), list)
    put("fast_checks", prof.get("fast_checks"), str)
    put("local_os_shell", prof.get("local_environment"), str)
    put("local_clone_path", prof.get("local_clone_path"), str)
    put("execution_lanes", prof.get("execution_lanes"), list)
    labels = [str(x) for x in prof.get("file_ownership_labels") or []] if isinstance(prof.get("file_ownership_labels"), list) else []
    good = [l for l in labels if re.fullmatch(r"lane:[a-z0-9_-]+", l)]
    if good:
        cfg["ownership_labels"] = good
    if len(good) != len(labels):
        notes.append("labels dropped (not of the form lane:<name>): " + ", ".join(l for l in labels if l not in good))
    put("lane_mapping_note", prof.get("lane_mapping_note"), str)
    put("workspace_root", prof.get("workspace_root"), str)
    for key in ("environment", "default_branch", "governance_branch"):
        if prof.get(key):
            cfg[key] = str(prof[key])
    if isinstance(prof.get("critical_paths"), list):
        cfg["critical_paths"] = [str(x) for x in prof["critical_paths"]]
    if isinstance(prof.get("label_paths"), list):
        cfg["label_paths"] = [str(x) for x in prof["label_paths"]]
    if isinstance(prof.get("seam_groups"), list):
        cfg["seam_groups"] = [str(x) for x in prof["seam_groups"]]
    if isinstance(prof.get("seam_audit_every_prs"), int) and not isinstance(prof.get("seam_audit_every_prs"), bool):
        cfg["seam_audit_every_prs"] = prof["seam_audit_every_prs"]
    if isinstance(prof.get("doc_paths"), list):
        cfg["doc_paths"] = [str(x) for x in prof["doc_paths"]]
    if isinstance(prof.get("governance_paths"), list):
        cfg["governance_paths"] = [str(x) for x in prof["governance_paths"]]
    if isinstance(prof.get("promised_tests_check"), str):
        cfg["promised_tests_check"] = prof["promised_tests_check"]

    execp = data.get("execution_profile") if isinstance(data.get("execution_profile"), dict) else {}
    routing = execp.get("model_routing") if isinstance(execp.get("model_routing"), dict) else {}
    cfg["model_preset"] = "custom"
    label_to_key = {label: key for key, label, _ in MODEL_SLOTS}
    for label, key in label_to_key.items():
        if routing.get(label):
            cfg[key] = str(routing[label])
    if routing.get("implementation_and_critical_review"):
        for key in ("critical_model", "implementation_model", "specify_model"):
            cfg.setdefault(key, str(routing["implementation_and_critical_review"]))
    if routing.get("standard_review_audit_and_kb"):
        for key in ("review_model", "ops_model"):
            cfg.setdefault(key, str(routing["standard_review_audit_and_kb"]))
    missing_slots = [label for label, key in label_to_key.items() if key not in cfg]
    if missing_slots:
        notes.append("no model found for: " + ", ".join(missing_slots) + " (the 'balanced' preset fills them; check with the owner)")
        for label in missing_slots:
            cfg[label_to_key[label]] = MODEL_PRESETS[DEFAULT_MODEL_PRESET][label_to_key[label]]

    token = execp.get("token_economy") if isinstance(execp.get("token_economy"), dict) else {}
    profile = token.get("profile_name")
    cfg["profile_key"] = profile if profile in TOKEN_PROFILES else "balanced"
    if profile not in TOKEN_PROFILES:
        notes.append(f"token profile {profile!r} is not known; using 'balanced' with the numbers found")
    tok: dict[str, Any] = {}
    for key, template in TOKEN_PROFILES["balanced"].items():
        if key == "description" or key not in token:
            continue
        v = token[key]
        if isinstance(template, bool):
            ok = isinstance(v, bool)
        elif isinstance(template, int):
            ok = isinstance(v, int) and not isinstance(v, bool)
        else:
            ok = isinstance(v, str) and bool(v.strip())
        if ok:
            tok[key] = v
        else:
            notes.append(f"token_economy.{key} = {v!r} is not usable; profile value used")
    if tok:
        cfg["token_cfg"] = tok
    for key in ("cache_ttl_minutes", "coordinator_compact_every_batches", "coordinator_compact_at_tokens", "rounds_after_escalation"):
        v = token.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            cfg[key] = v

    scopes = {s.strip() for r in rules for s in str(r.applies_to).split(",")}
    cfg["dispatcher"] = "dispatcher" in scopes
    cfg["advisor"] = "advisor" in scopes
    if cfg["advisor"] and routing.get("advisor"):
        cfg["advisor_model"] = str(routing["advisor"])
    cfg["acceptance_contracts"] = any(re.search(r"acceptance[- ]contract", r.text, re.I) for r in rules)
    cfg["allow_parallel_release_branch"] = "LANE-04" in by_id
    m = re.search(r"hand steps:\s*(.+?)\.?$", text_of("ROLE-02"))
    if m:
        cfg["owner_hand_steps"] = [x.strip() for x in m.group(1).split(";") if x.strip()]
    else:
        notes.append("not found, default used: owner_hand_steps (ROLE-02)")
    m = re.search(r"autonomously\s+(.+?),\s*keeping", text_of("AUTO-01"))
    if m:
        cfg["autonomy_horizon"] = m.group(1)
    else:
        notes.append("not found, default used: autonomy_horizon (AUTO-01)")
    m = re.search(r"touches\s+(.+?),?\s+or carries risk:high", text_of("CRIT-01"))
    if m:
        cfg["critical_areas"] = [x.strip() for x in m.group(1).split(", ") if x.strip()]
    m = re.search(r"after review round (\d+)", text_of("REV-04"))
    if m:
        cfg["escalate_after_round"] = int(m.group(1))
    elif cfg.get("implementation_model") != cfg.get("critical_model"):
        cfg["escalate_after_round"] = 0
    if "REV-01" in by_id and not re.search(r"hard stop|owner sign-?off", text_of("REV-01"), re.I):
        notes.append("REV-01 has no hard stop for the owner at the last critical review round; the regenerated ruleset has one (invariant 5)")
    all_text = " ".join(r.text for r in rules)
    cfg["github_rest_only"] = bool(re.search(r"GraphQL", all_text))
    cfg["local_ui_loopback_only"] = "127.0.0.1" in all_text
    cfg["no_telemetry"] = bool(re.search(r"\btelemetry\b", all_text, re.I))
    pref = text_of("PREF-01")
    prefs: list[str] = []
    if re.search(r"no inline comments", pref):
        prefs.append("Shell commands contain no inline comments inside code blocks; explanations go outside.")
    else:
        rest = re.sub(r"^Report times to .+? in \S+\.\s*", "", pref).strip()
        if rest and rest != pref.strip():
            prefs.append(rest)
    cfg["owner_prefs"] = prefs

    customs: list[str] = []
    cfg["layer_boundary_check"] = ""
    for r in rules:
        if not (r.id or "").startswith("INV-"):
            continue
        if r.text.startswith("Licence gate"):
            body, check = split_enforced(r.text)
            m = re.search(r"Banned licences:\s*(.+?)\.?$", body)
            if m:
                cfg["banned_licences"] = [x.strip() for x in m.group(1).split(",") if x.strip()]
            cfg["licence_check"] = check
        elif r.text.startswith("Architectural layer boundaries"):
            m = re.search(r"enforced automatically \((.+?)\);", r.text)
            cfg["layer_boundary_check"] = m.group(1) if m else "import linting"
        elif r.text.startswith("Zero telemetry"):
            cfg["telemetry_check"] = split_enforced(r.text)[1]
        else:
            body, check = split_enforced(r.text)
            customs.append(body + (f" [check: {check}]" if check else ""))
    cfg["custom_invariants"] = customs

    if state_path and state_path.is_file():
        st = state_path.read_text(encoding="utf-8")
        m = re.search(r"^notifications_pending:\n((?:[ \t]+-.*\n?)+)", st, re.MULTILINE)
        if m:
            cfg["notify_triggers"] = [audit_rules.unquote(x.strip()[1:].strip()) for x in m.group(1).splitlines() if x.strip()]
        m = re.search(r"^\s*active_milestones:\s*\[(.*)\]", st, re.MULTILINE)
        if m and m.group(1).strip():
            cfg["active_milestones"] = [audit_rules.unquote(x) for x in audit_rules.split_inline(m.group(1))]
    else:
        notes.append("no state file read: notify_triggers and active_milestones use defaults (the live state file is kept anyway)")

    try:
        normalized = normalize_config(cfg)
    except ConfigError as exc:
        raise ConfigError("the derived config is not valid; fix these values in the JSON by hand:\n" + str(exc)) from exc
    produced = {rid for rid, _, _ in _RULE_RE.findall(render_rules_yaml(normalized))}
    for r in rules:
        if r.id and r.id not in produced:
            notes.append(f"rule {r.id} ({r.applies_to}) is not produced by the generator and would be dropped: \"{one_line(r.text)[:160]}\"")
    return cfg, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate claude-project-rules.yaml, per-role extracts and project-state.yaml from a config"
    )
    parser.add_argument("--from-json", type=Path, help="config JSON for non-interactive generation")
    parser.add_argument("--out-dir", type=Path, default=Path("."), help="target directory (default: current directory)")
    parser.add_argument("--dump-schema", action="store_true", help="print the config keys with their defaults and exit")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="change one config value before generating (repeatable; with --from-json). true/false for switches, "
        "whole numbers for numbers, a JSON list for lists, plain text otherwise; token numbers are token_cfg.<name>. "
        "model_preset, profile_key and stack_key replace the stored values that depend on them.",
    )
    parser.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    parser.add_argument("--reset-state", action="store_true",
                        help="overwrite an existing project-state.yaml (default: keep it, it holds live state)")
    parser.add_argument("--model-presets", action="store_true",
                        help="print the model routing presets (slot -> model per preset) as JSON and exit")
    parser.add_argument("--derive-config", type=Path, metavar="RULES_YAML",
                        help="read an existing ruleset (older or hand-edited) and print the config that reproduces it; writes nothing unless --out is given")
    parser.add_argument("--state", type=Path, help="with --derive-config: the existing project-state.yaml to read triggers and milestones from")
    parser.add_argument("--out", type=Path, help="with --derive-config: write the derived config JSON to this file")
    args = parser.parse_args()

    if args.model_presets:
        table = {
            name: {label: slots[key] for key, label, _ in MODEL_SLOTS} for name, slots in MODEL_PRESETS.items()
        }
        print(json.dumps({"default": DEFAULT_MODEL_PRESET, "slots": {l: d for _, l, d in MODEL_SLOTS}, "presets": table}, indent=2))
        return 0

    if args.dump_schema:
        schema = default_config()
        schema["token_cfg"] = {k: v for k, v in schema["token_cfg"].items() if k != "description"}
        print(json.dumps(schema, indent=2))
        return 0

    if args.derive_config:
        if not args.derive_config.is_file():
            print(f"error: {args.derive_config} not found", file=sys.stderr)
            return 2
        try:
            derived, notes = derive_config(args.derive_config, args.state)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        payload = json.dumps(derived, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(payload, encoding="utf-8")
            print(f"Derived config written to {args.out}. Nothing else was changed.")
        else:
            print(payload, end="")
        print("\nCheck before regenerating:" if notes else "\nEvery value was found in the ruleset.", file=sys.stderr)
        for n in notes:
            print(f"  - {n}", file=sys.stderr)
        return 0

    if args.overrides and not args.from_json:
        parser.error("--set needs --from-json <governance-config.json>")
    try:
        if args.from_json:
            try:
                raw_cfg = json.loads(args.from_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"error: cannot read {args.from_json}: {exc}", file=sys.stderr)
                return 2
            if not isinstance(raw_cfg, dict):
                print("error: the config must be a JSON object", file=sys.stderr)
                return 2
            cfg = normalize_config(apply_overrides(raw_cfg, args.overrides))
            out_dir = args.out_dir.expanduser().resolve()
        else:
            print("Claude Multi-Thread Project Rules Generator")
            print("Generates static rules, per-role extracts and the runtime state file.")
            cfg = run_wizard()
            header(6, "COMPILATION & FILE OUTPUT", "Writing the rules, the per-role extracts and the state file.")
            out_dir = Path(ask("Output directory", str(args.out_dir))).expanduser().resolve()
    except ValueError as exc:  # ConfigError is a ValueError
        print("error: nothing was written.\n" + "\n".join(f"  - {l}" for l in str(exc).splitlines()), file=sys.stderr)
        return 2

    rules_path = out_dir / "claude-project-rules.yaml"
    state_path = out_dir / "project-state.yaml"
    config_path = out_dir / "governance-config.json"
    extract_dir = out_dir / EXTRACT_DIR

    today = today_iso()
    had_rules = rules_path.exists()
    old_text = rules_path.read_text(encoding="utf-8") if had_rules else ""
    old_version = file_version(old_text) if had_rules else ""
    if had_rules and _version_tuple(old_version) > _version_tuple(cfg["ruleset_version"]):
        cfg["ruleset_version"] = old_version
    new_rules = render_rules_yaml(cfg, today)
    changed = had_rules and _body(old_text) != _body(new_rules)
    if changed:
        major, minor, _ = _version_tuple(cfg["ruleset_version"])
        cfg["ruleset_version"] = f"{major}.{minor + 1}.0"
        new_rules = render_rules_yaml(cfg, today)
    new_state = render_state_yaml(cfg, today)
    extracts = role_extracts(new_rules)

    problem = check_output(new_rules, new_state, extracts, cfg)
    if problem:
        print(f"error: nothing was written. The generated files failed their own check: {problem}", file=sys.stderr)
        return 3

    summary = change_summary(old_text, new_rules) if had_rules else []
    if args.dry_run:
        print("Dry run, nothing written.")
        print("\n".join(summary) if had_rules else "No existing ruleset to compare with; a full set would be generated.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(new_rules, encoding="utf-8")
    extract_dir.mkdir(exist_ok=True)
    for role, text in extracts.items():
        (extract_dir / f"{role}.yaml").write_text(text, encoding="utf-8")
    stale = sorted(p.name for p in extract_dir.glob("*.yaml") if p.stem not in extracts)
    for name in stale:
        (extract_dir / name).unlink()
    keep_state = state_path.exists() and not args.reset_state
    if not keep_state:
        state_path.write_text(new_state, encoding="utf-8")
    config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    state_note = "kept as it is (live state; --reset-state rewrites it)" if keep_state else "written"
    print(
        f"Generated (ruleset version {cfg['ruleset_version']}, {today}):\n"
        f"  1. {rules_path}\n"
        f"  2. {extract_dir}/<role>.yaml ({', '.join(extracts)})\n"
        f"  3. {state_path} ({state_note})\n"
        f"  4. {config_path} (normalized config; re-run --from-json on it to regenerate)"
    )
    if stale:
        print("Removed extracts of roles that no longer exist: " + ", ".join(stale))
    if had_rules:
        print("\nWhat changed:\n" + "\n".join(summary))
    if changed:
        print(
            "\nDecision-log entry for the coordinator to record with the next D-number (META-01, KB-01):\n"
            f"  Ruleset regenerated on {today}: version {old_version or '?'} -> {cfg['ruleset_version']}, approved by the owner.\n"
            "  Changes: " + decision_summary(summary) + "\n"
            "  Owner message: \"<quote the owner's yes and its date>\""
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
