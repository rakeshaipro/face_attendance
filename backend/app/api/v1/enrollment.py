"""Enrollment group (SRS §3.3).

Stateless per-frame protocol: the client uploads a JPEG for each step;
the backend evaluates pose + quality and persists on success.

Endpoints (mounted under /employees/{employee_id}/face)
  GET    /face             enrollment status          §3.3.24
  GET    /face/protocol    the 7 pose steps           §3.3.5
  POST   /face/pose-check  evaluate frame, no save    §3.3.6/§3.3.8/§3.3.14
  POST   /face/capture     validate + save embedding  §3.3.8/§3.3.16/§3.3.18
  GET    /face/captures    summary of current caps    §3.3.19
  POST   /face/finalize    mark enrolled              §3.3.19/§3.3.20
  POST   /face/re-enroll   clear + start over         §3.3.21
  DELETE /face             remove face data           §3.3.22
  POST   /face/verify      sanity-check a frame       §3.3.23
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_readonly, require_readwrite
from app.core.settings_store import get_float
from app.db import get_db
from app.engine.face_provider import get_provider
from app.models import ApiKey, Employee, FaceEmbedding
from app.schemas.common import Envelope
from app.schemas.enrollment import (
    CaptureOut,
    CaptureSummary,
    EnrollmentStatus,
    FinalizeResult,
    PoseCheckResult,
    PoseProtocol,
    VerifyResult,
)
from app.services import enrollment as enrollment_svc

router = APIRouter(prefix="/employees/{employee_id}/face", tags=["enrollment"])


def _employee(db: Session, employee_id: str) -> Employee:
    emp = db.execute(
        select(Employee).where(or_(Employee.id == employee_id, Employee.employee_id == employee_id))
    ).scalar_one_or_none()
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return emp


def _decode(file: UploadFile):
    data = file.file.read()
    return enrollment_svc._decode_image(data)


# --- §3.3.24 status ------------------------------------------------------
@router.get("", response_model=Envelope[EnrollmentStatus])
def status(
    employee_id: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[EnrollmentStatus]:
    emp = _employee(db, employee_id)
    captures = (
        db.execute(
            select(FaceEmbedding).where(FaceEmbedding.employee_id == emp.id).order_by(FaceEmbedding.pose_step)
        )
        .scalars()
        .all()
    )
    return Envelope(
        data=EnrollmentStatus(
            is_enrolled=emp.is_enrolled,
            enrolled_at=emp.enrolled_at,
            capture_count=len(captures),
            steps_captured=[c.pose_step for c in captures],
            overall_quality=emp.enrollment_quality,
        )
    )


# --- §3.3.5 protocol -----------------------------------------------------
@router.get("/protocol", response_model=Envelope[PoseProtocol])
def protocol(
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PoseProtocol]:
    from app.engine.pose import POSE_STEPS, MANDATORY_STEP_COUNT
    from app.schemas.enrollment import PoseStepOut

    return Envelope(
        data=PoseProtocol(
            steps=[
                PoseStepOut(
                    step=s.step,
                    instruction=s.instruction,
                    yaw=s.yaw,
                    pitch=s.pitch,
                    mandatory=s.mandatory,
                )
                for s in POSE_STEPS
            ],
            mandatory_count=MANDATORY_STEP_COUNT,
        )
    )


# --- §3.3.6/§3.3.8/§3.3.14 pose-check -----------------------------------
@router.post("/pose-check", response_model=Envelope[PoseCheckResult])
def pose_check(
    employee_id: str,
    step: int = Query(..., ge=1, le=7),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readwrite),
) -> Envelope[PoseCheckResult]:
    _employee(db, employee_id)  # existence check
    frame = _decode(file)
    min_face_ratio = get_float(db, "engine.min_face_ratio")
    result = enrollment_svc.pose_check(frame, step, get_provider(), min_face_ratio=min_face_ratio)
    return Envelope(data=result)


# --- §3.3.8/§3.3.16/§3.3.18 capture -------------------------------------
@router.post("/capture", response_model=Envelope[CaptureOut])
def capture(
    employee_id: str,
    step: int = Query(..., ge=1, le=7),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[CaptureOut]:
    emp = _employee(db, employee_id)
    frame = _decode(file)
    quality_threshold = get_float(db, "enroll.quality_threshold")
    min_face_ratio = get_float(db, "engine.min_face_ratio")
    try:
        out = enrollment_svc.capture(
            db, emp, frame, step, get_provider(),
            quality_threshold=quality_threshold, min_face_ratio=min_face_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.services.audit import write_audit
    write_audit(
        db, action="enrollment.capture", affected_id=emp.id, source="api",
        actor=api_key.label, new_value={"step": step, "quality": out.quality.score}, commit=True,
    )
    return Envelope(data=out)


# --- §3.3.19 captures summary -------------------------------------------
@router.get("/captures", response_model=Envelope[list[CaptureSummary]])
def captures(
    employee_id: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    emp = _employee(db, employee_id)
    rows = enrollment_svc._list_captures(db, emp.id)
    return Envelope(data=[enrollment_svc._step_summary(r) for r in rows])


# --- per-step capture removal (re-capture a single pose) -----------------
@router.delete("/captures/{step}", response_model=Envelope[dict])
def remove_capture(
    employee_id: str,
    step: int = Path(..., ge=1, le=7),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
):
    emp = _employee(db, employee_id)
    try:
        enrollment_svc.remove_step(db, emp, step, api_key.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Envelope(data={"removed": True, "step": step, "employee_id": emp.employee_id})


# --- §3.3.19/§3.3.20 finalize -------------------------------------------
@router.post("/finalize", response_model=Envelope[FinalizeResult])
def finalize(
    employee_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[FinalizeResult]:
    emp = _employee(db, employee_id)
    try:
        result = enrollment_svc.finalize(db, emp, api_key.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Envelope(data=result)


# --- §3.3.21 re-enroll ---------------------------------------------------
@router.post("/re-enroll", response_model=Envelope[dict])
def re_enroll(
    employee_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
):
    emp = _employee(db, employee_id)
    enrollment_svc.remove_face(db, emp, api_key.label)
    from app.services.audit import write_audit
    write_audit(
        db, action="enrollment.re-enroll", affected_id=emp.id, source="api",
        actor=api_key.label, note="Previous face data cleared; ready for re-enrollment.", commit=True,
    )
    return Envelope(data={"cleared": True, "employee_id": emp.employee_id})


# --- §3.3.22 remove face data -------------------------------------------
@router.delete("", response_model=Envelope[dict])
def remove(
    employee_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
):
    emp = _employee(db, employee_id)
    enrollment_svc.remove_face(db, emp, api_key.label)
    return Envelope(data={"removed": True, "employee_id": emp.employee_id})


# --- §3.3.23 verify ------------------------------------------------------
@router.post("/verify", response_model=Envelope[VerifyResult])
def verify(
    employee_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readwrite),
) -> Envelope[VerifyResult]:
    emp = _employee(db, employee_id)
    frame = _decode(file)
    result = enrollment_svc.verify(frame, emp, get_provider(), db)
    return Envelope(data=result)
