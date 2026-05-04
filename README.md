# Thread Restore

English | [中文](README.zh-CN.md)

Restore recent active Codex Desktop conversations hidden after switching auth
providers.

## Ask Codex

> Install `https://github.com/yunKKang/codex-thread-restore`, then run a dry-run restore.

## Install

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

## Usage

```bash
cd ~/.codex/skills/thread-restore

python3 restore.py --dry-run   # preview recent 5 active conversations
python3 restore.py             # restore recent 5 active conversations
python3 restore.py restore -n 10
python3 restore.py restore --all
python3 restore.py verify
python3 restore.py show
```

Close Codex Desktop before restore. Restart it after restore.

## Safety

- Only active, non-archived conversations are selected.
- Default scope is the recent 5 conversations.
- Backups are written to `~/.codex/backups/restore.*`.
- Failed restores copy the latest backup back automatically.
- No third-party Python dependencies.

## Test

```bash
python3 test_restore.py
```

MIT licensed.
