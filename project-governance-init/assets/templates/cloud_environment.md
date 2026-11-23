# {{project_name}} — running the threads in Claude Code cloud sessions

This project's sessions run in the cloud (`claude_code_host: cloud`), at
claude.ai/code or started with `claude --cloud`. Nothing runs on the owner's
computer, so a few things have to be set up once and a few checks go
elsewhere. The rule for the threads is `THR-17`.

## Set up once (owner)

1. **Connect GitHub** for cloud sessions (in the browser at claude.ai/code,
   or `/web-setup` from the Claude Code CLI), with access to `{{repo_slug}}`.
2. **One cloud environment for this repository.** Give it a setup script that
   installs what the fast checks need: {{fast_checks}}. The setup result is
   cached, so it does not run again on every session; change the script when
   the tools change, not in a thread.
3. **Network access**: enough to install those tools and to reach GitHub.
   Keep it as narrow as that allows.
4. **No secrets in the repository.** A value a check needs goes into the
   environment's variables, never into a file a thread can commit.

## What a cloud session cannot do

- Run the desktop app, open a window, or use local hardware. A check that
  needs that runs in CI, or becomes an owner hand step with a starter block
  (`THR-17`). It is never reported as run.
- Reach anything on the owner's own network.

## What stays the same

- Working files are committed on `{{governance_branch}}` from a second
  worktree, exactly as in a local checkout (`THR-13`).
- The copy on `{{default_branch}}` is the one that counts (`THR-14`).
- Sessions keep running when the browser is closed, so a batch does not stop
  when the owner's computer sleeps. A session that does stop is picked up
  from the files, not from its chat.

## Tokens

Per turn a cloud session costs the same as a local one. The extra cost is the
start of each new session: a fresh environment clones the repository and,
the first time, runs the setup script. Fewer, longer-lived worker threads
(`replace_after_prs`) keep that small.
