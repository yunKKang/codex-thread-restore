---
name: thread-restore
description: Restore Codex Desktop conversations hidden after switching auth providers
---

# Thread Restore

Use when Codex Desktop conversations disappear after switching login mode,
account, or API provider.

## Commands

```bash
python3 ~/.codex/skills/thread-restore/restore.py
python3 ~/.codex/skills/thread-restore/restore.py now
python3 ~/.codex/skills/thread-restore/restore.py restore -n 10
python3 ~/.codex/skills/thread-restore/restore.py restore --all
python3 ~/.codex/skills/thread-restore/restore.py verify
python3 ~/.codex/skills/thread-restore/restore.py show
python3 ~/.codex/skills/thread-restore/restore.py auto
python3 ~/.codex/skills/thread-restore/restore.py install-auto
python3 ~/.codex/skills/thread-restore/restore.py auto-status
python3 ~/.codex/skills/thread-restore/restore.py uninstall-auto
```

## Rules

- Run `restore.py` directly unless the user asks to preview; it is a one-shot restore
  of all active conversations.
- Restore only active, non-archived conversations.
- Rank recency by the latest rollout event; use SQLite timestamps only as fallback.
- Rank all providers together; do not split account/API conversations into separate buckets.
- Match rollout files by header ID or filename.
- Tell the user to restart Codex Desktop after restore.
- Backups are created under `~/.codex/backups/restore.*`.
- `auto` is only a compatibility alias for `now`.
- Install startup automation only when explicitly requested. On macOS,
  `install-auto` creates a LaunchAgent; on Windows, it creates a Task Scheduler
  logon task. Both run the monitor and restore all active conversations after
  Codex starts or provider data changes.
- Use `auto-status` to inspect startup automation and `uninstall-auto` to remove it.
- Works on macOS and Windows when `CODEX_HOME` or the default `~/.codex` directory
  points to the Codex data folder.
