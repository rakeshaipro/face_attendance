"""Schemas for the enrollment group (SRS §3.3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PoseStepOut(BaseModel):
    """One step of the guided protocol (§3.3.5)."""

    step: int
    instruction: str
    yaw: tuple[int, int] | None
    pitch: tuple[int, int] | None
    mandatory: bool


class PoseProtocol(BaseModel):
    steps: list[PoseStepOut]
    mandatory_count: int


class QualityOut(BaseModel):
    score: float
    sharpness: float
    brightness: float
    face_size_ratio: float
    acceptable: bool


class PoseCheckResult(BaseModel):
    """Outcome of a single-frame pose+quality check (no save)."""

    face_detected: bool
    face_count: int
    in_range: bool
    yaw: float | None = None
    pitch: float | None = None
    quality: QualityOut | None = None
    reason: str | None = None


class CaptureOut(BaseModel):
    """Outcome of a successful capture (§3.3.8, §3.3.18)."""

    step: int
    quality: QualityOut
    yaw: float | None
    pitch: float | None
    image_path: str


class CaptureSummary(BaseModel):
    """One captured step's summary (§3.3.19)."""

    step: int
    quality: float
    yaw: float | None
    pitch: float | None
    image_path: str


class EnrollmentStatus(BaseModel):
    """GET /face — enrollment status of an employee (§3.3.24)."""

    is_enrolled: bool
    enrolled_at: datetime | None
    capture_count: int
    steps_captured: list[int]
    overall_quality: float | None


class FinalizeResult(BaseModel):
    """POST /face/finalize (§3.3.19, §3.3.20)."""

    is_enrolled: bool
    overall_quality: float
    captures: list[CaptureSummary]
    warning: str | None = None  # set when below min quality (admin may proceed)


class VerifyResult(BaseModel):
    """POST /face/verify (§3.3.23)."""

    face_detected: bool
    best_score: float | None = None
    threshold: float
    matched: bool
