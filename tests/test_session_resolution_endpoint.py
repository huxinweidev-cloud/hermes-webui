from urllib.parse import urlparse


def _json_response(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(
        routes,
        "j",
        lambda _handler, payload, status=200, extra_headers=None: {
            "status_code": status,
            "payload": payload,
        },
    )
    monkeypatch.setattr(
        routes,
        "bad",
        lambda _handler, msg, status=400: {
            "status_code": status,
            "payload": {"error": msg},
        },
    )
    return routes


def test_session_resolve_visible_sidecar_resolves_to_itself(monkeypatch):
    routes = _json_response(monkeypatch)

    rows = [
        {
            "session_id": "visible_sid",
            "title": "Visible",
            "profile": "demiurge",
            "message_count": 2,
            "updated_at": 20,
        }
    ]

    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: list(rows))
    monkeypatch.setattr(routes, "read_session_lineage_report", lambda _db, _sid: {"found": False})

    response = routes.handle_get(
        object(),
        urlparse("/api/session/resolve?session_id=visible_sid&profile=demiurge"),
    )

    assert response["status_code"] == 200
    assert response["payload"] == {
        "requested_session_id": "visible_sid",
        "canonical_visible_session_id": "visible_sid",
        "status": "visible",
        "profile": "demiurge",
        "reason": None,
    }


def test_session_resolve_snapshot_parent_resolves_to_visible_continuation(monkeypatch):
    routes = _json_response(monkeypatch)

    rows = [
        {
            "session_id": "child_sid",
            "title": "Long Chat",
            "profile": "demiurge",
            "parent_session_id": "parent_sid",
            "message_count": 1,
            "updated_at": 200,
        }
    ]

    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: list(rows))
    monkeypatch.setattr(routes, "read_session_lineage_report", lambda _db, _sid: {"found": False})

    response = routes.handle_get(
        object(),
        urlparse("/api/session/resolve?session_id=parent_sid&profile=demiurge"),
    )

    assert response["status_code"] == 200
    assert response["payload"]["requested_session_id"] == "parent_sid"
    assert response["payload"]["canonical_visible_session_id"] == "child_sid"
    assert response["payload"]["status"] == "resolved_to_continuation"
    assert response["payload"]["profile"] == "demiurge"
    assert response["payload"]["reason"] == (
        "requested session is a pre-compression snapshot with a visible continuation"
    )


def test_session_resolve_state_db_only_does_not_404(monkeypatch):
    routes = _json_response(monkeypatch)

    monkeypatch.setattr(routes, "all_sessions", lambda diag=None: [])
    monkeypatch.setattr(
        routes,
        "read_session_lineage_report",
        lambda _db, sid: {"found": sid == "state_only_sid", "segments": []},
    )

    response = routes.handle_get(
        object(),
        urlparse("/api/session/resolve?session_id=state_only_sid&profile=demiurge"),
    )

    assert response["status_code"] == 200
    assert response["payload"] == {
        "requested_session_id": "state_only_sid",
        "canonical_visible_session_id": None,
        "status": "state_db_only",
        "profile": "demiurge",
        "reason": "session exists in profile state.db but no WebUI sidecar transcript is available",
    }


def test_session_resolve_invalid_profile_rejected(monkeypatch):
    routes = _json_response(monkeypatch)

    called = False

    def fake_all_sessions(diag=None):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(routes, "all_sessions", fake_all_sessions)

    response = routes.handle_get(
        object(),
        urlparse("/api/session/resolve?session_id=visible_sid&profile=../../default"),
    )

    assert response["status_code"] == 400
    assert response["payload"]["error"] == "invalid_profile"
    assert called is False
