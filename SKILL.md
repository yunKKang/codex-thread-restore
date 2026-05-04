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
python3 ~/.codex/skills/thread-restore/restore.py restore -n 10
python3 ~/.codex/skills/thread-restore/restore.py restore --all
python3 ~/.codex/skills/thread-restore/restore.py verify
python3 ~/.codex/skills/thread-restore/restore.py show
```

## Rules

- Run `restore.py` directly unless the user asks to preview.
- Restore only active, non-archived conversations.
- Rank recency by the latest rollout event; use SQLite timestamps only as fallback.
- Rank all providers together; do not split account/API conversations into separate buckets.
- Match rollout files by header ID or filename.
- Tell the user to close Codex Desktop before restore and restart it after.
- Backups are created under `~/.codex/backups/restore.*`.
