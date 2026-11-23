#!/usr/bin/env bash
# Builds the fixture: a rendered repository whose reviewer was given back its edit tools by hand.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
git init -q -b main . 2>/dev/null || true
mkdir -p .claude
echo '{"name": "tidyshelf", "checks": "pytest"}' > .claude/project-setup.json
python3 "$here/../../skills/project-setup/scripts/setup.py" render . > /dev/null
sed -i.bak '/^disallowedTools:/d' .claude/agents/reviewer.md && rm .claude/agents/reviewer.md.bak
