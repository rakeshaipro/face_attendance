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
    """Each test starts with a forced settings refresh + cleared cooldown.

    Several engine settings (similarity_threshold, min_face_ratio, …) are
    stored in the shared system_settings table and mutated by individual
    tests. Without resetting them, a value set by one test leaks into the
    next (the table is seeded once per session by conftest). We restore the
    mutable engine/enroll keys to their defaults here so each test begins
    from a known state. The temporal-smoothing window is reset to 1 (log on
    first match) so pre-existing tests don't have to opt out of smoothing;
    tests that exercise smoothing set it explicitly via
    _set_match_confirm_window().
    """
    import app.engine.service as svc
    from app.db import SessionLocal
    from app.core.settings_store import set_value
    from app.engine.defaults import defaults_dict

    # Restore the mutable recognition/enrollment settings to their defaults.
    reset_keys = [
        "engine.similarity_threshold",
        "engine.cooldown_seconds",
        "engine.min_face_ratio",
        "engine.min_det_score",
        "engine.detect_width",
        "engine.match_confirm_window",
        "engine.match_margin",
        "enroll.quality_threshold",
        "enroll.min_det_score",
    ]
    defaults = defaults_dict()
    with SessionLocal() as db:
        for k in reset_keys:
            set_value(db, k, defaults[k])
        # Pre-existing unit tests assert "log on first match" without
        # waiting for the production default confirm window of 2.
        set_value(db, "engine.match_confirm_window", "1")
        # Margin off so single-employee gallery tests don't depend on
        # a second-best score existing.
        set_value(db, "engine.match_margin", "0")

    monkeypatch.setattr(svc.service, "_settings_ts", 0.0, raising=False)
    svc.service._cooldown.clear()
    svc.service._match_streaks.clear()
    yield


def _set_match_confirm_window(monkeypatch, value: int):
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    with SessionLocal() as db:
        set_value(db, "engine.match_confirm_window", str(value))


def _enroll_employee(db, embedding: np.ndarray, *, blocked: bool = False) -> str:
    """Insert an employee + one embedding; mark enrolled. Returns internal id."""
    from app.models import Employee, FaceEmbedding

    eid = uuid.uuid4().hex
    emb_list = embedding.astype(float).tolist()
    emp = Employee(
        id=eid, employee_id=f"ORG-{eid[:6]}", name=f"Emp-{eid[:4]}",
        is_active=True, is_blocked=blocked, is_enrolled=True,
    )
    db.add(emp)
    db.add(
        FaceEmbedding(
            id=uuid.uuid4().hex, employee_id=eid, pose_step=1,
            embedding_vec=emb_list,
            embedding_json=str(emb_list),
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


def test_min_det_score_filters_low_confidence_face(client, admin_headers, monkeypatch):
    """A low-confidence detection (below min_det_score) is discarded before matching."""
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    emb = _seed_embedding(21)
    with SessionLocal() as db:
        _enroll_employee(db, emb)

    # FakeFaceProvider returns score=0.95 by default; here force it low (0.3).
    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb, score=0.30))
    _set_threshold(monkeypatch, 0.5)
    with SessionLocal() as db:
        set_value(db, "engine.min_det_score", "0.50")  # above the 0.30 detection
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 0


def test_temporal_smoothing_requires_consecutive_matches(client, admin_headers, monkeypatch):
    """With window=3, a match is only logged on the 3rd consecutive matching frame."""
    from app.db import SessionLocal
    from app.models import AttendanceLog

    emb = _seed_embedding(31)
    with SessionLocal() as db:
        emp_id = _enroll_employee(db, emb)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    _set_cooldown(monkeypatch, 0.0)  # don't let cooldown interfere with the count
    _set_match_confirm_window(monkeypatch, 3)
    from app.engine.service import service
    service.invalidate_gallery()

    frame = fake_provider.make_frame()
    n1 = service._process_frame(frame)  # streak 1
    n2 = service._process_frame(frame)  # streak 2
    n3 = service._process_frame(frame)  # streak 3 → log
    assert (n1, n2, n3) == (0, 0, 1)
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_id).count() == 1


def test_temporal_smoothing_resets_on_missed_frame(client, admin_headers, monkeypatch):
    """A non-matching frame between matches resets the streak to zero."""
    from app.db import SessionLocal

    emb = _seed_embedding(32)
    with SessionLocal() as db:
        _enroll_employee(db, emb)

    matcher = fake_provider.FakeFaceProvider(embedding=emb)
    noface = fake_provider.NoFaceProvider()
    _set_threshold(monkeypatch, 0.5)
    _set_cooldown(monkeypatch, 0.0)
    _set_match_confirm_window(monkeypatch, 3)
    from app.engine.service import service
    service.invalidate_gallery()

    frame = fake_provider.make_frame()
    _patch_provider(monkeypatch, matcher)
    service._process_frame(frame)  # streak 1
    service._process_frame(frame)  # streak 2
    _patch_provider(monkeypatch, noface)
    service._process_frame(frame)  # no face → streak resets
    _patch_provider(monkeypatch, matcher)
    n = service._process_frame(frame)  # streak 1 again → not enough
    assert n == 0


def test_detect_width_downscales_but_still_matches(client, admin_headers, monkeypatch):
    """Pre-detect downscale must not break matching (bboxes are ratio-based)."""
    from app.db import SessionLocal
    from app.core.settings_store import set_value

    emb = _seed_embedding(41)
    with SessionLocal() as db:
        _enroll_employee(db, emb)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb))
    _set_threshold(monkeypatch, 0.5)
    with SessionLocal() as db:
        set_value(db, "engine.detect_width", "320")  # downscale 640→320
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame(width=640))
    assert n == 1


def test_match_margin_rejects_ambiguous_near_tie(client, admin_headers, monkeypatch):
    """When two employees score within margin of each other, log neither."""
    from app.db import SessionLocal
    from app.core.settings_store import set_value
    from app.models import AttendanceLog

    # Two nearly-identical embeddings (same seed space → high cosine).
    emb_a = _seed_embedding(50)
    emb_b = emb_a.copy()
    emb_b[0] += 0.01
    emb_b = emb_b / np.linalg.norm(emb_b)

    with SessionLocal() as db:
        emp_a = _enroll_employee(db, emb_a)
        emp_b = _enroll_employee(db, emb_b)

    # Probe with emb_a — both employees will score very high.
    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb_a))
    _set_threshold(monkeypatch, 0.40)
    with SessionLocal() as db:
        set_value(db, "engine.match_margin", "0.05")  # strict enough to reject near-ties
        set_value(db, "engine.match_confirm_window", "1")
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 0
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id.in_([emp_a, emp_b])).count() == 0


def test_match_margin_allows_clear_winner(client, admin_headers, monkeypatch):
    """A decisive best match still logs when margin is enabled."""
    from app.db import SessionLocal
    from app.core.settings_store import set_value
    from app.models import AttendanceLog

    emb_a = _seed_embedding(60)
    emb_b = _seed_embedding(61)  # orthogonal-ish random → low cosine to A

    with SessionLocal() as db:
        emp_a = _enroll_employee(db, emb_a)
        _enroll_employee(db, emb_b)

    _patch_provider(monkeypatch, fake_provider.FakeFaceProvider(embedding=emb_a))
    _set_threshold(monkeypatch, 0.40)
    with SessionLocal() as db:
        set_value(db, "engine.match_margin", "0.10")
        set_value(db, "engine.match_confirm_window", "1")
    from app.engine.service import service
    service.invalidate_gallery()
    n = service._process_frame(fake_provider.make_frame())
    assert n == 1
    with SessionLocal() as db:
        assert db.query(AttendanceLog).filter(AttendanceLog.employee_id == emp_a).count() == 1
