#!/usr/bin/env python3
"""Codex Desktop conversation restore tool.

Fixes conversation isolation when switching accounts/API providers by syncing
three data sources: SQLite threads, session_index.jsonl, and rollout file headers.

Usage:
    python3 restore.py                  # restore recent 10
    python3 restore.py restore -n 10    # restore recent 10
    python3 restore.py restore --all    # restore all
    python3 restore.py verify           # check consistency
    python3 restore.py show             # list threads
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
DB_PATH = CODEX_HOME / "state_5.sqlite"
CONFIG_PATH = CODEX_HOME / "config.toml"
INDEX_PATH = CODEX_HOME / "session_index.jsonl"
SESSIONS_DIR = CODEX_HOME / "sessions"
ARCHIVED_DIR = CODEX_HOME / "archived_sessions"
BACKUP_DIR = CODEX_HOME / "backups"
SKIP_TITLE_PATTERNS = ("%Uncaught Exception%", "%Memory Writing%")
VERSION = "0.1.3"


def get_provider() -> str:
    try:
        text = CONFIG_PATH.read_text()
    except FileNotFoundError:
        sys.exit(f"Error: config not found at {CONFIG_PATH}")
    m = re.search(r'^model_provider\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("Error: cannot read model_provider from config.toml")
    return m.group(1)


def require_schema(conn: sqlite3.Connection):
    rows = conn.execute("PRAGMA table_info(threads)").fetchall()
    columns = {row[1] for row in rows}
    required = {"id", "title", "model_provider", "archived", "updated_at", "updated_at_ms"}
    missing = sorted(required - columns)
    if missing:
        sys.exit(f"Error: unsupported state_5.sqlite schema; missing: {', '.join(missing)}")


def backup(conn: sqlite3.Connection, rollout_files: list[Path] | None = None) -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    root = BACKUP_DIR / f"restore.{ts}"
    root.mkdir()
    target_conn = sqlite3.connect(root / "state_5.sqlite")
    try:
        conn.backup(target_conn)
    finally:
        target_conn.close()
    if INDEX_PATH.exists():
        shutil.copy2(INDEX_PATH, root / "session_index.jsonl")
    if rollout_files:
        for path in rollout_files:
            try:
                relative = path.relative_to(CODEX_HOME)
            except ValueError:
                relative = Path(path.name)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for f in sorted(BACKUP_DIR.glob("restore.*"))[:-10]:
        shutil.rmtree(f)
    return root


def restore_backup(backup_path: Path):
    for suffix in ("-wal", "-shm"):
        Path(f"{DB_PATH}{suffix}").unlink(missing_ok=True)
    shutil.copy2(backup_path / "state_5.sqlite", DB_PATH)
    index_backup = backup_path / "session_index.jsonl"
    if index_backup.exists():
        shutil.copy2(index_backup, INDEX_PATH)
    elif INDEX_PATH.exists():
        INDEX_PATH.unlink()
    for path in backup_path.rglob("rollout-*.jsonl"):
        relative = path.relative_to(backup_path)
        target = CODEX_HOME / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def atomic_write(path: Path, content: str):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def parse_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def thread_id_from_rollout_name(path: Path, thread_ids: set[str]) -> str | None:
    stem = path.stem
    candidates = []
    if stem.startswith("rollout-"):
        candidates.append(stem.removeprefix("rollout-"))
        parts = stem.split("-")
        if len(parts) >= 6:
            candidates.append("-".join(parts[-5:]))
    for candidate in candidates:
        if candidate in thread_ids:
            return candidate
    return None


def rollout_activity(thread_ids: set[str]) -> dict[str, tuple[Path, int]]:
    activity: dict[str, tuple[Path, int]] = {}
    for d in (SESSIONS_DIR, ARCHIVED_DIR):
        if not d.exists():
            continue
        for f in d.rglob("*.jsonl"):
            try:
                thread_id = thread_id_from_rollout_name(f, thread_ids)
                last_seen = None
                with f.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        payload = event.get("payload", {})
                        if thread_id is None and payload.get("id") in thread_ids:
                            thread_id = payload["id"]
                        timestamp = parse_timestamp(event.get("timestamp"))
                        if timestamp is not None:
                            last_seen = timestamp
                if thread_id is not None and last_seen is not None:
                    activity[thread_id] = (f, last_seen)
            except OSError as e:
                print(f"  WARN: {f.name}: {e}", file=sys.stderr)
    return activity


def active_threads(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    return conn.execute(
        "SELECT id, title, updated_at FROM threads "
        "WHERE archived=0 "
        "AND title NOT LIKE ? "
        "AND title NOT LIKE ? "
        "ORDER BY updated_at DESC",
        SKIP_TITLE_PATTERNS,
    ).fetchall()


def restore_candidates(
    rows: list[tuple[str, str, int]], limit: int | None, activity: dict[str, tuple[Path, int]]
) -> list[tuple[str, str, int]]:
    ranked = [
        (tid, title, activity.get(tid, (None, updated_at))[1])
        for tid, title, updated_at in rows
    ]
    ranked.sort(key=lambda row: row[2], reverse=True)
    return ranked if limit is None else ranked[:limit]


def placeholders(values: set[str] | list[str]) -> str:
    return ",".join("?" for _ in values)


def fix_provider(conn: sqlite3.Connection, provider: str, thread_ids: set[str]) -> int:
    if not thread_ids:
        return 0
    cur = conn.execute(
        "UPDATE threads SET model_provider = ? "
        f"WHERE id IN ({placeholders(thread_ids)}) AND model_provider != ?",
        (provider, *thread_ids, provider),
    )
    return cur.rowcount


def fix_timestamps(conn: sqlite3.Connection, threads: list[tuple[str, str, int]]) -> int:
    if not threads:
        return 0
    now = int(time.time())
    updated = 0
    for offset, (thread_id, _title, _updated_at) in enumerate(threads):
        promoted = now - offset
        cur = conn.execute(
            "UPDATE threads SET updated_at=?, updated_at_ms=? WHERE id=?",
            (promoted, promoted * 1000, thread_id),
        )
        updated += cur.rowcount
    return updated


def rebuild_index(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, title, updated_at FROM threads "
        "WHERE archived=0 "
        "AND title NOT LIKE ? "
        "AND title NOT LIKE ? "
        "ORDER BY updated_at DESC",
        SKIP_TITLE_PATTERNS,
    ).fetchall()
    lines = []
    for tid, title, updated_at in rows:
        ts = datetime.fromtimestamp(updated_at, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000000Z"
        )
        lines.append(json.dumps({"id": tid, "thread_name": title, "updated_at": ts}, ensure_ascii=False))
    atomic_write(INDEX_PATH, "\n".join(lines) + "\n" if lines else "")
    return len(rows)


def find_rollout_files(thread_ids: set[str], activity: dict[str, tuple[Path, int]]) -> list[Path]:
    return [path for thread_id, (path, _last_seen) in activity.items() if thread_id in thread_ids]


def fix_rollout_headers(provider: str, rollout_files: list[Path]) -> int:
    fixed = 0
    for f in rollout_files:
        try:
            content = f.read_text()
            if not content:
                continue
            parts = content.split("\n", 1)
            meta = json.loads(parts[0])
            payload = meta.setdefault("payload", {})
            if payload.get("model_provider") == provider:
                continue
            payload["model_provider"] = provider
            parts[0] = json.dumps(meta, ensure_ascii=False)
            atomic_write(f, "\n".join(parts))
            fixed += 1
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: {f.name}: {e}", file=sys.stderr)
    return fixed


def cmd_restore(args: argparse.Namespace):
    provider = get_provider()
    if not DB_PATH.exists():
        sys.exit(f"Error: database not found at {DB_PATH}")
    if not args.all and args.n < 1:
        sys.exit("Error: -n must be greater than 0")

    print(f"Provider: {provider}")
    limit = None if args.all else args.n

    conn = get_db()
    require_schema(conn)
    active_rows = active_threads(conn)
    activity = rollout_activity({tid for tid, _title, _updated_at in active_rows})
    threads = restore_candidates(active_rows, limit, activity)
    thread_ids = {tid for tid, _title, _updated_at in threads}
    rollout_files = find_rollout_files(thread_ids, activity)

    scope = "all active conversations" if args.all else f"recent {args.n} active conversation(s)"
    print(f"Scope: {scope}")
    print(f"Selected: {len(thread_ids)} thread(s), {len(rollout_files)} rollout file(s)")
    if args.dry_run:
        conn.close()
        print("\nDry run only. No files changed.")
        return

    backup_path = backup(conn, rollout_files)
    print(f"Backup: {backup_path}")

    try:
        n = fix_provider(conn, provider, thread_ids)
        print(f"[1/4] SQLite provider: {n} updated")

        n = fix_timestamps(conn, threads)
        print(f"[2/4] Timestamps: {n} promoted")

        n = rebuild_index(conn)
        print(f"[3/4] session_index.jsonl: {n} entries")

        n = fix_rollout_headers(provider, rollout_files)
        print(f"[4/4] Rollout headers: {n} fixed")

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        restore_backup(backup_path)
        print(f"Restore failed. Backup restored from: {backup_path}", file=sys.stderr)
        raise
    else:
        conn.close()

    print("\nDone. Restart Codex Desktop to see restored conversations.")


def cmd_verify(args: argparse.Namespace):
    provider = get_provider()
    if not args.all and args.n < 1:
        sys.exit("Error: -n must be greater than 0")

    limit = None if args.all else args.n
    conn = get_db()
    require_schema(conn)
    active_rows = active_threads(conn)
    activity = rollout_activity({tid for tid, _title, _updated_at in active_rows})
    threads = restore_candidates(active_rows, limit, activity)
    thread_ids = {tid for tid, _title, _updated_at in threads}
    ok = True

    if thread_ids:
        n = conn.execute(
            "SELECT COUNT(*) FROM threads "
            f"WHERE id IN ({placeholders(thread_ids)}) AND model_provider != ?",
            (*thread_ids, provider),
        ).fetchone()[0]
    else:
        n = 0
    tag = "OK" if n == 0 else "NEEDS RESTORE"
    print(f"  [{tag}] SQLite selected scope: {n} provider(s) to update")

    if INDEX_PATH.exists():
        idx_rows = []
        for line in INDEX_PATH.read_text().splitlines():
            try:
                idx_rows.append(json.loads(line))
            except json.JSONDecodeError:
                ok = False
                print("  [FAIL] session_index.jsonl contains invalid JSON")
                break
        idx_ids = {row.get("id") for row in idx_rows}
        missing = thread_ids - idx_ids
        tag = "OK" if not missing else "FAIL"
        print(f"  [{tag}] session_index.jsonl selected scope: {len(missing)} missing")
        if missing:
            ok = False
    else:
        print("  [FAIL] session_index.jsonl missing")
        ok = False

    mismatch = 0
    rollout_files = find_rollout_files(thread_ids, activity)
    for f in rollout_files:
        try:
            meta = json.loads(f.open().readline())
            if meta.get("payload", {}).get("model_provider") != provider:
                mismatch += 1
        except (json.JSONDecodeError, OSError):
            mismatch += 1
    tag = "OK" if mismatch == 0 else "FAIL"
    print(f"  [{tag}] Rollout selected scope: {mismatch} mismatched")
    if mismatch:
        ok = False

    conn.close()
    print(f"\n{'Selected scope is consistent.' if ok else 'Issues found. Run: python3 restore.py restore'}")


def cmd_verify_all(_args: argparse.Namespace):
    provider = get_provider()
    conn = get_db()
    require_schema(conn)
    ok = True

    n = conn.execute(
        "SELECT COUNT(*) FROM threads WHERE archived=0 "
        "AND model_provider != ? "
        "AND title NOT LIKE ? "
        "AND title NOT LIKE ?",
        (provider, *SKIP_TITLE_PATTERNS),
    ).fetchone()[0]
    tag = "OK" if n == 0 else "FAIL"
    print(f"  [{tag}] SQLite: {n} mismatched provider(s)")
    if n:
        ok = False

    if INDEX_PATH.exists():
        idx_count = len(INDEX_PATH.read_text().splitlines())
        db_count = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE archived=0 "
            "AND title NOT LIKE ? "
            "AND title NOT LIKE ?",
            SKIP_TITLE_PATTERNS,
        ).fetchone()[0]
        tag = "OK" if idx_count == db_count else "WARN"
        print(f"  [{tag}] session_index.jsonl: {idx_count} entries (DB: {db_count})")
        if idx_count != db_count:
            ok = False
    else:
        print("  [FAIL] session_index.jsonl missing")
        ok = False

    active_rows = active_threads(conn)
    active_ids = {tid for tid, _title, _updated_at in active_rows}
    activity = rollout_activity(active_ids)
    mismatch = 0
    for f in find_rollout_files(active_ids, activity):
        try:
            meta = json.loads(f.open().readline())
            if meta.get("payload", {}).get("model_provider") != provider:
                mismatch += 1
        except (json.JSONDecodeError, OSError):
            mismatch += 1
    tag = "OK" if mismatch == 0 else "FAIL"
    print(f"  [{tag}] Rollout headers: {mismatch} mismatched")
    if mismatch:
        ok = False

    conn.close()
    print(f"\n{'All consistent.' if ok else 'Issues found. Run: python3 restore.py'}")


def cmd_show(_args: argparse.Namespace):
    conn = get_db()
    require_schema(conn)
    rows = conn.execute(
        "SELECT substr(id,1,16), substr(title,1,50), model_provider, "
        "archived, datetime(updated_at,'unixepoch','localtime') "
        "FROM threads "
        "WHERE title NOT LIKE ? "
        "AND title NOT LIKE ? "
        "ORDER BY updated_at DESC",
        SKIP_TITLE_PATTERNS,
    ).fetchall()
    conn.close()

    print(f"{'ID':<18} {'Provider':<8} {'State':<6} {'Updated':<20} Title")
    print("-" * 100)
    for tid, title, provider, archived, updated in rows:
        state = "arch" if archived else "act"
        print(f"{tid:<18} {provider:<8} {state:<6} {updated:<20} {title}")


def main():
    parser = argparse.ArgumentParser(description="Codex conversation restore tool")
    parser.add_argument("--version", action="version", version=f"thread-restore {VERSION}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("restore", help="Restore conversations")
    p.add_argument("-n", type=int, default=10, help="Recent active conversation count (default: 10)")
    p.add_argument("--all", action="store_true", help="Restore all active conversations")
    p.add_argument("--dry-run", action="store_true", help="Preview without changing files")

    v = sub.add_parser("verify", help="Verify selected restore scope")
    v.add_argument("-n", type=int, default=10, help="Recent active conversation count (default: 10)")
    v.add_argument("--all", action="store_true", help="Verify all active conversations")
    sub.add_parser("verify-all", help="Verify all active threads and rollouts")
    sub.add_parser("show", help="List all threads")

    command_names = {"restore", "verify", "verify-all", "show"}
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help", "--version"}:
        args = parser.parse_args(argv)
    elif not argv or argv[0] not in command_names:
        argv = ["restore", *argv]
        args = parser.parse_args(argv)
    else:
        args = parser.parse_args(argv)

    dispatch = {
        "restore": cmd_restore,
        "verify": cmd_verify,
        "verify-all": cmd_verify_all,
        "show": cmd_show,
    }
    if args.command in dispatch:
        dispatch[args.command](args)


if __name__ == "__main__":
    main()
