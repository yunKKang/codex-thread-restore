#!/usr/bin/env python3
"""Self-contained tests for restore.py."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESTORE = ROOT / "restore.py"


def run(
    codex_home: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(RESTORE), *args],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )


def make_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="thread-restore."))
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (codex_home / "config.toml").write_text('model_provider = "openai"\n')

    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    conn.execute(
        "CREATE TABLE threads ("
        "id TEXT, title TEXT, model_provider TEXT, archived INTEGER, "
        "updated_at INTEGER, updated_at_ms INTEGER)"
    )
    conn.executemany(
        "INSERT INTO threads VALUES (?,?,?,?,?,?)",
        [
            ("old1", "older hidden", "chatgpt", 0, 100, 100000),
            ("old2", "newer hidden", "chatgpt", 0, 200, 200000),
            ("cur1", "already visible", "openai", 0, 300, 300000),
            ("arch", "archived hidden", "chatgpt", 1, 400, 400000),
            ("mem", "Memory Writing hidden", "chatgpt", 0, 500, 500000),
        ],
    )
    conn.commit()
    conn.close()

    for thread_id, provider in [
        ("old1", "chatgpt"),
        ("old2", "chatgpt"),
        ("cur1", "openai"),
        ("arch", "chatgpt"),
        ("mem", "chatgpt"),
    ]:
        header = {
            "timestamp": {
                "old1": "2026-05-04T00:01:00.000Z",
                "old2": "2026-05-04T00:02:00.000Z",
                "cur1": "2026-05-04T00:03:00.000Z",
                "arch": "2026-05-04T00:04:00.000Z",
                "mem": "2026-05-04T00:05:00.000Z",
            }[thread_id],
            "type": "session_meta",
            "payload": {"id": thread_id, "model_provider": provider},
        }
        (sessions / f"rollout-{thread_id}.jsonl").write_text(json.dumps(header) + "\n{}\n")
    return codex_home


def make_small_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="thread-restore-small."))
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (codex_home / "config.toml").write_text('model_provider = "openai"\n')

    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    conn.execute(
        "CREATE TABLE threads ("
        "id TEXT, title TEXT, model_provider TEXT, archived INTEGER, "
        "updated_at INTEGER, updated_at_ms INTEGER)"
    )
    rows = [
        ("a1", "active one", "chatgpt", 0, 100, 100000),
        ("a2", "active two", "chatgpt", 0, 200, 200000),
        ("a3", "active three", "chatgpt", 0, 300, 300000),
        ("arch", "archived", "chatgpt", 1, 400, 400000),
    ]
    conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    for thread_id, _title, provider, _archived, _updated_at, _updated_at_ms in rows:
        header = {
            "timestamp": {
                "a1": "2026-05-04T00:01:00.000Z",
                "a2": "2026-05-04T00:02:00.000Z",
                "a3": "2026-05-04T00:03:00.000Z",
                "arch": "2026-05-04T00:04:00.000Z",
            }[thread_id],
            "type": "session_meta",
            "payload": {"id": thread_id, "model_provider": provider},
        }
        (sessions / f"rollout-{thread_id}.jsonl").write_text(json.dumps(header) + "\n{}\n")
    return codex_home


def make_rollout_activity_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="thread-restore-activity."))
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (codex_home / "config.toml").write_text('model_provider = "openai"\n')

    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    conn.execute(
        "CREATE TABLE threads ("
        "id TEXT, title TEXT, model_provider TEXT, archived INTEGER, "
        "updated_at INTEGER, updated_at_ms INTEGER)"
    )
    rows = [
        ("stale-meta", "recent rollout", "chatgpt", 0, 100, 100000),
        ("fresh-meta", "older rollout", "chatgpt", 0, 999, 999000),
    ]
    conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    rollouts = {
        "stale-meta": ["2026-05-04T01:00:00.000Z", "2026-05-04T09:00:00.000Z"],
        "fresh-meta": ["2026-05-04T02:00:00.000Z"],
    }
    for thread_id, timestamps in rollouts.items():
        lines = [
            json.dumps(
                {
                    "timestamp": timestamps[0],
                    "type": "session_meta",
                    "payload": {"id": thread_id, "model_provider": "chatgpt"},
                }
            )
        ]
        lines.extend(json.dumps({"timestamp": ts, "payload": {}}) for ts in timestamps[1:])
        (sessions / f"rollout-{thread_id}.jsonl").write_text("\n".join(lines) + "\n")
    return codex_home


def make_mixed_provider_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="thread-restore-mixed."))
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (codex_home / "config.toml").write_text('model_provider = "codex"\n')

    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    conn.execute(
        "CREATE TABLE threads ("
        "id TEXT, title TEXT, model_provider TEXT, archived INTEGER, "
        "updated_at INTEGER, updated_at_ms INTEGER)"
    )
    rows = [
        ("api-recent", "api recent", "openai", 0, 100, 100000),
        ("login-recent", "login recent", "chatgpt", 0, 200, 200000),
        ("codex-recent", "codex recent", "codex", 0, 300, 300000),
        ("api-old", "api old", "openai", 0, 400, 400000),
    ]
    conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    timestamps = {
        "api-old": "2026-05-04T00:01:00.000Z",
        "api-recent": "2026-05-04T00:04:00.000Z",
        "login-recent": "2026-05-04T00:03:00.000Z",
        "codex-recent": "2026-05-04T00:02:00.000Z",
    }
    for thread_id, _title, provider, _archived, _updated_at, _updated_at_ms in rows:
        header = {
            "timestamp": timestamps[thread_id],
            "type": "session_meta",
            "payload": {"id": thread_id, "model_provider": provider},
        }
        (sessions / f"rollout-{thread_id}.jsonl").write_text(json.dumps(header) + "\n{}\n")
    return codex_home


def make_filename_fallback_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="thread-restore-filename."))
    codex_home = root / ".codex"
    sessions = codex_home / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (codex_home / "config.toml").write_text('model_provider = "openai"\n')

    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    conn.execute(
        "CREATE TABLE threads ("
        "id TEXT, title TEXT, model_provider TEXT, archived INTEGER, "
        "updated_at INTEGER, updated_at_ms INTEGER)"
    )
    rows = [
        ("filename-hit", "filename fallback", "chatgpt", 0, 100, 100000),
        ("sqlite-hit", "sqlite fallback", "chatgpt", 0, 999, 999000),
    ]
    conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    (sessions / "rollout-filename-hit.jsonl").write_text(
        json.dumps({"timestamp": "2026-05-04T09:00:00.000Z", "payload": {}}) + "\n"
    )
    (sessions / "rollout-sqlite-hit.jsonl").write_text(
        json.dumps({"payload": {"id": "sqlite-hit", "model_provider": "chatgpt"}}) + "\n"
    )
    return codex_home


def provider_map(codex_home: Path) -> dict[str, str]:
    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    rows = conn.execute("SELECT id, model_provider FROM threads ORDER BY id").fetchall()
    conn.close()
    return dict(rows)


def rollout_provider(codex_home: Path, thread_id: str) -> str:
    path = codex_home / "sessions" / "2026" / f"rollout-{thread_id}.jsonl"
    return json.loads(path.open().readline())["payload"]["model_provider"]


def updated_at_map(codex_home: Path) -> dict[str, int]:
    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    rows = conn.execute("SELECT id, updated_at FROM threads ORDER BY id").fetchall()
    conn.close()
    return dict(rows)


def main():
    codex_home = make_home()
    try:
        before = provider_map(codex_home)
        dry = run(codex_home, "-n", "1", "--dry-run")
        assert "Dry run only" in dry.stdout
        assert provider_map(codex_home) == before
        dry = run(codex_home, "restore", "-n", "1", "--dry-run")
        assert "Dry run only" in dry.stdout
        assert provider_map(codex_home) == before

        run(codex_home, "restore", "-n", "1")
        providers = provider_map(codex_home)
        assert providers["cur1"] == "openai"
        assert providers["old2"] == "chatgpt"
        assert providers["old1"] == "chatgpt"
        assert providers["arch"] == "chatgpt"
        assert providers["mem"] == "chatgpt"
        assert rollout_provider(codex_home, "cur1") == "openai"
        assert rollout_provider(codex_home, "old2") == "chatgpt"
        assert rollout_provider(codex_home, "old1") == "chatgpt"
        assert rollout_provider(codex_home, "arch") == "chatgpt"

        run(codex_home, "restore", "-n", "2")
        providers = provider_map(codex_home)
        assert providers["old2"] == "openai"
        assert providers["old1"] == "chatgpt"
        assert providers["arch"] == "chatgpt"
        assert rollout_provider(codex_home, "old2") == "openai"
        assert rollout_provider(codex_home, "arch") == "chatgpt"
        assert (codex_home / "session_index.jsonl").exists()
        backup_dirs = sorted(path.name for path in (codex_home / "backups").iterdir())
        assert len(backup_dirs) == 2
        assert len(set(backup_dirs)) == len(backup_dirs)
        assert all(name.startswith("restore.") for name in backup_dirs)
        verify = run(codex_home, "verify-all")
        assert "Rollout headers: 1 mismatched" in verify.stdout
    finally:
        shutil.rmtree(codex_home.parent)

    small_home = make_small_home()
    try:
        run(small_home)
        providers = provider_map(small_home)
        updated_at = updated_at_map(small_home)
        assert providers["a1"] == "openai"
        assert providers["a2"] == "openai"
        assert providers["a3"] == "openai"
        assert providers["arch"] == "chatgpt"
        assert updated_at["a3"] > updated_at["a2"] > updated_at["a1"]
        assert updated_at["arch"] == 400
    finally:
        shutil.rmtree(small_home.parent)

    auto_home = make_small_home()
    try:
        run(auto_home, "now")
        providers = provider_map(auto_home)
        assert providers["a1"] == "openai"
        assert providers["a2"] == "openai"
        assert providers["a3"] == "openai"
        backups = list((auto_home / "backups").iterdir())
        assert len(backups) == 1
        second = run(auto_home, "auto")
        assert "already consistent" in second.stdout
        assert len(list((auto_home / "backups").iterdir())) == 1
    finally:
        shutil.rmtree(auto_home.parent)

    default_home = make_small_home()
    try:
        run(default_home)
        providers = provider_map(default_home)
        assert providers["a1"] == "openai"
        assert providers["a2"] == "openai"
        assert providers["a3"] == "openai"
    finally:
        shutil.rmtree(default_home.parent)

    activity_home = make_rollout_activity_home()
    try:
        run(activity_home, "restore", "-n", "1")
        providers = provider_map(activity_home)
        assert providers["stale-meta"] == "openai"
        assert providers["fresh-meta"] == "chatgpt"
    finally:
        shutil.rmtree(activity_home.parent)

    mixed_home = make_mixed_provider_home()
    try:
        run(mixed_home, "restore", "-n", "3")
        providers = provider_map(mixed_home)
        assert providers["api-recent"] == "codex"
        assert providers["login-recent"] == "codex"
        assert providers["codex-recent"] == "codex"
        assert providers["api-old"] == "openai"
    finally:
        shutil.rmtree(mixed_home.parent)

    filename_home = make_filename_fallback_home()
    try:
        verify = run(filename_home, "verify", "-n", "1")
        assert "[NEEDS RESTORE] SQLite selected scope: 1 provider(s) to update" in verify.stdout
        run(filename_home, "restore", "-n", "1")
        providers = provider_map(filename_home)
        assert providers["filename-hit"] == "openai"
        assert providers["sqlite-hit"] == "chatgpt"
    finally:
        shutil.rmtree(filename_home.parent)
    print("tests ok")


if __name__ == "__main__":
    main()
