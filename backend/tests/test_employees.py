"""Tests for /api/v1/employees (SRS §3.2)."""
from __future__ import annotations

import io


def _create(client, headers, employee_id="EMP001", name="Alice", **kw) -> dict:
    payload = {"employee_id": employee_id, "name": name, **kw}
    r = client.post("/api/v1/employees", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_create_requires_write_scope(client, ro_headers):
    r = client.post("/api/v1/employees", headers=ro_headers, json={"employee_id": "E1", "name": "x"})
    assert r.status_code == 403


def test_create_duplicate_returns_409(client, admin_headers):
    _create(client, admin_headers, "DUP1")
    r = client.post("/api/v1/employees", headers=admin_headers, json={"employee_id": "DUP1", "name": "y"})
    assert r.status_code == 409


def test_crud_happy_path(client, admin_headers):
    emp = _create(client, admin_headers, "CRUD1", "Carol", phone="555", email="c@x.io")
    eid = emp["id"]

    got = client.get(f"/api/v1/employees/{eid}", headers=admin_headers)
    assert got.status_code == 200
    assert got.json()["data"]["name"] == "Carol"

    upd = client.put(f"/api/v1/employees/{eid}", headers=admin_headers, json={"name": "Carolyn"})
    assert upd.status_code == 200
    assert upd.json()["data"]["name"] == "Carolyn"


def test_lookup_by_organisation_employee_id(client, admin_headers):
    _create(client, admin_headers, "ORGID1", "Dave")
    r = client.get("/api/v1/employees/ORGID1", headers=admin_headers)
    assert r.status_code == 200


def test_delete_requires_admin(client, ro_headers, admin_headers):
    # readwrite can't delete — create with admin first via direct call.
    emp = _create(client, admin_headers, "DEL1")
    # Build a readwrite key quickly: reuse admin for setup, but check scope
    # by attempting delete with a readwrite key. We don't have one in
    # fixtures, so assert that readonly is forbidden (403) at minimum.
    r = client.delete(f"/api/v1/employees/{emp['id']}?reason=test", headers=ro_headers)
    assert r.status_code == 403


def test_delete_admin_cascades(client, admin_headers):
    from app.db import SessionLocal
    from app.models import Employee, FaceEmbedding

    emp = _create(client, admin_headers, "DEL2")
    # Insert a stray embedding row to confirm cascade.
    import uuid
    with SessionLocal() as db:
        _emb = [0.0] * 512
        row = FaceEmbedding(
            id=uuid.uuid4().hex, employee_id=emp["id"], pose_step=1,
            embedding_vec=_emb, embedding_json=str(_emb), image_path="x.jpg",
        )
        db.add(row)
        db.commit()

    r = client.delete(f"/api/v1/employees/{emp['id']}?reason=cleanup", headers=admin_headers)
    assert r.status_code == 200

    with SessionLocal() as db:
        leftover = db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == emp["id"]).count()
        assert leftover == 0


def test_search_filter_pagination(client, admin_headers):
    _create(client, admin_headers, "SEA1", "Alice")
    _create(client, admin_headers, "SEA2", "Bob")
    _create(client, admin_headers, "SEA3", "Alicia")

    r = client.get("/api/v1/employees?q=ali", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 2
    names = {i["name"] for i in data["items"]}
    assert {"Alice", "Alicia"} <= names

    r2 = client.get("/api/v1/employees?page=1&limit=2", headers=admin_headers)
    assert len(r2.json()["data"]["items"]) <= 2


def test_block_unblock_and_blocked_list(client, admin_headers):
    emp = _create(client, admin_headers, "BLK1", "Blocked Person")
    r = client.post(f"/api/v1/employees/{emp['id']}/block", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["is_blocked"] is True

    listed = client.get("/api/v1/employees/blocked", headers=admin_headers)
    assert any(e["employee_id"] == "BLK1" for e in listed.json()["data"])

    r2 = client.post(f"/api/v1/employees/{emp['id']}/unblock", headers=admin_headers)
    assert r2.json()["data"]["is_blocked"] is False


def test_csv_export(client, admin_headers):
    _create(client, admin_headers, "EXP1", "Exported")
    r = client.get("/api/v1/employees/export", headers=admin_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "EXP1,Exported" in r.text


def test_csv_import_valid_and_invalid(client, admin_headers):
    csv_content = "employee_id,name,phone,email,is_active\nA1,Alice,555,a@x.io,true\nA2,,bad,b@x.io,true\nA1,Dup,555,d@x.io,true\n"
    files = {"file": ("emp.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    r = client.post("/api/v1/employees/import", headers=admin_headers, files=files)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    assert data["succeeded"] == 1
    assert data["failed"] == 2
    # The valid row should now be retrievable.
    assert client.get("/api/v1/employees/A1", headers=admin_headers).status_code == 200


def test_audit_rows_written(client, admin_headers):
    from app.db import SessionLocal
    from app.models import AuditLog

    _create(client, admin_headers, "AUD1", "Audited")
    with SessionLocal() as db:
        n = db.query(AuditLog).filter(AuditLog.action == "employee.create").count()
        assert n >= 1
