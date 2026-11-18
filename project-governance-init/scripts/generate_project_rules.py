#!/usr/bin/env python3
"""
Interactive & JSON-Driven Project Rules Generator for Multi-Thread Claude Projects.

Generates decoupled:
  1. `claude-project-rules.yaml` (static governance, project profile, decoupled model/token profiles)
  2. `project-state.yaml` (volatile runtime state, active flags, pending notifications)

Supports both:
  - Interactive 6-stage terminal wizard: `python3 generate_project_rules.py`
  - Deterministic non-interactive rendering (for Claude Skills):
      `python3 generate_project_rules.py --from-json config.json --out-dir .`
      `python3 generate_project_rules.py --dump-schema`

Config keys (see --dump-schema for defaults): project_name, repo_slug, is_public,
owner_name, owner_gh, timezone, local_os_shell, local_clone_path, workspace_root,
stack_key, fast_checks, target_platforms, coordinator_model, critical_worker_model,
standard_worker_model, profile_key, token_cfg{...}, autonomy_horizon, round4_hard_stop,
owner_hand_steps, notify_triggers, execution_lanes, ownership_labels, lane_mapping_note,
allow_parallel_release_branch, no_telemetry, banned_licences, custom_invariants,
acceptance_contracts, dispatcher, active_milestones, today.

`workspace_root` is where shared files (plans/, project-state.yaml) live: the
claude.ai Project mount `/mnt/project-files` or a folder inside a repo checkout.
Unknown keys are ignored with a warning on stderr.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any


TOKEN_PROFILES: dict[str, dict[str, Any]] = {
    "frugal": {
        "description": "Minimizes token spend while keeping strong models on critical paths.",
        "max_concurrent_lanes": 2,
        "replace_at_compressions": 1,
        "watchdog_interval_minutes": 120,
        "watchdog_max_nudges": 3,
        "non_critical_max_review_rounds": 1,
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
    },
    "custom": {
        "execution_lanes": ["lane_a", "lane_b", "app_release"],
        "file_ownership_labels": ["lane:core", "lane:a", "lane:b", "lane:app", "lane:infra", "lane:docs"],
        "lane_mapping_note": (
            "Define explicit mapping from file-ownership labels to execution lanes. "
            "core is cross-cutting and critical (requires lane:infra). docs may be edited by any lane."
        ),
        "fast_checks": "lint, format check, fast test suite",
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


def yaml_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def header(stage_num: int, title: str, explanation: str) -> None:
    print("\n" + "=" * 72)
    print(f"STAGE {stage_num}/6: {title}")
    print("-" * 72)
    print(explanation)
    print("=" * 72)


def default_config(project_name: str = "my-project") -> dict[str, Any]:
    stack_key = "python_cli_or_service"
    preset = STACK_PRESETS[stack_key]
    profile_key = "balanced"
    return {
        "today": datetime.date.today().isoformat(),
        "project_name": project_name,
        "repo_slug": f"owner/{project_name}",
        "is_public": True,
        "owner_name": "Project Owner",
        "owner_gh": "owner",
        "timezone": "UTC",
        "local_os_shell": "unspecified",
        "local_clone_path": f"~/projects/{project_name}",
        "workspace_root": "/mnt/project-files",
        "stack_key": stack_key,
        "fast_checks": preset["fast_checks"],
        "target_platforms": ["ubuntu-latest", "macos-latest", "windows-latest"],
        "coordinator_model": "Fable 5.1",
        "critical_worker_model": "Opus 5.5 high",
        "standard_worker_model": "Opus 5.5 medium",
        "profile_key": profile_key,
        "token_cfg": dict(TOKEN_PROFILES[profile_key]),
        "autonomy_horizon": "until v1.0 is finished",
        "round4_hard_stop": True,
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
        "no_telemetry": True,
        "banned_licences": ["AGPL", "SSPL", "non-commercial", "unclear"],
        "custom_invariants": [],
        "acceptance_contracts": True,
        "dispatcher": False,
        "active_milestones": ["v0.1"],
    }


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    base = default_config(raw.get("project_name", "my-project"))
    stack_key = raw.get("stack_key", base["stack_key"])
    if stack_key in STACK_PRESETS:
        preset = STACK_PRESETS[stack_key]
        base["fast_checks"] = preset["fast_checks"]
        base["execution_lanes"] = list(preset["execution_lanes"])
        base["ownership_labels"] = list(preset["file_ownership_labels"])
        base["lane_mapping_note"] = preset["lane_mapping_note"]

    profile_key = raw.get("profile_key", base["profile_key"])
    if profile_key in TOKEN_PROFILES:
        base["token_cfg"] = dict(TOKEN_PROFILES[profile_key])

    for k, v in raw.items():
        if k == "token_cfg" and isinstance(v, dict):
            unknown_t = sorted(set(v) - set(base["token_cfg"]))
            if unknown_t:
                print(f"warning: unknown token_cfg keys ignored: {', '.join(unknown_t)}", file=sys.stderr)
            base["token_cfg"].update({tk: tv for tk, tv in v.items() if tk in base["token_cfg"]})
        elif k not in base:
            print(f"warning: unknown config key ignored: {k}", file=sys.stderr)
        elif v is not None:
            base[k] = v

    base["workspace_root"] = str(base["workspace_root"]).rstrip("/") or "/"
    return base


def run_wizard() -> dict[str, Any]:
    today = datetime.date.today().isoformat()

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
    coordinator_model = ask("Coordinator model", "Fable 5.1")
    critical_worker_model = ask("Critical implementation & review model", "Opus 5.5 high")
    standard_worker_model = ask("Standard review, audit & KB model", "Opus 5.5 medium")

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

    if ask_bool("Customize individual token profile numbers?", False):
        token_cfg["max_concurrent_lanes"] = int(
            ask("Max concurrent implementation lanes", str(token_cfg["max_concurrent_lanes"]))
        )
        token_cfg["replace_at_compressions"] = int(
            ask("Replace thread at N context compressions", str(token_cfg["replace_at_compressions"]))
        )
        token_cfg["watchdog_interval_minutes"] = int(
            ask("Watchdog check interval (minutes)", str(token_cfg["watchdog_interval_minutes"]))
        )
        token_cfg["watchdog_max_nudges"] = int(
            ask("Max watchdog nudges before replacing stalled thread", str(token_cfg["watchdog_max_nudges"]))
        )
        token_cfg["non_critical_max_review_rounds"] = int(
            ask("Max review rounds for non-critical PRs", str(token_cfg["non_critical_max_review_rounds"]))
        )

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
    round4_hard_stop = ask_bool(
        "Enforce hard stop for owner sign-off if a critical PR hits review round 4 (D-703)?",
        True,
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
        "Cross-cutting core changes always require 'lane:infra' and act as a single-thread lock.",
    )
    execution_lanes = ask_list("Execution lanes", preset["execution_lanes"])
    ownership_labels = ask_list("File-ownership labels", preset["file_ownership_labels"])
    lane_mapping_note = ask("Lane-to-label ownership mapping summary", preset["lane_mapping_note"])
    allow_parallel_release_branch = ask_bool(
        "Allow release branch thread to run alongside app/release lane while release/* is open?",
        True,
    )
    dispatcher = ask_bool(
        "Add a dispatcher thread for per-PR operations (recommended with 3+ lanes or a coordinator that compresses more than once per batch)?",
        False,
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

    return {
        "today": today,
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
        "coordinator_model": coordinator_model,
        "critical_worker_model": critical_worker_model,
        "standard_worker_model": standard_worker_model,
        "profile_key": profile_key,
        "token_cfg": token_cfg,
        "autonomy_horizon": autonomy_horizon,
        "round4_hard_stop": round4_hard_stop,
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
    }


def render_rules_yaml(cfg: dict[str, Any]) -> str:
    t = cfg["token_cfg"]
    platforms_yaml = ", ".join(cfg["target_platforms"])
    exec_lanes_yaml = ", ".join(cfg["execution_lanes"])
    labels_yaml = ", ".join(cfg["ownership_labels"])
    banned_lic_str = ", ".join(cfg["banned_licences"])
    hand_steps_str = "; ".join(cfg["owner_hand_steps"])
    ws = cfg["workspace_root"]

    q = chr(39)
    disp = bool(cfg.get("dispatcher", False))
    ops = "dispatcher" if disp else "coordinator"
    merge_go = (
        "an explicit go (dispatcher for non-critical PRs, coordinator for critical ones)"
        if disp
        else "the coordinator" + q + "s explicit go"
    )
    if disp:
        role04 = (
            "The coordinator splits work into lane batches, approves plans, logs non-scope decisions with "
            "sequential D-numbers, grants merge go for critical PRs, and talks to the owner. It hands each batch "
            "to the dispatcher and reads its batch report and the ledgers, not worker messages."
        )
    else:
        role04 = (
            "The coordinator splits work into lane batches, manages thread lifecycles, approves plans, logs "
            "non-scope decisions with sequential D-numbers, grants merge go, and runs fitness checks. It reads "
            "ledgers, round reports and PR state at hand-offs instead of relaying messages between threads."
        )

    extra_role_rules: list[str] = []
    contract_plan_rules: list[str] = []
    contract_review_rules: list[str] = []
    if cfg.get("acceptance_contracts", True):
        extra_role_rules += [
            "  - id: ROLE-10",
            "    applies_to: acceptance",
            f"    rule: {yaml_quote('Following ' + ws + '/tools/acceptance-contracts.md, the acceptance thread turns the coordinator' + q + 's interview notes into ' + ws + '/plans/contract-<NNN>-<slug>.yaml: binary criteria, each with a verify step and a source (research: URL and retrieval date), plus a core probe. It lints the file clean, returns only the contract_tool.py summary, and never approves it.')}",
        ]
        contract_plan_rules = [
            "  - id: PLAN-03",
            "    applies_to: coordinator",
            f"    rule: {yaml_quote('Before a milestone' + q + 's first plan, interview the owner and have an acceptance thread draft the acceptance contract. It binds only after the owner' + q + 's own approval, logged with a D-number and the contract hash; approved criteria are frozen, and a change is a new version with a new D-number.')}",
            "  - id: PLAN-04",
            "    applies_to: implementation",
            '    rule: "Plans cite the acceptance-contract criterion ids they cover (read them with contract_tool.py brief); the PR body lists each covered criterion with the command run and its result. A /goal loop on criteria stops at execution_profile.token_economy.goal_turn_cap turns."',
            "  - id: PLAN-05",
            "    applies_to: coordinator",
            '    rule: "A milestone closes only when every must criterion and the core probe pass and every should criterion passes or has a deferred issue; log the result as a D-entry."',
        ]
        contract_review_rules = [
            "  - id: REV-03",
            "    applies_to: review",
            '    rule: "Read the diff and the acceptance contract before the plan and PR description. Confirm each criterion the PR claims from CI output or by re-running its verify step; a claimed criterion without passing proof is a must-fix finding."',
        ]
    if disp:
        extra_role_rules += [
            "  - id: ROLE-11",
            "    applies_to: dispatcher",
            f"    rule: {yaml_quote('The dispatcher runs one batch at a time for the coordinator: it spawns, fitness-checks, watches and replaces worker threads, keeps ' + ws + '/plans/batch-<NNN>.md and the ledgers current, and grants merge go for non-critical PRs with green CI. It never approves plans, never touches scope, and reports to the coordinator once per batch or on escalation.')}",
        ]
    dispatcher_thread_rules: list[str] = []
    if disp:
        dispatcher_thread_rules = [
            "  - id: THR-05",
            "    applies_to: dispatcher",
            f"    rule: {yaml_quote('The dispatcher keeps its whole working state in ' + ws + '/plans/batch-<NNN>.md and the ledgers, so it is replaced at its first compression, at the next hand-off.')}",
        ]

    lines: list[str] = [
        f"# {cfg['project_name']}: reusable project rules for multi-thread Claude execution",
        "# Generated by project-governance-init (decoupled model routing + token economy)",
        "#",
        "# SCHEMA",
        "#   version:           semver of this ruleset",
        "#   date:              last audit/generation date (YYYY-MM-DD, UTC)",
        "#   authority:         precedence order when sources conflict (first wins)",
        "#   project_profile:   project-specific stack, paths, lanes, and CI checks",
        "#   execution_profile: decoupled model routing and token-economy settings",
        "#   <section>:         active rules with id, applies_to, rule, and optional values/note",
        "",
        "version: 2.0.0",
        f"date: {cfg['today']}",
        f"project: {cfg['project_name']}",
        f"repository: {cfg['repo_slug']}",
        f"public_repo: {str(cfg['is_public']).lower()}",
        f"owner: {yaml_quote(cfg['owner_name'] + ' (GitHub ' + cfg['owner_gh'] + ')')}",
        f"time_zone_owner: {yaml_quote(cfg['timezone'])}",
        "",
        "authority:",
        "  - project_instructions",
        "  - kb_decision_log        # newest D-entry first",
        "  - pending_kb_batch       # decided in session, awaiting daily/batch KB PR",
        "  - owner_messages",
        "  - project_memory",
        "  - repo_claude_md",
        "",
        "project_profile:",
        f"  stack_preset: {cfg['stack_key']}",
        f"  target_platforms: [{platforms_yaml}]",
        f"  fast_checks: {yaml_quote(cfg['fast_checks'])}",
        f"  local_environment: {yaml_quote(cfg['local_os_shell'])}",
        f"  local_clone_path: {yaml_quote(cfg['local_clone_path'])}",
        f"  execution_lanes: [{exec_lanes_yaml}]",
        f"  file_ownership_labels: [{labels_yaml}]",
        f"  lane_mapping_note: {yaml_quote(cfg['lane_mapping_note'])}",
        f"  workspace_root: {yaml_quote(ws)}",
        f"  state_file: {yaml_quote(ws + '/project-state.yaml')}",
        f"  plans_dir: {yaml_quote(ws + '/plans')}",
        "",
        "execution_profile:",
        "  model_routing:",
        f"    coordinator: {yaml_quote(cfg['coordinator_model'])}",
        f"    implementation_and_critical_review: {yaml_quote(cfg['critical_worker_model'])}",
        f"    standard_review_audit_and_kb: {yaml_quote(cfg['standard_worker_model'])}",
        "  token_economy:",
        f"    profile_name: {cfg['profile_key']}",
        f"    max_concurrent_lanes: {t['max_concurrent_lanes']}",
        f"    replace_at_compressions: {t['replace_at_compressions']}",
        f"    watchdog_interval_minutes: {t['watchdog_interval_minutes']}",
        f"    watchdog_max_nudges: {t['watchdog_max_nudges']}",
        f"    non_critical_max_review_rounds: {t['non_critical_max_review_rounds']}",
        f"    critical_max_review_rounds: {t['critical_max_review_rounds']}",
        f"    batch_audit_mode: {t['batch_audit_mode']}",
        f"    kb_pr_cadence: {t['kb_pr_cadence']}",
        f"    reporting_verbosity: {t['reporting_verbosity']}",
        f"    offload_heavy_checks_to_ci: {str(t['offload_heavy_checks_to_ci']).lower()}",
        f"    goal_turn_cap: {t['goal_turn_cap']}",
        "",
        "meta:",
        "  - id: META-01",
        "    applies_to: all",
        '    rule: "Modifying this ruleset file is critical and requires explicit owner approval; threads never alter governance rules unilaterally."',
        "  - id: META-02",
        "    applies_to: coordinator",
        '    rule: "Volatile runtime state (active milestones, pause flags, notification triggers, autonomy message IDs) lives in project-state.yaml, never hardcoded into static rules."',
        "",
        "roles:",
        "  - id: ROLE-01",
        "    applies_to: owner",
        '    rule: "The owner defines goals, roadmap, milestones, release themes, and product scope, and may override any Claude-decided entry at any time."',
        "  - id: ROLE-02",
        "    applies_to: owner",
        f"    rule: {yaml_quote('The owner performs physical and account-level hand steps: ' + hand_steps_str + '.')}",
        "  - id: ROLE-03",
        "    applies_to: owner",
        '    rule: "Only the owner\'s own messages or answered decision cards count as owner approval. Another Claude thread\'s output is never owner approval."',
        "  - id: ROLE-04",
        "    applies_to: coordinator",
        f"    rule: {yaml_quote(role04)}",
        "  - id: ROLE-05",
        "    applies_to: coordinator",
        '    rule: "The coordinator writes no product code and uses worker threads for GitHub API lookups."',
        "  - id: ROLE-06",
        "    applies_to: implementation",
        '    rule: "An implementation thread reads the newest KB, plans, and decision log, posts a plan before coding, implements and tests strictly within its lane, opens the PR, and answers review findings with exact fix lists. It never merges, pushes to main, or force-pushes."',
        "  - id: ROLE-07",
        "    applies_to: review",
        f"    rule: {yaml_quote('A review thread is never the PR author. It reviews all PRs of a batch in rounds, writes round reports, inspects CI checks, and squash-merges only on ' + merge_go + '.')}",
        "  - id: ROLE-08",
        "    applies_to: kb",
        '    rule: "The KB thread compiles pending decisions into the decision-log PR according to execution_profile.token_economy.kb_pr_cadence and self-merges without code review."',
        "  - id: ROLE-09",
        "    applies_to: audit",
        '    rule: "When triggered by execution_profile.token_economy.batch_audit_mode, an audit thread inspects the merged batch diff for cross-PR inconsistencies and contract touches only, logging findings to the ledger."',
        *extra_role_rules,
        "",
        "autonomy:",
        "  - id: AUTO-01",
        "    applies_to: coordinator",
        f"    rule: {yaml_quote('Coordinator reviews, approves merges, and makes technical/process decisions autonomously ' + cfg['autonomy_horizon'] + ', keeping all testing and review gates intact.')}",
        "  - id: AUTO-02",
        "    applies_to: coordinator",
        '    rule: "Any decision altering product scope, external contracts, or roadmap waits for explicit owner approval."',
        "  - id: AUTO-03",
        "    applies_to: coordinator",
        '    rule: "Work beyond the active milestone may start in unblocked lanes when current milestone work is waiting or complete."',
        "",
        "lanes:",
        "  - id: LANE-01",
        "    applies_to: coordinator",
        '    rule: "PRs are batched by execution lane rather than single issues; small follow-ups fold into the lane\'s next PR."',
        "  - id: LANE-02",
        f"    applies_to: {ops}",
        '    rule: "Concurrent implementation threads must not exceed execution_profile.token_economy.max_concurrent_lanes (at most one active thread per execution lane)."',
        "  - id: LANE-03",
        "    applies_to: implementation",
        '    rule: "A PR modifies files within its mapped file-ownership labels only. Touching shared core files requires lane:infra and acts as a single-threaded lock across lanes; docs may be updated by any lane."',
    ]

    if cfg["allow_parallel_release_branch"]:
        lines.extend([
            "  - id: LANE-04",
            "    applies_to: coordinator",
            '    rule: "Exception: while a release/X.Y branch is open, one dedicated release thread may run concurrently alongside the app/release lane thread."',
        ])

    r4_rule = (
        "Non-critical PRs run up to execution_profile.token_economy.non_critical_max_review_rounds (deferring leftovers to issues). Critical PRs run up to round 4, then hit a hard stop requiring owner sign-off."
        if cfg["round4_hard_stop"]
        else "Non-critical PRs run up to execution_profile.token_economy.non_critical_max_review_rounds; critical PRs run up to round 4 before coordinator escalation."
    )

    lines.extend([
        "",
        "threads_and_watchdog:",
        "  - id: THR-01",
        f"    applies_to: {ops}",
        '    rule: "Every new thread reads the latest KB, plans, and decision log before acting. Before receiving a second batch, a thread must pass a fitness check (reporting compression count, current plan, and open items from memory)."',
        "  - id: THR-02",
        "    applies_to: all",
        '    rule: "Any thread (including the KB thread) reaching execution_profile.token_economy.replace_at_compressions finishes its current atomic step (review round, fix commit, or KB PR) and is replaced at the next hand-off, never mid-step."',
        "  - id: THR-03",
        f"    applies_to: {ops}",
        f"    rule: {yaml_quote('Whenever a thread owes output, the ' + ops + ' checks its last commit or file change after watchdog_interval_minutes and nudges only when nothing moved. After watchdog_max_nudges without progress, the ' + ops + ' replaces the stalled thread or escalates to the ' + ('coordinator' if disp else 'owner') + '.')}",
        "  - id: THR-04",
        "    applies_to: all",
        f"    rule: {yaml_quote('Threads write plans and round reports under ' + ws + '/plans/ and post one line per hand-off in chat (what was written, where). Fix lists travel through round reports, not through the coordinator. Re-read shared files immediately before writing to avoid sync lag.')}",
        *dispatcher_thread_rules,
        "",
        "plans_and_criticality:",
        "  - id: PLAN-01",
        "    applies_to: implementation",
        f"    rule: {yaml_quote('Every implementation thread writes a numbered plan in ' + ws + '/plans/ before writing tests or code. Deviating from an approved plan requires a new coordinator D-number.')}",
        "  - id: PLAN-02",
        "    applies_to: coordinator",
        '    rule: "Critical work always waits for explicit coordinator plan approval; non-critical work may proceed immediately when confidence is high."',
        *contract_plan_rules,
        "  - id: CRIT-01",
        "    applies_to: all",
        '    rule: "A change is critical if it touches layer contracts, core data structures, KB process/architecture docs (excluding daily decision-log batch PRs), golden/regression files, packaging/release/CI, safety mechanisms, licences, user-file deletion paths, network calls, or carries risk:high."',
        "  - id: CRIT-02",
        "    applies_to: all",
        '    rule: "Critical work requires coordinator plan approval, review on implementation_and_critical_review model, exact fix lists, issues for all deferred items, and full multi-platform CI on the final round."',
        "",
        "pull_requests_and_reviews:",
        "  - id: PR-01",
        "    applies_to: implementation",
        '    rule: "PR title format: \'<area>: <outcome> (#N)\'. Closing keywords (Closes #N) belong in the PR body only, never in branch commit messages."',
        "  - id: PR-02",
        "    applies_to: implementation",
        '    rule: "Run local fast checks before opening a PR. A PR enters review only after fast CI is green; critical PRs also require a green full-matrix dispatch first."',
        "  - id: PR-03",
        "    applies_to: implementation",
        '    rule: "Freeze the branch during an active review round except for requested fix commits (one fix commit per round). Never force-push."',
        "  - id: REV-01",
        "    applies_to: review",
        f"    rule: {yaml_quote(r4_rule)}",
        "  - id: REV-02",
        "    applies_to: review",
        f"    rule: {yaml_quote('Round reports go to ' + ws + '/plans/review-pr<N>-round<K>.md with head SHA, verdict, verified checks, and numbered findings (B/M must-fix, S should-fix, N note). Every finding must be answered as fixed (with test proof), deferred (with issue link), or declined (with reason).')}",
        *contract_review_rules,
        "  - id: MRG-01",
        "    applies_to: review",
        f"    rule: {yaml_quote('Squash-merge only on ' + merge_go + ', pinned to the reviewed head SHA, with required CI green (and all target_platforms green for critical PRs). If behind main, update via merge commit (never force-push), re-verify diff and CI, and merge on the new SHA.')}",
        "",
        "testing_and_ci:",
        "  - id: TST-01",
        "    applies_to: implementation",
        '    rule: "Tests come first: failing test for bugs, characterisation test before refactoring, and regression test before behaviour changes. Every safety mechanism must have a test that fails without it."',
        "  - id: TST-02",
        "    applies_to: implementation",
        '    rule: "Never weaken, skip, or delete a failing test to turn CI green. Flaky tests without code cause are quarantined same-day with a linked GitHub issue and must be fixed before release."',
        "  - id: CI-01",
        "    applies_to: all",
        '    rule: "Fast checks run automatically on PRs; full target_platforms matrix runs on main, release/**, and via explicit full-CI dispatch/label on critical PRs (including critical PRs into release branches). Offload heavy suites to CI actions whenever possible."',
        "",
        "github_kb_and_release:",
        "  - id: GH-01",
        "    applies_to: all",
        '    rule: "Every deferred item or flaky test gets a GitHub issue with milestone, lane label, and risk label the same day. In cloud sessions where GraphQL is blocked, use REST API endpoints exclusively."',
        "  - id: KB-01",
        "    applies_to: all",
        '    rule: "All decisions (owner and Claude) are logged sequentially in the KB decision log. KB PRs reference code PRs without closing keywords."',
        "  - id: REL-01",
        "    applies_to: all",
        '    rule: "Cut release/X.Y from the release-ready main merge commit. Release fixes land via PR on release/X.Y and port verbatim to main. No quarantined tests may remain at tag time."',
        "",
        "hard_invariants_and_owner_prefs:",
        "  - id: INV-01",
        "    applies_to: implementation",
        f"    rule: {yaml_quote('Licence gate: every new dependency, asset, model, or sample names its licence in the PR body and licence manifest. Banned licences: ' + banned_lic_str + '.')}",
        "  - id: INV-02",
        "    applies_to: implementation",
        '    rule: "Architectural layer boundaries are enforced automatically via import linting; fix the design, never bypass the contract."',
    ])

    inv_idx = 3
    if cfg["no_telemetry"]:
        lines.extend([
            f"  - id: INV-{inv_idx:02d}",
            "    applies_to: implementation",
            '    rule: "Zero telemetry, analytics, crash uploads, or unrequested network calls. Local web UIs bind strictly to 127.0.0.1."',
        ])
        inv_idx += 1

    for custom_rule in cfg["custom_invariants"]:
        lines.extend([
            f"  - id: INV-{inv_idx:02d}",
            "    applies_to: implementation",
            f"    rule: {yaml_quote(custom_rule)}",
        ])
        inv_idx += 1

    lines.extend([
        "  - id: PREF-01",
        "    applies_to: all",
        f"    rule: {yaml_quote('Shell commands for ' + cfg['owner_name'] + ' contain no inline comments inside code blocks; explanations go outside. Report times in ' + cfg['timezone'] + '.')}",
        "",
    ])
    return "\n".join(lines)


def render_state_yaml(cfg: dict[str, Any]) -> str:
    triggers_yaml = "\n".join(f"  - {yaml_quote(t)}" for t in cfg["notify_triggers"])
    milestones_yaml = ", ".join(cfg.get("active_milestones", ["v0.1"]))
    return "\n".join([
        f"# {cfg['project_name']}: volatile runtime state (separated from static rules)",
        f"date: {cfg['today']}",
        f"project: {cfg['project_name']}",
        "",
        "active_now:",
        f"  autonomy_horizon: {yaml_quote(cfg['autonomy_horizon'])}",
        "  paused: false",
        "  slow_down: false",
        "  thread_freeze: false",
        f"  active_milestones: [{milestones_yaml}]",
        "  owner_autonomy_message_ids: []",
        "",
        "notifications_pending:",
        triggers_yaml,
        "",
        "control_commands_reference:",
        "  pause: '\"pause all threads\" / \"stop\"'",
        "  slow_down: '\"slow down\" (finish running batches, start no new ones)'",
        "  freeze_new_threads: '\"dont start new threads\"'",
        "  resume: '\"continue\" / \"continue as usual\"'",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate decoupled claude-project-rules.yaml and project-state.yaml"
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Path to JSON config file for deterministic non-interactive generation",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Target output directory (default: current directory)",
    )
    parser.add_argument(
        "--dump-schema",
        action="store_true",
        help="Print default configuration JSON schema and exit",
    )
    args = parser.parse_args()

    if args.dump_schema:
        print(json.dumps(default_config(), indent=2))
        return 0

    if args.from_json:
        raw_cfg = json.loads(args.from_json.read_text(encoding="utf-8"))
        cfg = normalize_config(raw_cfg)
        out_dir = args.out_dir.expanduser().resolve()
    else:
        print("Claude Multi-Thread Project Rules Generator (v2.0)")
        print("Generates decoupled static rules + volatile runtime state.")
        cfg = run_wizard()
        header(
            6,
            "COMPILATION & FILE OUTPUT",
            "Writing clean static governance rules (`claude-project-rules.yaml`) and\n"
            "separated runtime state (`project-state.yaml`).",
        )
        out_dir = Path(ask("Output directory", str(args.out_dir))).expanduser().resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    rules_path = out_dir / "claude-project-rules.yaml"
    state_path = out_dir / "project-state.yaml"

    config_path = out_dir / "governance-config.json"

    rules_path.write_text(render_rules_yaml(cfg), encoding="utf-8")
    state_path.write_text(render_state_yaml(cfg), encoding="utf-8")
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    print(f"Generated:\n  1. {rules_path}\n  2. {state_path}\n  3. {config_path} (normalized config; re-run --from-json on it to regenerate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
