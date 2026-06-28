"""Face detection / embedding / pose provider (SRS §3.3, §3.4).

Backend: InsightFace `buffalo_l` (ArcFace + RetinaFace). InsightFace is
not installed in core deps (it lags the latest CPython wheels). We
import lazily and fall back to a `StubFaceProvider` so the rest of the
app runs during development and in tests without the ~330MB model.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.config import MODEL_DIR

logger = logging.getLogger(__name__)


@dataclass
class FaceDetection:
    """One detected face in a frame."""

    # Axis-aligned bounding box in pixel coords: (x1, y1, x2, y2).
    bbox: tuple[int, int, int, int]
    # Detector confidence (0..1).
    score: float
    # 512-dim ArcFace embedding (L2-normalised) or None if not requested.
    embedding: np.ndarray | None
    # Head pose angles in degrees (yaw, pitch, roll). Used in enrollment.
    yaw: float | None
    pitch: float | None
    roll: float | None


class FaceProvider(Protocol):
    """Provider interface the engine depends on."""

    def detect(
        self,
        frame: np.ndarray,
        *,
        with_embeddings: bool = True,
        min_size_ratio: float = 0.0,
        frame_width: int | None = None,
    ) -> list[FaceDetection]: ...


def _have_insightface() -> bool:
    try:
        import insightface  # noqa: F401
        return True
    except Exception:
        return False


def parse_insightface_pose(pose) -> tuple[float | None, float | None, float | None]:
    """Map InsightFace's raw `face.pose` to this project's (yaw, pitch, roll).

    InsightFace stores pose as ``[pitch, yaw, roll]`` in degrees, with sign
    conventions opposite to this project's (SRS §3.3.5):
      - turn LEFT  → negative yaw   (InsightFace reports positive)
      - tilt  UP   → positive pitch (InsightFace reports negative)
    Negating yaw and pitch keeps the backend aligned with the frontend
    (MediaPipe) and the protocol ranges, e.g. step 2 (turn left) targets
    ``yaw ∈ [-45, -30]``. Without this, step 2 and steps 4/5 always fail
    with "Face pose not in target range".
    """
    if pose is None or len(pose) < 3:
        return None, None, None
    yaw = -float(pose[1])
    pitch = -float(pose[0])
    roll = float(pose[2])
    return yaw, pitch, roll


class InsightFaceProvider:
    """Real provider backed by InsightFace buffalo_l."""

    def __init__(self, ctx_id: int = -1) -> None:
        import insightface
        from insightface.app import FaceAnalysis

        self.app = FaceAnalysis(name="buffalo_l", root=str(MODEL_DIR), providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        logger.info("InsightFace buffalo_l loaded (ctx_id=%s)", ctx_id)

    def detect(
        self,
        frame: np.ndarray,
        *,
        with_embeddings: bool = True,
        min_size_ratio: float = 0.0,
        frame_width: int | None = None,
    ) -> list[FaceDetection]:
        rgb = frame[:, :, ::-1]  # BGR → RGB
        faces = self.app.get(rgb)
        out: list[FaceDetection] = []
        width = frame_width or frame.shape[1]
        min_w = min_size_ratio * width
        for f in faces:
            x1, y1, x2, y2 = (int(v) for v in f.bbox)
            if (x2 - x1) < min_w:
                continue
            yaw = pitch = roll = None
            pose = getattr(f, "pose", None)
            if pose is not None:
                yaw, pitch, roll = parse_insightface_pose(pose)
            out.append(
                FaceDetection(
                    bbox=(x1, y1, x2, y2),
                    score=float(f.det_score),
                    embedding=np.asarray(f.embedding, dtype=np.float32) if with_embeddings and f.embedding is not None else None,
                    yaw=yaw,
                    pitch=pitch,
                    roll=roll,
                )
            )
        return out


class StubFaceProvider:
    """Fallback provider that detects no faces.

    Useful when InsightFace isn't installed (e.g. on a CPython version
    lacking wheels) or during tests. The engine still reads frames,
    tracks FPS, and reports camera online/offline — only face matching
    is inert.
    """

    def detect(
        self,
        frame: np.ndarray,
        *,
        with_embeddings: bool = True,
        min_size_ratio: float = 0.0,
        frame_width: int | None = None,
    ) -> list[FaceDetection]:
        return []


_PROVIDER: FaceProvider | None = None


def get_provider() -> FaceProvider:
    global _PROVIDER
    if _PROVIDER is None:
        if _have_insightface():
            try:
                _PROVIDER = InsightFaceProvider()
            except Exception:
                logger.exception("InsightFace init failed; falling back to stub provider")
                _PROVIDER = StubFaceProvider()
        else:
            logger.warning(
                "insightface not installed — using StubFaceProvider. "
                "Install with: pip install insightface onnxruntime"
            )
            _PROVIDER = StubFaceProvider()
    return _PROVIDER


def reset_provider() -> None:
    """Test hook to force re-evaluation of provider availability."""
    global _PROVIDER
    _PROVIDER = None
