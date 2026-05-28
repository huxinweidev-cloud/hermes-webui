#!/usr/bin/env python3
"""Read-only diagnostic for WebUI sidecar/profile/state.db session split-brain."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9._-]{6,}"),
]


def _redact(text: str) -> str:
    redacted = str(text or "")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]", redacted)
    return redacted


def _snippet(text: str, query: str | None = None, limit: int = 200) -> str:
    text = _redact(" ".join(str(text or "").split()))
    if not text:
        return ""
    if query:
        needle = query.lower()
        haystack = text.lower()
        idx = haystack.find(needle)
        if idx >= 0:
            start = max(0, idx - 60)
            text = text[start:]
            if start:
                text = "..." + text
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _default_webui_state_dir(hermes_home: Path) -> Path:
    return hermes_home / "webui"


def _profile_dirs(hermes_home: Path, profile: str | None = None) -> list[tuple[str, Path]]:
    if profile:
        return [(profile, hermes_home if profile == "default" else hermes_home / "profiles" / profile)]
    out: list[tuple[str, Path]] = []
    if (hermes_home / "state.db").exists():
        out.append(("default", hermes_home))
    profiles_root = hermes_home / "profiles"
    if profiles_root.exists():
        for child in sorted(profiles_root.iterdir(), key=lambda p: p.name):
            if child.is_dir() and (child / "state.db").exists():
                out.append((child.name, child))
    return out


def _read_sidecar_index(webui_state_dir: Path) -> dict[str, dict[str, Any]]:
    index_path = webui_state_dir / "sessions" / "_index.json"
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    rows = {}
    for row in data:
        if isinstance(row, dict) and row.get("session_id"):
            rows[str(row["session_id"])] = row
    return rows


def _db_has_table(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _read_state_matches(db_path: Path, query: str | None = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    matches: list[dict[str, Any]] = []
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if not _db_has_table(cur, "sessions"):
                return []
            cur.execute("PRAGMA table_info(sessions)")
            session_cols = {row[1] for row in cur.fetchall()}
            title_expr = "title" if "title" in session_cols else "'' AS title"
            started_expr = "started_at" if "started_at" in session_cols else "0 AS started_at"
            if query:
                if _db_has_table(cur, "messages"):
                    cur.execute(
                        f"""
                        SELECT s.id, {title_expr}, {started_expr}, m.content AS snippet
                        FROM sessions s
                        JOIN messages m ON m.session_id = s.id
                        WHERE lower(COALESCE(s.title, '') || ' ' || COALESCE(m.content, '')) LIKE ?
                        ORDER BY {started_expr} DESC
                        LIMIT 100
                        """,
                        (f"%{query.lower()}%",),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT s.id, {title_expr}, {started_expr}, COALESCE(s.title, '') AS snippet
                        FROM sessions s
                        WHERE lower(COALESCE(s.title, '')) LIKE ?
                        ORDER BY {started_expr} DESC
                        LIMIT 100
                        """,
                        (f"%{query.lower()}%",),
                    )
            else:
                cur.execute(
                    f"""
                    SELECT s.id, {title_expr}, {started_expr}, COALESCE(s.title, '') AS snippet
                    FROM sessions s
                    ORDER BY {started_expr} DESC
                    LIMIT 100
                    """
                )
            seen = set()
            for row in cur.fetchall():
                sid = str(row["id"])
                if sid in seen:
                    continue
                seen.add(sid)
                matches.append({
                    "session_id": sid,
                    "title": row["title"],
                    "started_at": row["started_at"],
                    "snippet": _snippet(row["snippet"], query),
                })
    except Exception:
        return []
    return matches


def _status_for(profile: str, state_session_id: str, sidecar_rows: dict[str, dict[str, Any]]) -> tuple[str, str | None, list[str]]:
    sidecar = sidecar_rows.get(state_session_id)
    if not sidecar:
        return "state_db_only", None, ["state_db"]
    sidecar_profile = str(sidecar.get("profile") or "default")
    if sidecar_profile != profile:
        return "profile_mismatch", sidecar_profile, ["state_db", "sidecar_index"]
    return "ok", sidecar_profile, ["state_db", "sidecar_index"]


def build_report(
    hermes_home: Path | str,
    webui_state_dir: Path | str | None = None,
    *,
    query: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    hermes_home = Path(hermes_home).expanduser().resolve()
    webui_state_dir = Path(webui_state_dir).expanduser().resolve() if webui_state_dir else _default_webui_state_dir(hermes_home)
    sidecar_rows = _read_sidecar_index(webui_state_dir)
    profile_homes = _profile_dirs(hermes_home, profile)
    matches: list[dict[str, Any]] = []
    for profile_name, home in profile_homes:
        for row in _read_state_matches(home / "state.db", query=query):
            status, sidecar_profile, sources = _status_for(profile_name, row["session_id"], sidecar_rows)
            entry = {
                "session_id": row["session_id"],
                "profile": profile_name,
                "sources": sources,
                "status": status,
                "title": _redact(row.get("title") or ""),
                "snippet": row.get("snippet") or "",
            }
            if sidecar_profile is not None:
                entry["sidecar_profile"] = sidecar_profile
            matches.append(entry)
    return {
        "query": query,
        "webui_state_dir": str(webui_state_dir),
        "profiles_scanned": [name for name, _home in profile_homes],
        "matches": matches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default="~/.hermes")
    parser.add_argument("--webui-state-dir")
    parser.add_argument("--query")
    parser.add_argument("--profile")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args.hermes_home, args.webui_state_dir, query=args.query, profile=args.profile)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
