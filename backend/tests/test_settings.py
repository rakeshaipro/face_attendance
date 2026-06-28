"""Tests for the /api/v1/settings group (SRS §6.4)."""
from __future__ import annotations


def test_settings_list_requires_api_key(client):
    r = client.get("/api/v1/settings")
    assert r.status_code == 401


def test_settings_list_returns_all_known_keys(client, ro_headers):
    r = client.get("/api/v1/settings", headers=ro_headers)
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert isinstance(items, list) and len(items) >= 30  # every defaults.py key
    keys = {it["key"] for it in items}
    # Spot-check that the major groups are present.
    assert "device.machine_id" in keys
    assert "engine.similarity_threshold" in keys
    assert "enroll.quality_threshold" in keys
    assert "retention.logs_days" in keys
    assert "sync.batch_size" in keys
    assert "smtp.host" in keys
    assert "backup.schedule_time" in keys
    assert "system.log_retention_days" in keys
    # Every entry carries the metadata the editor relies on.
    for it in items:
        assert {"key", "value", "type", "group", "subsection", "label"}.issubset(it.keys())


def test_settings_list_masks_sensitive_values(client, ro_headers):
    r = client.get("/api/v1/settings", headers=ro_headers)
    items = r.json()["data"]["items"]
    by_key = {it["key"]: it for it in items}
    cam_pw = by_key["device.camera_password"]
    assert cam_pw["sensitive"] is True
    # Plaintext must never be returned.
    assert cam_pw["value"] == ""
    assert cam_pw["value_set"] is False  # seeded default is empty
    smtp_pw = by_key["smtp.password_encrypted"]
    assert smtp_pw["sensitive"] is True
    assert smtp_pw["value"] == ""


def test_settings_update_requires_admin(client, ro_headers):
    r = client.put(
        "/api/v1/settings",
        headers=ro_headers,
        json={"items": [{"key": "device.machine_id", "value": "X"}]},
    )
    assert r.status_code == 403


def test_settings_update_round_trip(client, admin_headers):
    # Write → read back.
    w = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [
            {"key": "device.machine_id", "value": "SITE-TEST-42"},
            {"key": "device.location_name", "value": "Lab"},
            {"key": "engine.similarity_threshold", "value": "0.72"},
            {"key": "engine.cooldown_seconds", "value": "120"},
            {"key": "sync.batch_size", "value": "250"},
            {"key": "backup.schedule_frequency", "value": "weekly"},
        ]},
    )
    assert w.status_code == 200
    results = w.json()["data"]["items"]
    assert all(r["ok"] for r in results)

    g = client.get("/api/v1/settings", headers=admin_headers).json()["data"]["items"]
    by_key = {it["key"]: it for it in g}
    assert by_key["device.machine_id"]["value"] == "SITE-TEST-42"
    assert by_key["device.location_name"]["value"] == "Lab"
    assert by_key["engine.similarity_threshold"]["value"] == "0.72"
    assert by_key["engine.cooldown_seconds"]["value"] == "120"
    assert by_key["sync.batch_size"]["value"] == "250"
    assert by_key["backup.schedule_frequency"]["value"] == "weekly"


def test_settings_update_rejects_out_of_range(client, admin_headers):
    r = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [
            {"key": "engine.similarity_threshold", "value": "1.50"},  # max 0.95
            {"key": "engine.cooldown_seconds", "value": "99999"},      # max 3600
        ]},
    )
    assert r.status_code == 200
    results = {x["key"]: x for x in r.json()["data"]["items"]}
    assert results["engine.similarity_threshold"]["ok"] is False
    assert "≤" in results["engine.similarity_threshold"]["error"]
    assert results["engine.cooldown_seconds"]["ok"] is False


def test_settings_update_rejects_non_numeric(client, admin_headers):
    r = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [{"key": "engine.read_fps", "value": "fast"}]},
    )
    assert r.status_code == 200
    res = r.json()["data"]["items"][0]
    assert res["ok"] is False
    assert res["error"]


def test_settings_update_rejects_unknown_key(client, admin_headers):
    r = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [{"key": "no.such.key", "value": "x"}]},
    )
    assert r.status_code == 200
    res = r.json()["data"]["items"][0]
    assert res["ok"] is False


def test_settings_update_sensitive_value_round_trip(client, admin_headers):
    """Setting a sensitive value stores it encrypted; a subsequent GET
    reports `value_set=true` but the plaintext is never returned."""
    w = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [{"key": "smtp.password_encrypted", "value": "s3cr3t!"}]},
    )
    assert w.status_code == 200
    assert w.json()["data"]["items"][0]["ok"] is True

    g = client.get("/api/v1/settings", headers=admin_headers).json()["data"]["items"]
    by_key = {it["key"]: it for it in g}
    assert by_key["smtp.password_encrypted"]["value"] == ""
    assert by_key["smtp.password_encrypted"]["value_set"] is True

    # And reading the actual stored plaintext through the typed
    # accessor (used by the SMTP transport in a later slice) returns
    # the original value.
    from app.core.settings_store import get_value
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert get_value(db, "smtp.password_encrypted") == "s3cr3t!"


def test_settings_clear_resets_to_default(client, admin_headers):
    # First, save a value.
    client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [{"key": "smtp.password_encrypted", "value": "temp"}]},
    )
    # Then clear it.
    r = client.put(
        "/api/v1/settings",
        headers=admin_headers,
        json={"items": [{"key": "smtp.password_encrypted", "clear": True}]},
    )
    assert r.status_code == 200
    assert r.json()["data"]["items"][0]["ok"] is True

    g = client.get("/api/v1/settings", headers=admin_headers).json()["data"]["items"]
    by_key = {it["key"]: it for it in g}
    # Default for smtp.password_encrypted is the empty string.
    assert by_key["smtp.password_encrypted"]["value_set"] is False
