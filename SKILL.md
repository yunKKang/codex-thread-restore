---
name: thread-restore
description: Restore conversations lost after switching accounts or API providers
---

# Thread Restore

Fixes Codex Desktop sidebar showing no conversations after switching between
ChatGPT login and API key authentication.

This is a local data repair tool. Prefer `--dry-run` first when the user only
wants to inspect what would change. Restore creates a timestamped backup under
`~/.codex/backups/restore.*` before writing data.

## When to Use

Activate when the user says any of:
- "恢复对话" / "restore conversations"
- "对话消失了" / "conversations missing"
- "切换账号后看不到对话"
- "sidebar empty" / "侧边栏空白"
- "restore threads" / "recover chats"

## How It Works

Codex Desktop reads conversation visibility from three data sources:
1. `state_5.sqlite` — thread metadata (`model_provider`)
2. `session_index.jsonl` — sidebar display index
3. `rollout-*.jsonl` headers — `session_meta.model_provider`

Switching auth changes the active provider but leaves old data pointing to the
previous provider. This skill syncs all three layers.

Restore candidates are the most recent active, non-archived conversations.
Archived conversations are never restored unless the implementation is changed
explicitly.

## Commands

Run from the skill directory: `~/.codex/skills/thread-restore/`

```bash
# Preview recent 5 conversations without changes
python3 restore.py --dry-run

# Restore recent 5 active conversations (default)
python3 restore.py

# Restore recent N active conversations
python3 restore.py restore -n 10

# Restore all active conversations
python3 restore.py restore --all

# Verify consistency
python3 restore.py verify

# Verify all active data
python3 restore.py verify-all

# List all threads
python3 restore.py show
```

## Agent Instructions

1. When the user asks to restore conversations, run:
   ```
   python3 ~/.codex/skills/thread-restore/restore.py --dry-run
   ```
2. If the selected scope is correct, run without `--dry-run`.
3. Tell the user to close Codex Desktop before restore and restart it after restore.
4. If the user wants more or fewer, use `-n <count>` or `--all`.
5. To check selected scope without changes, use `verify`; for all active data, use `verify-all`.
