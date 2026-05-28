"""Tests for the read-only WebUI/session profile diagnostic script."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import diagnose_webui_session_profiles as diag


def _write_state_db(path: Path, *, session_id: str, title: str, profile: str | None = None, message: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                started_at REAL NOT NULL,
                title TEXT,
                parent_session_id TEXT,
                message_count INTEGER DEFAULT 0,
                tool_call_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions (id, source, started_at, title, message_count) VALUES (?, ?, ?, ?, ?)",
            (session_id, "webui", 1.0, title, 1),
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, "user", message or title, 1.0),
        )


def _write_sidecar_index(webui_state_dir: Path, rows: list[dict]):
    sessions_dir = webui_state_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "_index.json").write_text(json.dumps(rows), encoding="utf-8")


def test_diagnostic_reports_ok_when_sidecar_profile_matches_state_db(tmp_path):
    hermes_home = tmp_path / "hermes"
    webui_state_dir = hermes_home / "webui"
    _write_state_db(
        hermes_home / "profiles" / "sophia" / "state.db",
        session_id="sid-ok",
        title="Grok Websearch",
        message="websearch grok-4",
    )
    _write_sidecar_index(
        webui_state_dir,
        [{"session_id": "sid-ok", "profile": "sophia", "title": "Hermes WebUI"}],
    )

    report = diag.build_report(hermes_home, webui_state_dir, query="websearch grok-4")

    assert report["profiles_scanned"] == ["sophia"]
    assert report["matches"][0]["session_id"] == "sid-ok"
    assert report["matches"][0]["profile"] == "sophia"
    assert report["matches"][0]["status"] == "ok"
    assert set(report["matches"][0]["sources"]) == {"state_db", "sidecar_index"}


def test_diagnostic_reports_state_db_only_for_missing_sidecar(tmp_path):
    hermes_home = tmp_path / "hermes"
    webui_state_dir = hermes_home / "webui"
    _write_state_db(
        hermes_home / "profiles" / "demiurge" / "state.db",
        session_id="sid-db-only",
        title="Grok Websearch",
        message="websearch grok-4",
    )
    _write_sidecar_index(webui_state_dir, [])

    report = diag.build_report(hermes_home, webui_state_dir, query="websearch grok-4")

    assert report["matches"][0]["session_id"] == "sid-db-only"
    assert report["matches"][0]["profile"] == "demiurge"
    assert report["matches"][0]["status"] == "state_db_only"
    assert report["matches"][0]["snippet"] == "websearch grok-4"


def test_diagnostic_reports_profile_mismatch(tmp_path):
    hermes_home = tmp_path / "hermes"
    webui_state_dir = hermes_home / "webui"
    _write_state_db(
        hermes_home / "profiles" / "demiurge" / "state.db",
        session_id="sid-mismatch",
        title="Grok Websearch",
        message="websearch grok-4",
    )
    _write_sidecar_index(
        webui_state_dir,
        [{"session_id": "sid-mismatch", "profile": "sophia", "title": "Hermes WebUI"}],
    )

    report = diag.build_report(hermes_home, webui_state_dir, query="websearch grok-4")

    match = report["matches"][0]
    assert match["session_id"] == "sid-mismatch"
    assert match["profile"] == "demiurge"
    assert match["sidecar_profile"] == "sophia"
    assert match["status"] == "profile_mismatch"


def test_diagnostic_is_read_only_and_redacts_secret_like_snippets(tmp_path):
    hermes_home = tmp_path / "hermes"
    webui_state_dir = hermes_home / "webui"
    db_path = hermes_home / "profiles" / "demiurge" / "state.db"
    _write_state_db(
        db_path,
        session_id="sid-secret",
        title="Secret test",
        message="websearch api_key=sk-abcdefghijklmnopqrstuvwxyz123456",
    )
    _write_sidecar_index(webui_state_dir, [])
    index_path = webui_state_dir / "sessions" / "_index.json"
    db_mtime = db_path.stat().st_mtime_ns
    index_mtime = index_path.stat().st_mtime_ns

    report = diag.build_report(hermes_home, webui_state_dir, query="websearch")

    assert db_path.stat().st_mtime_ns == db_mtime
    assert index_path.stat().st_mtime_ns == index_mtime
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in json.dumps(report)
    assert "[REDACTED]" in report["matches"][0]["snippet"]
