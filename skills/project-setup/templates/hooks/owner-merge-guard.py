#!/usr/bin/env python3
"""Claude Code PreToolUse hook: stops a merge call on a pull request that only the owner merges.

It reads the PR's changed files with `gh` and blocks the call (exit 2) when one matches a glob below,
or when the files cannot be read. It stops accidents, not intent: a session that edits this file on
its own branch runs the edited copy. {{mark}}
"""
import json
import re
import subprocess
import sys

OWNER_ONLY = {{owner_globs_json}}


def matches(glob, path):
    rx = re.escape(glob).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(rx, path) is not None


def pr_to_merge(tool, args):
    """The PR a merge call names ("" for the current branch), or None when the call is no merge."""
    if tool.startswith("mcp__"):
        return str(args.get("pull_number") or args.get("pullNumber") or "")
    command = args.get("command", "")
    for part in re.split(r"&&|\|\||;|\|", command):
        m = re.search(r"\bgh\s+pr\s+merge\b(.*)", part)
        if m:
            words = [w for w in m.group(1).split() if not w.startswith("-")]
            return words[0] if words else ""
        m = re.search(r"\bgh\s+api\b.*?/pulls/(\d+)/merge\b", part)
        if m:
            return m.group(1)
    return None


def main():
    data = json.load(sys.stdin)
    pr = pr_to_merge(data.get("tool_name", ""), data.get("tool_input") or {})
    if pr is None:
        return 0
    cmd = ["gh", "pr", "view", *([pr] if pr else []), "--json", "files", "--jq", ".files[].path"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        res = None
    if res is None or res.returncode != 0:
        print("Could not read this PR's files, so the merge is stopped. Tell the owner the PR is ready.", file=sys.stderr)
        return 2
    hits = [p for p in res.stdout.splitlines() if any(matches(g, p) for g in OWNER_ONLY)]
    if hits:
        more = " and more" if len(hits) > 5 else ""
        print("This PR changes " + ", ".join(hits[:5]) + more + ", which only the owner merges (CLAUDE.md, rule 9). "
              "Do not merge it another way: tell the owner it is ready.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
