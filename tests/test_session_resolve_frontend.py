"""Source-level coverage for routing session opens through /api/session/resolve."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")


def test_frontend_defines_backend_session_resolver_helper():
    assert "async function resolveRequestedSessionId(sid" in SESSIONS_JS
    assert "new URLSearchParams({session_id:sid})" in SESSIONS_JS
    assert "params.set('profile', S.activeProfile)" in SESSIONS_JS
    assert "`/api/session/resolve?${params.toString()}`" in SESSIONS_JS
    assert "status:'resolver_error'" in SESSIONS_JS


def test_load_session_uses_backend_resolver_before_fetching_session():
    start = SESSIONS_JS.index("async function loadSession")
    fetch = SESSIONS_JS.index("/api/session?session_id=", start)
    body_before_fetch = SESSIONS_JS[start:fetch]

    assert "resolveRequestedSessionId(sid, opts)" in body_before_fetch
    assert "resolved.sessionId && resolved.sessionId !== sid" in body_before_fetch
    assert "sid = resolved.sessionId" in body_before_fetch
    assert "skipLineageResolve" in body_before_fetch


def test_boot_restore_keeps_resolution_inside_load_session():
    restore_start = BOOT_JS.index("const saved=urlSession||savedLocal")
    restore_block = BOOT_JS[restore_start: BOOT_JS.index("// no saved session", restore_start)]

    assert "await loadSession(saved);" in restore_block
    assert "/api/session/resolve" not in restore_block
    assert "resolveRequestedSessionId" not in restore_block
