"""Enrollment business logic (SRS §3.3).

Pure functions that the enrollment router calls. Each function takes a
decoded BGR frame and a FaceProvider so the logic is testable without a
camera or real InsightFace.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ENROLLMENT_DIR
from app.core.settings_store import get_float
from app.engine.face_provider import FaceProvider
from app.engine.matcher import cosine_similarity
from app.engine.pose import MANDATORY_STEP_COUNT, POSE_STEPS, assess_quality, get_step, pose_in_range
from app.models import Employee, FaceEmbedding
from app.schemas.enrollment import (
    CaptureOut,
    CaptureSummary,
    FinalizeResult,
    PoseCheckResult,
    QualityOut,
    VerifyResult,
)


# --- helpers -------------------------------------------------------------
def _decode_image(data: bytes) -> np.ndarray:
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Could not decode image (expected JPEG/PNG bytes).")
    return frame


def _save_capture_image(employee_internal_id: str, step: int, frame: np.ndarray) -> str:
    import cv2

    rel = f"{employee_internal_id}_{step}.jpg"
    path = ENROLLMENT_DIR / rel
    cv2.imwrite(str(path), frame)
    return rel


def _quality_to_out(qr) -> QualityOut:  # type: ignore[no-untyped-def]
    return QualityOut(
        score=qr.score,
        sharpness=qr.sharpness,
        brightness=qr.brightness,
        face_size_ratio=qr.face_size_ratio,
        acceptable=qr.acceptable,
    )


def _step_summary(emb: FaceEmbedding) -> CaptureSummary:
    return CaptureSummary(
        step=emb.pose_step,
        quality=emb.quality_score or 0.0,
        yaw=emb.yaw,
        pitch=emb.pitch,
        image_path=emb.image_path,
    )


def _list_captures(db: Session, employee_internal_id: str) -> list[FaceEmbedding]:
    return (
        db.execute(
            select(FaceEmbedding)
            .where(FaceEmbedding.employee_id == employee_internal_id)
            .order_by(FaceEmbedding.pose_step.asc())
        )
        .scalars()
        .all()
    )


# --- public API ----------------------------------------------------------
def pose_check(frame: np.ndarray, step: int, provider: FaceProvider, *, min_face_ratio: float) -> PoseCheckResult:
    """Evaluate a frame for the given step without saving (§3.3.6/§3.3.8/§3.3.14)."""
    get_step(step)  # raises on invalid step
    detections = provider.detect(frame, with_embeddings=False, min_size_ratio=min_face_ratio)
    if not detections:
        return PoseCheckResult(face_detected=False, face_count=0, in_range=False, reason="No face detected.")
    if len(detections) > 1:
        return PoseCheckResult(face_detected=True, face_count=len(detections), in_range=False, reason="Multiple faces detected; only one allowed.")
    det = detections[0]
    yaw, pitch = det.yaw, det.pitch
    in_range = pose_in_range(step, yaw, pitch)
    qr = assess_quality(frame, det.bbox, min_face_ratio=min_face_ratio)
    reason = None if in_range else "Face pose not in target range for this step."
    return PoseCheckResult(
        face_detected=True,
        face_count=1,
        in_range=in_range,
        yaw=yaw,
        pitch=pitch,
        quality=_quality_to_out(qr),
        reason=reason,
    )


def capture(
    db: Session,
    employee: Employee,
    frame: np.ndarray,
    step: int,
    provider: FaceProvider,
    *,
    quality_threshold: float,
    min_face_ratio: float,
) -> CaptureOut:
    """Validate + persist a capture for `step` (one-per-step upsert, §3.3.15)."""
    get_step(step)
    detections = provider.detect(frame, with_embeddings=True, min_size_ratio=min_face_ratio)
    if not detections:
        raise ValueError("No face detected.")
    if len(detections) > 1:
        raise ValueError("Multiple faces detected; only one allowed.")
    det = detections[0]
    if det.embedding is None:
        raise ValueError("Provider returned no embedding.")
    if not pose_in_range(step, det.yaw, det.pitch):
        raise ValueError("Face pose not in target range for this step.")
    qr = assess_quality(frame, det.bbox, min_face_ratio=min_face_ratio)
    if qr.score < quality_threshold:
        raise ValueError(f"Quality {qr.score} below threshold {quality_threshold}.")

    # One embedding per pose step (§3.3.15): upsert.
    existing = db.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.employee_id == employee.id, FaceEmbedding.pose_step == step
        )
    ).scalar_one_or_none()
    image_rel = _save_capture_image(employee.id, step, frame)
    embedding_json = json.dumps(det.embedding.astype(float).tolist())

    if existing is None:
        row = FaceEmbedding(
            id=uuid.uuid4().hex,
            employee_id=employee.id,
            pose_step=step,
            embedding_json=embedding_json,
            image_path=image_rel,
            quality_score=qr.score,
            yaw=det.yaw,
            pitch=det.pitch,
        )
        db.add(row)
    else:
        existing.embedding_json = embedding_json
        existing.image_path = image_rel
        existing.quality_score = qr.score
        existing.yaw = det.yaw
        existing.pitch = det.pitch
        existing.created_at = datetime.now(timezone.utc)
        row = existing
    db.commit()

    return CaptureOut(
        step=step,
        quality=_quality_to_out(qr),
        yaw=det.yaw,
        pitch=det.pitch,
        image_path=image_rel,
    )


def finalize(db: Session, employee: Employee, api_key_label: str | None) -> FinalizeResult:
    """Compute overall quality + mark the employee enrolled (§3.3.19/§3.3.20)."""
    from app.services.audit import write_audit

    captures = _list_captures(db, employee.id)
    steps_done = {c.pose_step for c in captures}
    mandatory_done = [s for s in range(1, MANDATORY_STEP_COUNT + 1) if s in steps_done]
    if len(mandatory_done) < MANDATORY_STEP_COUNT:
        raise ValueError(
            f"Cannot finalize: {MANDATORY_STEP_COUNT} mandatory captures required, "
            f"{len(mandatory_done)} present."
        )

    overall = float(sum((c.quality_score or 0.0) for c in captures) / len(captures))
    min_quality = get_float(db, "enroll.min_overall_quality")
    warning = None
    if overall < min_quality:
        warning = (
            f"Overall enrollment quality {overall:.3f} is below the recommended "
            f"minimum {min_quality:.3f}. Re-enrollment is recommended."
        )

    employee.is_enrolled = True
    employee.enrolled_at = datetime.now(timezone.utc)
    employee.enrollment_quality = overall
    db.commit()
    from app.engine.service import service
    service.invalidate_gallery()

    write_audit(
        db,
        action="enrollment.finalize",
        affected_id=employee.id,
        source="api",
        actor=api_key_label,
        new_value={
            "overall_quality": overall,
            "steps_captured": sorted(steps_done),
        },
        note=warning,
        commit=True,
    )
    return FinalizeResult(
        is_enrolled=True,
        overall_quality=overall,
        captures=[_step_summary(c) for c in captures],
        warning=warning,
    )


def verify(
    frame: np.ndarray,
    employee: Employee,
    provider: FaceProvider,
    db: Session,
) -> VerifyResult:
    """Sanity-check an image against this employee's embeddings (§3.3.23)."""
    threshold = get_float(db, "engine.similarity_threshold")
    detections = provider.detect(frame, with_embeddings=True)
    if not detections or detections[0].embedding is None:
        return VerifyResult(face_detected=False, threshold=threshold, matched=False)
    embedding = detections[0].embedding
    captures = _list_captures(db, employee.id)
    if not captures:
        return VerifyResult(face_detected=True, best_score=None, threshold=threshold, matched=False)
    best = max(cosine_similarity(embedding, np.array(json.loads(c.embedding_json), dtype=np.float32)) for c in captures)
    return VerifyResult(face_detected=True, best_score=round(best, 4), threshold=threshold, matched=best >= threshold)


def remove_face(db: Session, employee: Employee, api_key_label: str | None) -> None:
    """Delete all embeddings + images, reset enrollment status (§3.3.22)."""
    from app.engine.service import service
    from app.services.audit import write_audit

    captures = _list_captures(db, employee.id)
    for c in captures:
        try:
            (ENROLLMENT_DIR / c.image_path).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(c)
    employee.is_enrolled = False
    employee.enrolled_at = None
    employee.enrollment_quality = None
    db.commit()
    service.invalidate_gallery()
    write_audit(
        db,
        action="enrollment.remove",
        affected_id=employee.id,
        source="api",
        actor=api_key_label,
        note="All face embeddings and images removed.",
        commit=True,
    )


def protocol_out() -> dict:
    return {
        "steps": [
            {
                "step": s.step,
                "instruction": s.instruction,
                "yaw": list(s.yaw) if s.yaw else None,
                "pitch": list(s.pitch) if s.pitch else None,
                "mandatory": s.mandatory,
            }
            for s in POSE_STEPS
        ],
        "mandatory_count": MANDATORY_STEP_COUNT,
    }
