"""Guided enrollment pose protocol (SRS §3.3.5) and image-quality
assessment (§3.3.14).

The protocol is encoded as data so the frontend can fetch it once and
drive the UI, while the backend uses the same ranges to validate each
captured frame.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PoseStep:
    step: int
    instruction: str
    # (low, high) inclusive range in degrees, or None if the axis is unconstrained.
    yaw: tuple[int, int] | None
    pitch: tuple[int, int] | None
    # Whether this step is mandatory. Steps 1–5 are mandatory; 6–7 optional (§3.3.12).
    mandatory: bool = True


# SRS §3.3.5 — the fixed seven-step sequence.
POSE_STEPS: list[PoseStep] = [
    PoseStep(1, "Look straight at the camera",       yaw=(-15, 15),  pitch=(-15, 15)),
    PoseStep(2, "Slowly turn your head to the LEFT",  yaw=(-45, -30), pitch=None),
    PoseStep(3, "Slowly turn your head to the RIGHT", yaw=(30, 45),   pitch=None),
    PoseStep(4, "Tilt your head slightly UPWARD",    yaw=None,       pitch=(20, 35)),
    PoseStep(5, "Tilt your head slightly DOWNWARD",  yaw=None,       pitch=(-35, -20)),
    PoseStep(6, "Turn slightly LEFT and look UP",    yaw=(-35, -20), pitch=(15, 25),  mandatory=False),
    PoseStep(7, "Turn slightly RIGHT and look DOWN", yaw=(20, 35),   pitch=(-25, -15), mandatory=False),
]

MANDATORY_STEP_COUNT = sum(1 for s in POSE_STEPS if s.mandatory)  # = 5


def get_step(step: int) -> PoseStep:
    for s in POSE_STEPS:
        if s.step == step:
            return s
    raise ValueError(f"Unknown pose step {step}. Valid range: 1–7.")


def pose_in_range(step: int, yaw: float | None, pitch: float | None) -> bool:
    """True when (yaw, pitch) fall within the target window for `step`."""
    spec = get_step(step)
    if spec.yaw is not None:
        if yaw is None or not (spec.yaw[0] <= yaw <= spec.yaw[1]):
            return False
    if spec.pitch is not None:
        if pitch is None or not (spec.pitch[0] <= pitch <= spec.pitch[1]):
            return False
    return True


@dataclass
class QualityResult:
    """Image-quality assessment outcome (§3.3.14)."""

    score: float  # 0.0 – 1.0 overall
    sharpness: float  # 0.0 – 1.0
    brightness: float  # 0.0 – 1.0
    face_size_ratio: float  # face width / frame width
    acceptable: bool


def assess_quality(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    min_face_ratio: float = 0.10,
    target_face_ratio: float = 0.30,
) -> QualityResult:
    """Score a captured frame (§3.3.14): sharpness, brightness, face size.

    The score is a coarse blend in [0,1]; callers compare against the
    configurable `enroll.quality_threshold` (§3.3.14). The thresholds here
    are calibration constants, not user-facing configuration.
    """
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]

    # --- face size ----------------------------------------------------
    face_w = max(1, x2 - x1)
    face_ratio = face_w / float(w)
    # Maps [min_face_ratio, target_face_ratio] → [0, 1].
    size_score = _clamp((face_ratio - min_face_ratio) / max(1e-6, target_face_ratio - min_face_ratio))

    # --- sharpness (Laplacian variance on the face crop) -------------
    face_crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    if face_crop.size == 0:
        return QualityResult(0.0, 0.0, 0.0, face_ratio, False)
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Empirical: <50 = very blurry, >300 = crisp.
    sharpness = _clamp(lap_var / 300.0)

    # --- brightness ---------------------------------------------------
    # Mean grayscale intensity (0–255); ideal ~110.
    brightness = float(np.mean(gray))
    # Ideal ~110; penalise too dark (<60) or overexposed (>200).
    if brightness < 60 or brightness > 200:
        bright_score = 0.2
    else:
        bright_score = 1.0 - abs(brightness - 110.0) / 110.0
        bright_score = _clamp(bright_score)

    score = round(0.45 * sharpness + 0.20 * bright_score + 0.35 * size_score, 4)
    acceptable = (face_ratio >= min_face_ratio) and sharpness > 0.2 and bright_score > 0.2
    return QualityResult(
        score=score,
        sharpness=round(sharpness, 4),
        brightness=round(bright_score, 4),
        face_size_ratio=round(face_ratio, 4),
        acceptable=acceptable,
    )


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))
