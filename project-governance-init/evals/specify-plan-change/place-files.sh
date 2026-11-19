#!/usr/bin/env bash
# Builds the fixture at test time from the skill's own scripts, so it can never go stale:
# static files (roadmap, contracts, live state, ledger entries) come from files/, everything the
# generator and the scaffold produce is produced now.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
scripts="$here/../../scripts"
cp -R "$here/files/." .
python3 "$scripts/generate_project_rules.py" --from-json governance/fixture-config.json --out-dir governance > /dev/null
python3 "$scripts/scaffold_workspace.py" --from-json governance/governance-config.json --out-dir governance > /dev/null
rm governance/fixture-config.json
