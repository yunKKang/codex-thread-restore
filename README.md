# Thread Restore

Restore Codex Desktop conversations that disappear from the sidebar after
switching between ChatGPT login and API key authentication.

No third-party Python dependencies. MIT licensed.

## Problem

Codex Desktop stores conversation visibility across three local data layers:

1. `~/.codex/state_5.sqlite` thread metadata.
2. `~/.codex/session_index.jsonl` sidebar index.
3. `~/.codex/sessions/**/rollout-*.jsonl` session headers.

When the active `model_provider` changes, older conversations can remain tagged
with the previous provider. The conversations still exist on disk, but the
sidebar no longer shows them for the current provider.

## Safety Model

This tool is intentionally conservative:

- Default scope is the most recent 5 active, non-archived conversations.
- Restore candidates always exclude archived conversations.
- `-n` and `--all` apply to SQLite rows and rollout files using the same thread
  ID set.
- Backups are created before any write under `~/.codex/backups/restore.*`.
- If a restore step fails, the latest backup is copied back automatically.
- `--dry-run` previews the selected scope without changing files.
- Hidden/system-like titles such as `Uncaught Exception` and `Memory Writing`
  are skipped.

Close Codex Desktop before running `restore`; restart it after the command
finishes.

## Usage

```bash
# Preview the default restore scope
python3 restore.py --dry-run

# Restore the recent 5 active conversations
python3 restore.py

# Restore a larger active scope
python3 restore.py restore -n 10
python3 restore.py restore --all

# Verify selected or full active scope
python3 restore.py verify
python3 restore.py verify --all
python3 restore.py verify-all

# Inspect local thread state
python3 restore.py show
```

Set `CODEX_HOME=/path/to/.codex` to target a fixture or non-default Codex home.

## Install

For a Codex skill install from a local checkout:

```bash
mkdir -p ~/.codex/skills
cp -R /path/to/thread-restore ~/.codex/skills/thread-restore
```

After publishing on GitHub:

```bash
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

For standalone use, run the script directly from any checkout:

```bash
python3 /path/to/thread-restore/restore.py --dry-run
python3 /path/to/thread-restore/restore.py
```

## Uninstall

```bash
rm -rf ~/.codex/skills/thread-restore
```

## Tests

```bash
python3 test_restore.py
```

## Status

This is a local data repair utility for Codex Desktop. Review `--dry-run`
output before restore and keep Codex Desktop closed while writing data.
