#!/usr/bin/env python3
"""
Scaffold the shared workspace that the generated ruleset refers to.

Reads the normalized config (`governance-config.json`, written next to the YAML
files by generate_project_rules.py) and renders the templates in
`../assets/templates/` into the target directory:

    <out-dir>/
      project_instructions.md     starter block for the Coordinator chat
      plans/README.md
      kb/README.md
      kb/decision-log.md          with D-001 recording adoption of the ruleset
      ledger/implementation.md
      ledger/review.md
      .github/lanes.yml           label definitions (optional, --github)

Usage:
    python3 scaffold_workspace.py --from-json governance-config.json --out-dir <dir> [--github] [--force]

Existing files are left alone unless --force is given, so re-running on a live
workspace never clobbers plans or ledgers. Placeholders in templates look like
`{{project_name}}`; any config key (plus `execution_lanes`/`ownership_labels`
joined with commas) can be used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"

LABEL_COLOURS = {
    "lane:core": "B60205",
    "lane:infra": "D93F0B",
    "lane:docs": "0E8A16",
}
RISK_LABELS = [
    ("risk:high", "B60205", "Critical change: plan approval, strong-model review, full CI matrix"),
    ("risk:low", "C2E0C6", "Routine change within lane ownership"),
    ("full-ci", "1D76DB", "Dispatch the full target_platforms matrix on this PR"),
    ("deferred", "FBCA04", "Review finding deferred from a PR round"),
    ("flaky-test", "E99695", "Quarantined test; fix before release"),
]


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise SystemExit("config must be a JSON object")
    return cfg


def render(text: str, cfg: dict[str, Any]) -> str:
    values: dict[str, str] = {}
    for k, v in cfg.items():
        if isinstance(v, list):
            values[k] = ", ".join(str(x) for x in v)
        elif isinstance(v, dict):
            for sk, sv in v.items():
                values[f"{k}.{sk}"] = str(sv)
        else:
            values[k] = str(v)
    missing: set[str] = set()

    def sub(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key in values:
            return values[key]
        missing.add(key)
        return m.group(0)

    out = re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub, text)
    if missing:
        print(f"warning: unfilled placeholders: {', '.join(sorted(missing))}", file=sys.stderr)
    return out


def lanes_yml(cfg: dict[str, Any]) -> str:
    lines = [
        f"# {cfg.get('project_name', 'project')}: GitHub labels for lane ownership and risk.",
        "# Apply with a label-sync action or `gh label create` for each entry.",
        "labels:",
    ]
    lanes = cfg.get("execution_lanes", [])
    for label in cfg.get("ownership_labels", []):
        colour = LABEL_COLOURS.get(label, "5319E7")
        if label == "lane:core":
            desc = "Shared core files: critical, requires lane:infra, single-thread lock"
        elif label == "lane:infra":
            desc = "Cross-cutting/infra changes; the lock for touching core"
        elif label == "lane:docs":
            desc = "Documentation; any lane may edit without lane:infra"
        else:
            desc = f"File ownership for the {label.split(':', 1)[-1]} area"
        lines.append(f"  - name: {label}")
        lines.append(f"    color: \"{colour}\"")
        lines.append(f"    description: \"{desc}\"")
    for name, colour, desc in RISK_LABELS:
        lines.append(f"  - name: {name}")
        lines.append(f"    color: \"{colour}\"")
        lines.append(f"    description: \"{desc}\"")
    lines.append("")
    lines.append("# Execution lanes (one concurrent implementation thread each):")
    for lane in lanes:
        lines.append(f"#   - {lane}")
    lines.append(f"# {cfg.get('lane_mapping_note', '')}")
    return "\n".join(lines) + "\n"


def write(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return f"kept     {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote    {path}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold the shared governance workspace from a config JSON")
    ap.add_argument("--from-json", type=Path, required=True, help="governance-config.json written by the generator")
    ap.add_argument("--out-dir", type=Path, default=Path("."), help="workspace directory to scaffold into")
    ap.add_argument("--github", action="store_true", help="also write .github/lanes.yml label definitions")
    ap.add_argument("--force", action="store_true", help="overwrite files that already exist")
    args = ap.parse_args()

    if not TEMPLATE_DIR.is_dir():
        print(f"error: template directory not found at {TEMPLATE_DIR}", file=sys.stderr)
        return 2
    cfg = load_config(args.from_json)
    cfg.setdefault("workspace_root", str(args.out_dir))
    out = args.out_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for tpl in sorted(TEMPLATE_DIR.rglob("*")):
        if not tpl.is_file():
            continue
        rel = tpl.relative_to(TEMPLATE_DIR)
        results.append(write(out / rel, render(tpl.read_text(encoding="utf-8"), cfg), args.force))
    if args.github:
        results.append(write(out / ".github" / "lanes.yml", lanes_yml(cfg), args.force))

    print("\n".join(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
