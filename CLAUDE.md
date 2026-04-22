# CLAUDE.md — Claude Code entry point

Read `AGENTS.md` first, then `memory/MEMORY.md` for the durable Strategy automation index.

## Git Workflow

- Work remote: `origin` → `git@<ssh-alias>:<org-user>/strategy-automate.git`
- Personal mirror/old remote: `personal` → `https://github.com/<personal-handle>/strategy-automation.git`
- Local Git identity: `<operator> <redacted@example.com>`
- Use normal commands from the repo root: `git status`, `git pull --ff-only`, `git add`, `git commit`, `git push`.
- Before committing, run the relevant tests plus `git diff --check`.
- Never commit `.env`, `.claude/`, credentials, tenant IDs, raw tenant payloads, or local logs.

If SSH push fails, the work GitHub account still needs the public key from `~/.ssh/<ssh-key-name>.pub` added to GitHub.
