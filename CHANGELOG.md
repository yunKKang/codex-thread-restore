# Changelog

## 0.1.0 - 2026-05-04

- Restore recent active, non-archived Codex Desktop conversations after provider switches.
- Sync SQLite thread metadata, `session_index.jsonl`, and matching rollout headers.
- Add `--dry-run`, scoped `verify`, full active-scope `verify-all`, and `show`.
- Add timestamped backups under `~/.codex/backups/restore.*` with automatic restore on failure.
- Add self-contained fixture tests with `CODEX_HOME` override support.
