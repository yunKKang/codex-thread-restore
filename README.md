# Thread Restore

English | [中文](README.zh-CN.md)

Restore active Codex Desktop conversations hidden after switching auth providers.

## Ask Codex

> Install `https://github.com/yunKKang/codex-thread-restore`, restore all active conversations, and tell me to restart Codex when done.

## Install

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

## Usage

```bash
cd ~/.codex/skills/thread-restore

python3 restore.py             # one-shot restore for all active conversations
python3 restore.py now
python3 restore.py --dry-run
python3 restore.py restore -n 10
python3 restore.py restore --all
python3 restore.py verify
python3 restore.py show
python3 restore.py auto        # compatibility alias for now
python3 restore.py install-auto
python3 restore.py auto-status
python3 restore.py uninstall-auto
```

Restart Codex Desktop after restore.

The default command runs once and exits. It first checks whether anything needs restoration,
so consistent runs do not create new backups.

For automatic sync after login, explicitly install the macOS LaunchAgent:

```bash
python3 restore.py install-auto
python3 restore.py auto-status
python3 restore.py uninstall-auto
```

`install-auto` writes `~/Library/LaunchAgents/com.codex.thread-restore.plist`.
It starts a lightweight monitor at login. When Codex is running and provider/index data
changes, the monitor runs `now` once and restores all active conversations. Logs are written
to `~/.codex/logs/thread-restore.auto.log` and `~/.codex/logs/thread-restore.auto.err.log`.

This is a macOS user LaunchAgent, not an internal Codex Desktop startup hook. Windows keeps
the manual one-shot workflow.

On Windows, run the same commands with the Python launcher:

```powershell
py -3 restore.py
py -3 restore.py now
py -3 restore.py verify
```

## Safety

- Only active, non-archived conversations are selected.
- Recency is based on the latest rollout event, with SQLite `updated_at` as fallback.
- Conversations from all providers are ranked together.
- Rollout files can be matched by header ID or filename.
- Default scope is all active conversations; use `restore -n 10` for an explicit recent subset.
- `auto` is only a compatibility alias for `now`.
- `install-auto` creates a background LaunchAgent only when the user runs it explicitly.
- Backups are written to `~/.codex/backups/restore.*`.
- Failed restores copy the latest backup back automatically.
- No third-party Python dependencies.

MIT licensed.
