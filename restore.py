#!/usr/bin/env python3
"""Codex Desktop conversation restore tool.

Fixes conversation isolation when switching accounts/API providers by syncing
three data sources: SQLite threads, session_index.jsonl, and rollout file headers.

Usage:
    python3 restore.py                  # restore all active
    python3 restore.py now              # restore all active
    python3 restore.py restore -n 10    # restore recent 10
    python3 restore.py restore --all    # restore all
    python3 restore.py verify           # check consistency
    python3 restore.py show             # list threads
    python3 restore.py install-auto      # install macOS startup monitor
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
DB_PATH = CODEX_HOME / "state_5.sqlite"
CONFIG_PATH = CODEX_HOME / "config.toml"
INDEX_PATH = CODEX_HOME / "session_index.jsonl"
SESSIONS_DIR = CODEX_HOME / "sessions"
ARCHIVED_DIR = CODEX_HOME / "archived_sessions"
BACKUP_DIR = CODEX_HOME / "backups"
LOCK_PATH = CODEX_HOME / "thread-restore.lock"
LOG_DIR = CODEX_HOME / "logs"
AUTO_LABEL = "com.codex.thread-restore"
LAUNCH_AGENTS_DIR = Path(
    os.environ.get("THREAD_RESTORE_LAUNCH_AGENTS_DIR", Path.home() / "Library" / "LaunchAgents")
).expanduser()
AUTO_PLIST_PATH = LAUNCH_AGENTS_DIR / f"{AUTO_LABEL}.plist"
SKIP_TITLE_PATTERNS = ("%Uncaught Exception%", "%Memory Writing%")
VERSION = "0.3.0"


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
    path.parent.mkdir(parents=True, exist_ok=True)
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


def atomic_write_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def restore_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            age = 0
        if age > 600:
            LOCK_PATH.unlink(missing_ok=True)
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            print(f"Another restore is running: {LOCK_PATH}")
            yield False
            return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    try:
        yield True
    finally:
        LOCK_PATH.unlink(missing_ok=True)


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


def selected_scope(
    conn: sqlite3.Connection, limit: int | None
) -> tuple[list[tuple[str, str, int]], set[str], list[Path]]:
    active_rows = active_threads(conn)
    activity = rollout_activity({tid for tid, _title, _updated_at in active_rows})
    threads = restore_candidates(active_rows, limit, activity)
    thread_ids = {tid for tid, _title, _updated_at in threads}
    return threads, thread_ids, find_rollout_files(thread_ids, activity)


def index_ids() -> tuple[set[str], bool]:
    if not INDEX_PATH.exists():
        return set(), False
    ids = set()
    for line in INDEX_PATH.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return ids, False
        if row.get("id"):
            ids.add(row["id"])
    return ids, True


def scope_needs_restore(
    conn: sqlite3.Connection,
    provider: str,
    thread_ids: set[str],
    rollout_files: list[Path],
    exact_index: bool,
) -> list[str]:
    reasons = []
    if thread_ids:
        mismatched = conn.execute(
            "SELECT COUNT(*) FROM threads "
            f"WHERE id IN ({placeholders(thread_ids)}) AND model_provider != ?",
            (*thread_ids, provider),
        ).fetchone()[0]
    else:
        mismatched = 0
    if mismatched:
        reasons.append(f"{mismatched} SQLite provider mismatch(es)")

    ids, valid_index = index_ids()
    if not valid_index:
        reasons.append("session_index.jsonl missing or invalid")
    elif exact_index and ids != thread_ids:
        reasons.append("session_index.jsonl differs from active thread scope")
    else:
        missing = thread_ids - ids
        if missing:
            reasons.append(f"{len(missing)} selected thread(s) missing from session_index.jsonl")

    rollout_mismatches = 0
    for f in rollout_files:
        try:
            meta = json.loads(f.open().readline())
            if meta.get("payload", {}).get("model_provider") != provider:
                rollout_mismatches += 1
        except (json.JSONDecodeError, OSError):
            rollout_mismatches += 1
    if rollout_mismatches:
        reasons.append(f"{rollout_mismatches} rollout header mismatch(es)")
    return reasons


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


def cmd_now(args: argparse.Namespace):
    if args.n is not None and args.n < 1:
        sys.exit("Error: -n must be greater than 0")

    limit = args.n
    with restore_lock() as locked:
        if not locked:
            return
        provider = get_provider()
        if not DB_PATH.exists():
            sys.exit(f"Error: database not found at {DB_PATH}")
        conn = get_db()
        require_schema(conn)
        _threads, thread_ids, rollout_files = selected_scope(conn, limit)
        reasons = scope_needs_restore(
            conn,
            provider,
            thread_ids,
            rollout_files,
            exact_index=limit is None,
        )
        conn.close()

        scope = "all active conversations" if limit is None else f"recent {limit} active conversation(s)"
        if not reasons:
            print(f"One-shot restore: {scope} already consistent.")
            return
        print(f"One-shot restore: {scope} needs restore:")
        for reason in reasons:
            print(f"  - {reason}")
        if args.dry_run:
            print("\nDry run only. No files changed.")
            return

        restore_args = argparse.Namespace(
            all=limit is None,
            n=limit if limit is not None else 10,
            dry_run=False,
        )
        cmd_restore(restore_args)


def cmd_auto(args: argparse.Namespace):
    cmd_now(args)


def codex_running() -> bool:
    try:
        proc = subprocess.run(
            ["pgrep", "-x", "Codex"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def auto_state_path() -> Path:
    return CODEX_HOME / "thread-restore.auto-state.json"


def read_auto_state() -> dict[str, object]:
    path = auto_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_auto_state(state: dict[str, object]):
    atomic_write(auto_state_path(), json.dumps(state, indent=2, sort_keys=True) + "\n")


def auto_signature() -> dict[str, object]:
    paths = [CONFIG_PATH, DB_PATH, INDEX_PATH]
    signature: dict[str, object] = {"provider": None, "files": {}}
    try:
        signature["provider"] = get_provider()
    except SystemExit:
        signature["provider"] = None
    files = {}
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            files[str(path)] = None
        else:
            files[str(path)] = [stat.st_mtime_ns, stat.st_size]
    signature["files"] = files
    return signature


def cmd_monitor(args: argparse.Namespace):
    interval = args.interval
    if interval < 5:
        sys.exit("Error: --interval must be at least 5 seconds")

    last_signature = None
    last_restore = 0.0
    state = read_auto_state()
    if state.get("signature"):
        last_signature = state["signature"]
    if isinstance(state.get("restored_at"), int):
        last_restore = float(state["restored_at"])
    was_running = False
    print(f"Auto monitor started. Checking every {interval}s.")
    while True:
        running = codex_running()
        signature = auto_signature()
        changed = signature != last_signature
        started = running and not was_running
        cooled_down = time.time() - last_restore >= args.cooldown
        if running and (started or (changed and cooled_down)):
            print("Codex activity/config change detected; running one-shot restore.")
            restore_args = argparse.Namespace(n=None, all=True, dry_run=False)
            try:
                cmd_now(restore_args)
            except BaseException as e:
                print(f"Auto restore failed: {e}", file=sys.stderr)
            else:
                last_signature = auto_signature()
                last_restore = time.time()
                write_auto_state({"signature": last_signature, "restored_at": int(last_restore)})
        elif changed and not running:
            last_signature = signature
            write_auto_state({"signature": last_signature, "restored_at": state.get("restored_at")})
        was_running = running
        sys.stdout.flush()
        time.sleep(interval)


def launchctl_bootstrap(plist_path: Path) -> bool:
    if sys.platform != "darwin" or os.environ.get("THREAD_RESTORE_SKIP_LAUNCHCTL") == "1":
        return False
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False)
    proc = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
        return False
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{AUTO_LABEL}"], check=False)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{AUTO_LABEL}"], check=False)
    return True


def launchctl_bootout(plist_path: Path) -> bool:
    if sys.platform != "darwin" or os.environ.get("THREAD_RESTORE_SKIP_LAUNCHCTL") == "1":
        return False
    uid = os.getuid()
    proc = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0


def auto_plist(interval: int, cooldown: int) -> dict[str, object]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": AUTO_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(Path(__file__).resolve()),
            "monitor",
            "--interval",
            str(interval),
            "--cooldown",
            str(cooldown),
        ],
        "EnvironmentVariables": {
            "CODEX_HOME": str(CODEX_HOME),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_DIR / "thread-restore.auto.log"),
        "StandardErrorPath": str(LOG_DIR / "thread-restore.auto.err.log"),
    }


def cmd_install_auto(args: argparse.Namespace):
    if sys.platform != "darwin" and os.environ.get("THREAD_RESTORE_ALLOW_NON_DARWIN") != "1":
        sys.exit("Error: install-auto currently supports macOS LaunchAgent only")
    if args.interval < 5:
        sys.exit("Error: --interval must be at least 5 seconds")
    if args.cooldown < 0:
        sys.exit("Error: --cooldown must be non-negative")

    payload = plistlib.dumps(auto_plist(args.interval, args.cooldown), sort_keys=True)
    atomic_write_bytes(AUTO_PLIST_PATH, payload)
    loaded = launchctl_bootstrap(AUTO_PLIST_PATH)
    print(f"Installed auto restore LaunchAgent: {AUTO_PLIST_PATH}")
    print(f"Mode: restore all active conversations after Codex starts or provider data changes")
    print(f"LaunchAgent loaded: {'yes' if loaded else 'not loaded by this run'}")


def cmd_uninstall_auto(_args: argparse.Namespace):
    loaded = launchctl_bootout(AUTO_PLIST_PATH)
    existed = AUTO_PLIST_PATH.exists()
    AUTO_PLIST_PATH.unlink(missing_ok=True)
    print(f"Removed auto restore LaunchAgent: {'yes' if existed else 'already absent'}")
    print(f"LaunchAgent unloaded: {'yes' if loaded else 'not loaded or unavailable'}")


def cmd_auto_status(_args: argparse.Namespace):
    print(f"LaunchAgent plist: {AUTO_PLIST_PATH}")
    print(f"Installed: {'yes' if AUTO_PLIST_PATH.exists() else 'no'}")
    print(f"Codex running: {'yes' if codex_running() else 'no'}")
    state = read_auto_state()
    restored_at = state.get("restored_at")
    if isinstance(restored_at, int):
        stamp = datetime.fromtimestamp(restored_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"Last auto restore: {stamp}")
    else:
        print("Last auto restore: unknown")


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
    n = sub.add_parser("now", help="One-shot restore for all active conversations")
    n.add_argument("-n", type=int, help="Recent active conversation count (default: all)")
    n.add_argument("--all", action="store_true", help="Restore all active conversations (default)")
    n.add_argument("--dry-run", action="store_true", help="Preview without changing files")
    a = sub.add_parser("auto", help="Compatibility alias for now")
    a.add_argument("-n", type=int, help="Recent active conversation count (default: all)")
    a.add_argument("--all", action="store_true", help="Restore all active conversations (default)")
    a.add_argument("--dry-run", action="store_true", help="Preview without changing files")

    m = sub.add_parser("monitor", help="Internal LaunchAgent monitor")
    m.add_argument("--interval", type=int, default=30, help=argparse.SUPPRESS)
    m.add_argument("--cooldown", type=int, default=120, help=argparse.SUPPRESS)
    ia = sub.add_parser("install-auto", help="Install macOS LaunchAgent auto restore")
    ia.add_argument("--interval", type=int, default=30, help="Monitor interval in seconds (default: 30)")
    ia.add_argument("--cooldown", type=int, default=120, help="Minimum seconds between restores")
    sub.add_parser("uninstall-auto", help="Remove macOS LaunchAgent auto restore")
    sub.add_parser("auto-status", help="Show auto restore status")

    command_names = {
        "restore",
        "verify",
        "verify-all",
        "show",
        "now",
        "auto",
        "monitor",
        "install-auto",
        "uninstall-auto",
        "auto-status",
    }
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help", "--version"}:
        args = parser.parse_args(argv)
    elif not argv:
        argv = ["now"]
        args = parser.parse_args(argv)
    elif argv[0] not in command_names:
        argv = ["restore", *argv]
        args = parser.parse_args(argv)
    else:
        args = parser.parse_args(argv)

    dispatch = {
        "restore": cmd_restore,
        "verify": cmd_verify,
        "verify-all": cmd_verify_all,
        "show": cmd_show,
        "now": cmd_now,
        "auto": cmd_auto,
        "monitor": cmd_monitor,
        "install-auto": cmd_install_auto,
        "uninstall-auto": cmd_uninstall_auto,
        "auto-status": cmd_auto_status,
    }
    if args.command in dispatch:
        dispatch[args.command](args)


if __name__ == "__main__":
    main()
