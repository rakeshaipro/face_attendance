"""Tests for the recognition-loop frame processor (SRS §3.4).

Exercises service._process_frame() directly with a fake provider and a
hand-loaded gallery — no camera thread, no InsightFace.
"""
from __future__ import annotations

import uuid

import numpy as np
import pytest

from tests import fake_provider
from tests.fake_provider import _seed_embedding


@pytest.fixture(autouse=True)
def _fresh_engine_state(monkeypatch):
    """Each test starts with a forced settings refresh + cleared cooldown."""
    import app.engine.service as svc
    monkeypatch.setattr(svc.service, "_settings_ts", 0.0, raising=False)
    svc.service._cooldown.clear()
    yield


def _enroll_employee(db, embedding: np.ndarray, *, blocked: bool = False) -> str:
    """Insert an employee + one embedding; mark enrolled. Returns internal id."""
    import json

    from app.models import Employee, FaceEmbedding

    eid = uuid.uuid4().hex
    emp = Employee(
        id=eid, employee_id=f"ORG-{eid[:6]}", name=f"Emp-{eid[:4]}",
        is_active=True, is_blocked=blocked, is_enrolled=True,
    )
    db.add(emp)
    db.add(
        FaceEmbedding(
            id=uuid.uuid4().hex, employee_id=eid, pose_step=1,
            embedding_json=json.dumps(embedding.astype(float).tolist()),
            image_path="x.jpg", quality_score=0.9,
        )
    )
    db.commit()
    return eid


def _set_threshold(monkeypatch, value: float):
    """Set the threshold in the settings store so _refresh_settings picks it up."""
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    with SessionLocal() as db:
        set_value(db, "engine.similarity_threshold", str(value))


def _set_cooldown(monkeypatch, seconds: float):
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    with SessionLocal() as db:
        set_value(db, "engine.cooldown_seconds", str(seconds))


def _set_min_face_ratio(monkeypatch, value: float):
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    with SessionLocal() as db:
        set_value(db, "engine.min_face_ratio", str(value))


def _patch_provider(monkeypatch, provider):
    import app.engine.service as svc
    monkeypatch.setattr(svc.service, "_provider", provider, raising=False)


def test_match_writes_one_log(client, admin_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import AttendanceLog

    emb = _seed_embedding(7)
    with SessionLocal() as db:
        emp_id = _enroll_employee(db, emb)
    svc_emb = emb  # the gallery row carries this embedding

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)

    frame = fake_provider.make_frame()
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(frame)
    assert n == 1

    with SessionLocal() as db:
        rows = db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_id).all()
        assert len(rows) == 1
        assert rows[0].is_manual is False
        assert rows[0].sync_status == "pending"
        assert rows[0].confidence > 0.999  # identical embedding → cosine ≈ 1
        assert rows[0].snapshot_available is True


def test_below_threshold_writes_nothing(client, admin_headers, monkeypatch):
    from app.db import SessionLocal

    enrolled_emb = _seed_embedding(11)
    frame_emb = _seed_embedding(99)  # very different → low cosine
    with SessionLocal() as db:
        _enroll_employee(db, enrolled_emb)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=frame_emb))
    _set_threshold(monkeypatch, 0.99)  # set impossibly high
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 0


def test_blocked_employee_silently_ignored(client, admin_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import AttendanceLog

    emb = _seed_embedding(3)
    with SessionLocal() as db:
        emp_id = _enroll_employee(db, emb, blocked=True)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 0
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_id).count() == 0


def test_cooldown_suppresses_second_detection(client, admin_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import AttendanceLog

    emb = _seed_embedding(5)
    with SessionLocal() as db:
        emp_id = _enroll_employee(db, emb)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    _set_cooldown(monkeypatch, 60.0)
    from app.engine.service import service
    service.invalidate_gallery()

    n1 = service._process_frame(fake_provider.make_frame())
    n2 = service._process_frame(fake_provider.make_frame())  # within cooldown
    assert n1 == 1
    assert n2 == 0
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_id).count() == 1


def test_cooldown_zero_allows_repeats(client, admin_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import AttendanceLog

    emb = _seed_embedding(8)
    with SessionLocal() as db:
        emp_id = _enroll_employee(db, emb)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    _set_cooldown(monkeypatch, 0.0)  # disables suppression (§3.4.10)
    from app.engine.service import service
    service.invalidate_gallery()

    n1 = service._process_frame(fake_provider.make_frame())
    n2 = service._process_frame(fake_provider.make_frame())
    assert n1 == 1 and n2 == 1
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_id).count() == 2


def test_min_face_ratio_filters_small_face(client, admin_headers, monkeypatch):
    """A tiny face (below min_face_ratio) must not be processed (§3.4.11)."""
    from app.db import SessionLocal

    emb = _seed_embedding(13)
    with SessionLocal() as db:
        _enroll_employee(db, emb)

    # FakeFaceProvider draws a 40% face; force the threshold above that.
    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    _set_min_face_ratio(monkeypatch, 0.9)
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 0
