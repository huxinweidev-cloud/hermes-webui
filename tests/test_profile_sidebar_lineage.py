"""Regression coverage for profile-aware sidebar lineage metadata."""

from __future__ import annotations



def test_sidebar_lineage_metadata_uses_each_row_profile_state_db(monkeypatch, tmp_path):
    import api.models as models

    calls = []

    def fake_profile_home(profile):
        return tmp_path / str(profile or "default")

    def fake_read_lineage_metadata(db_path, session_ids):
        calls.append((db_path, set(session_ids)))
        if db_path == tmp_path / "sophia" / "state.db":
            assert set(session_ids) == {"sid-sophia"}
            return {"sid-sophia": {"_state_db_title": "Sophia title"}}
        if db_path == tmp_path / "demiurge" / "state.db":
            assert set(session_ids) == {"sid-demiurge"}
            return {"sid-demiurge": {"_state_db_title": "Demiurge title"}}
        return {}

    monkeypatch.setattr(models, "_get_profile_home", fake_profile_home)
    monkeypatch.setattr(models, "read_session_lineage_metadata", fake_read_lineage_metadata)

    rows = [
        {"session_id": "sid-sophia", "title": "Hermes WebUI", "profile": "sophia"},
        {"session_id": "sid-demiurge", "title": "Hermes WebUI", "profile": "demiurge"},
    ]

    models._enrich_sidebar_lineage_metadata(rows)

    assert rows[0]["display_title"] == "Sophia title"
    assert rows[1]["display_title"] == "Demiurge title"
    assert calls == [
        (tmp_path / "sophia" / "state.db", {"sid-sophia"}),
        (tmp_path / "demiurge" / "state.db", {"sid-demiurge"}),
    ]
