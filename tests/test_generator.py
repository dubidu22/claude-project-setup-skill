"""generate_project_rules.py: type checks, quoting, self-check, options, versioning, migration."""
from __future__ import annotations

import json
import re

import pytest
import yaml

from conftest import SCRIPTS, errors, findings, run


# ---- the default path ------------------------------------------------------

def test_default_generation_is_clean(w):
    r = w.generate()
    assert r.returncode == 0, r.stderr
    a = w.audit("--json", "--strict")
    assert a.returncode == 0 and findings(a) == [], a.stdout
    data = yaml.safe_load(w.rules_text())
    assert data["project"] == "demo" and data["version"] == "2.0.0" and str(data["date"]) == "2026-03-04"
    assert yaml.safe_load(w.state.read_text())["active_now"]["paused"] is False


@pytest.mark.parametrize("sets", [
    ("workspace_root=./governance",),
    ("model_preset=economy", "profile_key=frugal", "workspace_root=./governance"),
    ("acceptance_contracts=false", "dispatcher=false", "workspace_root=./gov", "coordinator_compact_every_batches=0"),
    ("stack_key=fullstack_web",),
    ("stack_key=custom", "profile_key=max_velocity"),
    ("token_cfg.critical_max_review_rounds=3",),
    ('custom_invariants=["One holds.","Two holds.","Three holds.","Four holds."]',),
])
def test_variants_pass_their_own_audit(w, sets):
    assert w.generate(None, *sets).returncode == 0
    a = w.audit("--json", "--strict")
    assert a.returncode == 0, a.stdout


# ---- B1 / B8: types --------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "dispatcher=False", "dispatcher=off", "dispatcher=no", "dispatcher=0", "acceptance_contracts=False",
    "escalate_after_round=two", "token_cfg.max_concurrent_lanes=many", "token_cfg.max_concurrent_lanes=0",
    "token_cfg.replace_after_prs=0", "cache_ttl_minutes=1.5", "ownership_labels=lane:app",
    'ownership_labels=["Lane App"]', "execution_lanes=[]", "profile_key=cheap", "model_preset=free",
    "stack_key=rust", "environment=desktop", "nonsense=1", "token_cfg.nonsense=1", "today=2026-01-01",
    "token_cfg.non_critical_max_review_rounds=9",
])
def test_bad_values_are_refused_and_nothing_is_written(w, bad):
    assert w.generate().returncode == 0
    before = {p: p.read_bytes() for p in w.ws.rglob("*") if p.is_file()}
    r = w.generate(None, bad)
    assert r.returncode == 2, (bad, r.stdout, r.stderr)
    assert "Traceback" not in r.stderr
    assert {p: p.read_bytes() for p in w.ws.rglob("*") if p.is_file()} == before


def test_bad_values_in_the_json_are_refused_too(w):
    r = w.generate({"project_name": "demo", "dispatcher": "False", "escalate_after_round": "two",
                    "token_cfg": {"max_concurrent_lanes": "many"}})
    assert r.returncode == 2 and not w.rules.exists()
    for needle in ("dispatcher must be true or false", "escalate_after_round must be a whole number",
                   "token_cfg.max_concurrent_lanes must be a whole number"):
        assert needle in r.stderr


def test_boolean_off_really_turns_the_feature_off(w):
    assert w.generate(None, "dispatcher=false", "acceptance_contracts=false").returncode == 0
    text = w.rules_text()
    assert "applies_to: dispatcher" not in text and "applies_to: specify" not in text
    assert json.loads(w.config.read_text())["dispatcher"] is False
    assert not (w.ws / "rules" / "dispatcher.yaml").exists()


def test_extract_of_a_removed_role_is_deleted(w):
    w.generate()
    assert (w.ws / "rules" / "dispatcher.yaml").exists()
    r = w.generate(None, "dispatcher=false")
    assert not (w.ws / "rules" / "dispatcher.yaml").exists() and "dispatcher.yaml" in r.stdout


# ---- B2: quoting and the self-check ----------------------------------------

NASTY = 'Shop: Phase #2 "beta" \\ [x] {y} - yes'


def test_awkward_text_survives_everywhere(w):
    cfg = {
        "project_name": NASTY, "owner_name": "A: B #c", "timezone": "Europe/Berlin",
        "active_milestones": ["v0.1: alpha #1", "no"], "notify_triggers": ["done: yes #1"],
        "execution_lanes": ["a: b", "c #d", "e"], "fast_checks": "ruff: check # all",
        "custom_invariants": ['Never write "x: y" # here'], "owner_prefs": ["Use: colons # freely."],
        "lane_mapping_note": "a: b # c", "autonomy_horizon": "until: v1 #x",
    }
    assert w.generate(cfg).returncode == 0
    rules = yaml.safe_load(w.rules_text())
    state = yaml.safe_load(w.state.read_text())
    assert rules["project"] == NASTY and state["project"] == NASTY
    assert state["active_now"]["active_milestones"] == ["v0.1: alpha #1", "no"]
    assert rules["project_profile"]["execution_lanes"] == ["a: b", "c #d", "e"]
    assert state["notifications_pending"] == ["done: yes #1"]
    assert any('Never write "x: y" # here' == r["rule"] for r in rules["hard_invariants_and_owner_prefs"])
    for extract in (w.ws / "rules").glob("*.yaml"):
        assert yaml.safe_load(extract.read_text())["project"] == NASTY
    assert findings(w.audit("--json", "--strict")) == []
    # and without PyYAML the audit reads the same rules
    a = w.audit("--json", no_yaml=True)
    assert a.returncode == 0 and json.loads(a.stdout)["rules"] == len(w.rule_ids())


def test_newlines_in_values_cannot_break_the_file(w):
    assert w.generate({"project_name": "two\nlines", "custom_invariants": ["a\nb: c"]}).returncode == 0
    assert yaml.safe_load(w.rules_text())["project"] == "two\nlines"


def test_output_is_parsed_before_it_is_saved(w, monkeypatch):
    import generate_project_rules as gen

    cfg = gen.normalize_config({"project_name": "demo"})
    good = gen.render_rules_yaml(cfg)
    state = gen.render_state_yaml(cfg)
    assert gen.check_output(good, state, gen.role_extracts(good), cfg) is None
    broken = good.replace('project: "demo"', "project: demo: x")
    assert "does not parse" in gen.check_output(broken, state, {}, cfg)
    fewer = good.replace('    rule: "Tests come first', '    text: "Tests come first')
    assert gen.check_output(fewer, state, {}, cfg) is not None


# ---- B3 / B4: the hard stop --------------------------------------------------

def test_round4_stop_cannot_be_turned_off(w):
    w.generate()
    r = w.generate(None, "round4_hard_stop=false")
    assert r.returncode == 2 and "can no longer be turned off" in r.stderr
    assert "hard stop requiring owner sign-off" in w.rule("REV-01")
    r = w.generate({"project_name": "demo", "round4_hard_stop": False})
    assert r.returncode == 2
    assert w.generate({"project_name": "demo", "round4_hard_stop": True}).returncode == 0


def test_stop_round_follows_the_config(w):
    assert w.generate(None, "token_cfg.critical_max_review_rounds=3", "workspace_root=./g").returncode == 0
    assert "up to round 3, then hit a hard stop" in w.rule("REV-01")
    w.scaffold()
    assert "reaches review round 3 (hard stop" in (w.ws / "project_instructions.md").read_text()
    assert errors(w.audit("--json")) == []


# ---- B5: rules follow the labels and the stack -----------------------------

def test_lane_rule_follows_the_labels(w):
    r = w.generate(None, 'ownership_labels=["lane:app","lane:docs"]', "lane_mapping_note=app owns everything; docs may be edited by any lane.")
    assert r.returncode == 0
    lane03 = w.rule("LANE-03")
    assert "lane:infra" not in lane03 and "one PR at a time" in lane03 and "Docs may be updated" in lane03
    a = w.audit("--json", "--strict")
    assert a.returncode == 0, a.stdout
    assert "app/release lane" not in w.rules_text()


def test_layer_boundary_rule_only_where_a_check_exists(w):
    w.generate(None, "stack_key=fullstack_web")
    assert "layer boundaries" not in w.rules_text()
    w.generate(None, "stack_key=python_cli_or_service")
    assert "import linting" in w.rules_text()
    w.generate(None, "layer_boundary_check=dependency-cruiser")
    assert "enforced automatically (dependency-cruiser)" in w.rules_text()


# ---- B6: date, version, decision-log entry ----------------------------------

def test_date_and_version_move_on_regeneration(w):
    w.generate(env={"GOVERNANCE_TODAY": "2026-01-01"})
    assert "today" not in json.loads(w.config.read_text())
    r = w.generate(None, "model_preset=economy", env={"GOVERNANCE_TODAY": "2026-02-02"})
    data = yaml.safe_load(w.rules_text())
    assert str(data["date"]) == "2026-02-02" and data["version"] == "2.1.0"
    assert "Decision-log entry" in r.stdout and "2.0.0 -> 2.1.0" in r.stdout
    assert json.loads(w.config.read_text())["ruleset_version"] == "2.1.0"
    # an identical regeneration keeps the version and prints no decision-log entry
    r = w.generate(env={"GOVERNANCE_TODAY": "2026-02-03"})
    data = yaml.safe_load(w.rules_text())
    assert data["version"] == "2.1.0" and str(data["date"]) == "2026-02-03"
    assert "nothing: the ruleset is identical" in r.stdout and "Decision-log entry" not in r.stdout
    for extract in (w.ws / "rules").glob("*.yaml"):
        e = yaml.safe_load(extract.read_text())
        assert e["version"] == "2.1.0" and str(e["date"]) == "2026-02-03"


def test_a_stored_today_from_an_old_config_is_ignored(w):
    r = w.generate({"project_name": "demo", "today": "2020-01-01", "round4_hard_stop": True,
                    "coordinator_compact_at_tokens": 50000, "workspace_root": "./g"})
    assert r.returncode == 0, r.stderr
    assert str(yaml.safe_load(w.rules_text())["date"]) == "2026-03-04"
    cfg = json.loads(w.config.read_text())
    assert "today" not in cfg and "round4_hard_stop" not in cfg and cfg["coordinator_compact_every_batches"] == 1
    assert "became options" in r.stderr  # the owner is told which former habits are now off


# ---- B7: changing the stack --------------------------------------------------

def test_stack_change_resets_what_depends_on_it_and_shows_it(w):
    w.generate()
    r = w.generate(None, "stack_key=fullstack_web", extra=("--dry-run",))
    assert "setting execution_lanes" in r.stdout and "backend_api" in r.stdout and "setting fast_checks" in r.stdout
    assert "core_pipeline" in w.rules_text()  # dry run wrote nothing
    w.generate(None, "stack_key=fullstack_web")
    prof = yaml.safe_load(w.rules_text())["project_profile"]
    assert prof["stack_preset"] == "fullstack_web" and prof["execution_lanes"][0] == "backend_api"
    assert "lane:frontend" in prof["file_ownership_labels"] and "typecheck" in prof["fast_checks"]
    # a value set in the same call wins
    w.generate(None, "stack_key=python_cli_or_service", 'execution_lanes=["one","two"]')
    assert yaml.safe_load(w.rules_text())["project_profile"]["execution_lanes"] == ["one", "two"]


# ---- settings changes --------------------------------------------------------

def test_dry_run_writes_nothing_and_state_is_kept(w):
    w.generate()
    w.state.write_text(w.state.read_text().replace("slow_down: false", "slow_down: true"))
    before = w.rules.read_bytes()
    r = w.generate(None, "model_preset=economy", extra=("--dry-run",))
    assert r.returncode == 0 and "Dry run, nothing written." in r.stdout and w.rules.read_bytes() == before
    assert "setting implementation" in r.stdout
    w.generate(None, "model_preset=economy")
    assert "slow_down: true" in w.state.read_text()
    assert yaml.safe_load(w.rules_text())["execution_profile"]["model_routing"]["implementation"].startswith("Sonnet")


def test_preset_and_profile_replace_stored_values_but_same_call_wins(w):
    w.generate(None, "implementation_model=Haiku", "token_cfg.max_concurrent_lanes=1")
    w.generate(None, "model_preset=economy", "profile_key=frugal", "token_cfg.watchdog_interval_minutes=45")
    tok = yaml.safe_load(w.rules_text())["execution_profile"]["token_economy"]
    assert tok["max_concurrent_lanes"] == 2 and tok["watchdog_interval_minutes"] == 45 and tok["replace_after_prs"] == 2
    assert json.loads(w.config.read_text())["implementation_model"].startswith("Sonnet")


def test_text_values_are_taken_literally(w):
    w.generate(None, "project_name=123", "owner_name=true", 'timezone="Europe/Berlin"')
    data = yaml.safe_load(w.rules_text())
    assert data["project"] == "123" and data["owner"].startswith("true (GitHub") and data["time_zone_owner"] == "Europe/Berlin"


# ---- D3 / D4 / D5 / D6 in the generated rules --------------------------------

def test_authority_puts_the_owner_first_and_lists_ruleset_and_contracts(w):
    w.generate()
    order = yaml.safe_load(w.rules_text())["authority"]
    assert order[:4] == ["owner_messages", "this_ruleset", "approved_acceptance_contracts", "kb_decision_log"]
    assert "newest message on a point outranks older decision-log entries" in w.rule("ROLE-01")
    assert "quotes the owner's message" in w.rule("KB-01")
    w.generate(None, "acceptance_contracts=false")
    assert "approved_acceptance_contracts" not in yaml.safe_load(w.rules_text())["authority"]


def test_criticality_merge_go_and_escalation_rules(w):
    w.generate(None, "model_preset=economy", "profile_key=frugal")
    assert "no open B/M finding" in w.rule("MRG-01")
    assert "record critical: yes or no" in w.rule("CRIT-03")
    assert "confirmed non-critical" in w.rule("ROLE-11") and "no open must-fix finding" in w.rule("ROLE-11")
    rev01, rev04 = w.rule("REV-01"), w.rule("REV-04")
    assert "must-fix findings never (REV-04 applies)" in rev01
    assert "after review round 1" in rev04 and "comes before the round cap in REV-01" in rev04
    assert "2 more rounds" in rev04 and "stop the PR for the coordinator" in rev04
    assert yaml.safe_load(w.rules_text())["execution_profile"]["token_economy"]["rounds_after_escalation"] == 2
    # same model for routine and critical work: no escalation rule, and REV-01 says where must-fix findings go
    w.generate(None, "implementation_model=Opus (high effort)")
    assert "REV-04" not in w.rule_ids() and "they stop the PR for the coordinator" in w.rule("REV-01")


def test_environment_decides_branch_and_compaction_rules(w):
    w.generate()  # /mnt/project-files
    assert yaml.safe_load(w.rules_text())["project_profile"]["environment"] == "claude_ai_project"
    assert "THR-11" not in w.rule_ids() and "THR-13" not in w.rule_ids() and "/compact" not in w.rules_text()
    w.generate(None, "workspace_root=./governance")
    prof = yaml.safe_load(w.rules_text())["project_profile"]
    assert prof["environment"] == "claude_code" and prof["governance_branch"] == "governance"
    assert "committed on branch governance" in w.rule("THR-13") and "pull request only" in w.rule("THR-13")
    assert "/compact" in w.rule("THR-11") and "tokens" not in w.rule("THR-11")
    w.generate(None, "coordinator_compact_every_batches=0")
    assert "THR-11" not in w.rule_ids()


def test_rules_rest_on_what_files_show(w):
    w.generate()
    assert "replace_after_prs" in w.rule("THR-02") and "counted from its ledger entries" in w.rule("THR-02")
    assert "take the time from a tool" in w.rule("THR-03") and "scheduled task" in w.rule("THR-03")
    assert "starter block" in w.rule("THR-10") and "ask the owner to open the chat" in w.rule("THR-10")
    assert "Every file has one writer" in w.rule("THR-04")
    assert "tells the coordinator" in w.rule("ROLE-12") and "project-state.yaml" not in w.rule("ROLE-12")
    assert "writes none" in w.rule("ROLE-11")


def test_origin_project_habits_are_options(w):
    w.generate()
    text = w.rules_text()
    for habit in ("inline comments", "GraphQL", "127.0.0.1", "golden", "deletion paths"):
        assert habit not in text
    assert w.rule("PREF-01") == "Report times to Project Owner in UTC."
    w.generate(None, 'owner_prefs=["Shell commands contain no inline comments."]', "github_rest_only=true",
               "local_ui_loopback_only=true", 'critical_areas=["golden/regression files","user-file deletion paths"]')
    text = w.rules_text()
    for habit in ("inline comments", "GraphQL", "127.0.0.1", "golden/regression files", "deletion paths"):
        assert habit in text


def test_no_rule_is_overlong_and_no_role_is_overloaded(w):
    w.generate(None, "workspace_root=./governance", "model_preset=economy")
    a = w.audit("--json")
    assert [f for f in findings(a) if f["code"] == "A08"] == []


# ---- per-role extracts --------------------------------------------------------

def test_extracts_hold_exactly_the_rules_that_bind_the_role(w):
    w.generate(None, "workspace_root=./governance")
    full = yaml.safe_load(w.rules_text())
    all_rules = {r["id"]: r for sec in full.values() if isinstance(sec, list) for r in sec if isinstance(r, dict) and "id" in r}
    roles = {r["applies_to"] for r in all_rules.values()} - {"all", "owner"}
    assert {p.stem for p in (w.ws / "rules").glob("*.yaml")} == roles
    for role in roles:
        e = yaml.safe_load((w.ws / "rules" / f"{role}.yaml").read_text())
        want = {rid for rid, r in all_rules.items() if r["applies_to"] in (role, "all")}
        assert {r["id"] for r in e["rules"]} == want
        assert all(all_rules[r["id"]]["rule"] == r["rule"] for r in e["rules"])
        assert e["extract_for"] == role and e["execution_profile"] == full["execution_profile"]
    kb = (w.ws / "rules" / "kb.yaml").read_text()
    assert len(kb) < len(w.rules_text()) / 2


# ---- migration ----------------------------------------------------------------

OLD_RULESET = '''version: 1.4.0
date: 2025-06-01
project: oldproj
repository: someone/oldproj
public_repo: false
owner: "Sam Lee (GitHub slee)"
time_zone_owner: "Europe/Vienna"
authority:
  - project_instructions
  - kb_decision_log
  - owner_messages
project_profile:
  stack_preset: python_cli_or_service
  target_platforms: [ubuntu-latest]
  fast_checks: "ruff, pytest"
  local_environment: "Linux bash"
  local_clone_path: "~/src/oldproj"
  execution_lanes: [core, app]
  file_ownership_labels: [lane:core, lane:app, lane:infra, lane:docs]
  lane_mapping_note: "core owns core; app owns app. core requires lane:infra."
  workspace_root: "./governance"
execution_profile:
  model_routing:
    coordinator: "Fable 5.1"
    implementation_and_critical_review: "Opus 5.5 high"
    standard_review_audit_and_kb: "Opus 5.5 medium"
  token_economy:
    profile_name: frugal
    max_concurrent_lanes: 2
    replace_at_compressions: 1
    watchdog_interval_minutes: 90
    non_critical_max_review_rounds: 1
    critical_max_review_rounds: 4
roles:
  - id: ROLE-02
    applies_to: owner
    rule: "The owner performs physical and account-level hand steps: publishing to PyPI; creating milestones."
autonomy:
  - id: AUTO-01
    applies_to: coordinator
    rule: "Coordinator reviews, approves merges, and makes technical/process decisions autonomously per milestone, keeping all testing and review gates intact."
plans_and_criticality:
  - id: CRIT-01
    applies_to: all
    rule: "A change is critical if it touches layer contracts, golden/regression files, licences, or carries risk:high."
pull_requests_and_reviews:
  - id: REV-01
    applies_to: review
    rule: "Critical PRs run up to round 4 before coordinator escalation."
  - id: XTRA-01
    applies_to: review
    rule: "Every review mentions the weather."
github_kb_and_release:
  - id: GH-01
    applies_to: all
    rule: "Issues same day. In cloud sessions where GraphQL is blocked, use REST API endpoints exclusively."
hard_invariants_and_owner_prefs:
  - id: INV-01
    applies_to: implementation
    rule: "Licence gate: every new dependency names its licence. Banned licences: GPL, unclear."
  - id: INV-02
    applies_to: implementation
    rule: "Architectural layer boundaries are enforced automatically via import linting; fix the design, never bypass the contract."
  - id: INV-03
    applies_to: implementation
    rule: "Zero telemetry, analytics, crash uploads, or unrequested network calls. Local web UIs bind strictly to 127.0.0.1."
  - id: INV-04
    applies_to: implementation
    rule: "The schema stays backwards compatible across minor versions."
  - id: PREF-01
    applies_to: all
    rule: "Shell commands for Sam Lee contain no inline comments inside code blocks; explanations go outside. Report times in Europe/Vienna."
'''
OLD_STATE = '''project: oldproj
active_now:
  paused: true
  active_milestones: [v0.3]
notifications_pending:
  - "first import works"
'''


@pytest.mark.parametrize("no_yaml", [False, True])
def test_migration_derives_a_config_and_keeps_live_files(w, no_yaml):
    w.ws.mkdir()
    w.rules.write_text(OLD_RULESET)
    w.state.write_text(OLD_STATE)
    (w.ws / "kb").mkdir()
    (w.ws / "kb" / "decision-log.md").write_text("## D-041 (2025-06-01, owner)\nold entry\n")
    out = w.tmp / "derived.json"
    r = run("generate_project_rules.py", "--derive-config", w.rules, "--state", w.state, "--out", out, no_yaml=no_yaml)
    assert r.returncode == 0, r.stderr
    assert w.rules.read_text() == OLD_RULESET  # derive writes only --out
    cfg = json.loads(out.read_text())
    assert cfg["project_name"] == "oldproj" and cfg["owner_name"] == "Sam Lee" and cfg["owner_gh"] == "slee"
    assert cfg["critical_model"] == "Opus 5.5 high" and cfg["review_model"] == "Opus 5.5 medium"
    assert cfg["token_cfg"]["watchdog_interval_minutes"] == 90 and cfg["profile_key"] == "frugal"
    assert cfg["owner_hand_steps"] == ["publishing to PyPI", "creating milestones"]
    assert cfg["autonomy_horizon"] == "per milestone" and cfg["banned_licences"] == ["GPL", "unclear"]
    assert cfg["custom_invariants"] == ["The schema stays backwards compatible across minor versions."]
    assert cfg["github_rest_only"] and cfg["local_ui_loopback_only"] and cfg["layer_boundary_check"] == "import linting"
    assert "golden/regression files" in cfg["critical_areas"] and cfg["owner_prefs"]
    assert cfg["dispatcher"] is False and cfg["acceptance_contracts"] is False
    assert cfg["notify_triggers"] == ["first import works"] and cfg["active_milestones"] == ["v0.3"]
    assert cfg["ruleset_version"] == "1.4.0"
    assert "XTRA-01" in r.stderr and "would be dropped" in r.stderr and "no hard stop" in r.stderr

    preview = run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws, "--dry-run")
    assert preview.returncode == 0 and "rules removed: XTRA-01" in preview.stdout and w.rules.read_text() == OLD_RULESET
    assert run("generate_project_rules.py", "--from-json", out, "--out-dir", w.ws).returncode == 0
    assert w.state.read_text() == OLD_STATE
    assert "D-041" in (w.ws / "kb" / "decision-log.md").read_text()
    data = yaml.safe_load(w.rules_text())
    assert data["version"] == "1.5.0"
    assert "hard stop requiring owner sign-off" in w.rule("REV-01")
    assert errors(w.audit("--json")) == []
    assert w.scaffold("--refresh").returncode == 0
    assert "D-041" in (w.ws / "kb" / "decision-log.md").read_text() and "D-001" not in (w.ws / "kb" / "decision-log.md").read_text()


def test_dump_schema_has_no_stored_date_and_validates(w):
    r = run("generate_project_rules.py", "--dump-schema")
    schema = json.loads(r.stdout)
    assert "today" not in schema and "round4_hard_stop" not in schema and "description" not in schema["token_cfg"]
    assert w.generate(schema).returncode == 0


def test_wizard_rejects_non_numbers_instead_of_crashing(tmp_path):
    import subprocess, sys
    answers = "\n" * 9 + "\n\ncustom\n" + "\n" * 6 + "abc\n2\n" + "\n" * 40
    r = subprocess.run([sys.executable, str(SCRIPTS / "generate_project_rules.py"), "--out-dir", str(tmp_path / "o")],
                       input=answers, capture_output=True, text=True)
    assert "Traceback" not in r.stderr
