# Changelog

## 0.3.0 - 2026-05-09

- Add explicit macOS `install-auto`, `auto-status`, and `uninstall-auto` commands.
- Install a user LaunchAgent that starts a lightweight monitor at login.
- Run one-shot restore when Codex is running and provider/index data changes.
- Keep `auto` as a compatibility alias for `now`.
- Cover LaunchAgent generation and uninstall behavior in tests.

## 0.2.0 - 2026-05-06

- Change the default command to a one-shot restore of all active conversations.
- Add `now` for explicit one-shot restore; keep `auto` as a compatibility alias.
- Avoid creating backups when one-shot checks find the selected scope already consistent.
- Document the no-background workflow and Windows usage.

## 0.1.3 - 2026-05-04

- Avoid repeated rollout scans during restore and verify.
- Use rollout filenames as fallback when headers lack thread IDs.
- Report pending provider updates as `NEEDS RESTORE` in `verify`.

## 0.1.2 - 2026-05-04

- Rank restore candidates by latest rollout event activity.
- Keep SQLite `updated_at` as fallback when rollout activity is unavailable.
- Rank conversations from all providers together.

## 0.1.1 - 2026-05-04

- Change default restore scope from 5 to 10 active conversations.
- Update docs for one-step install and restore.

## 0.1.0 - 2026-05-04

- Restore recent active, non-archived Codex Desktop conversations after provider switches.
- Sync SQLite thread metadata, `session_index.jsonl`, and matching rollout headers.
- Add `--dry-run`, scoped `verify`, full active-scope `verify-all`, and `show`.
- Add timestamped backups under `~/.codex/backups/restore.*` with automatic restore on failure.
- Add self-contained fixture tests with `CODEX_HOME` override support.
