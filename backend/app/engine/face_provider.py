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
        min_det_score: float = 0.0,
    ) -> list[FaceDetection]: ...


def _have_insightface() -> bool:
    try:
        import insightface  # noqa: F401
        return True
    except Exception:
        return False


def parse_insightface_pose(pose) -> tuple[float | None, float | None, float | None]:
    """Map InsightFace's raw `face.pose` to this project's (yaw, pitch, roll).

    InsightFace stores pose as ``[pitch, yaw, roll]`` in degrees. Its yaw
    sign is opposite to this project's convention (SRS §3.3.5):
      - turn LEFT  → negative yaw (InsightFace reports positive)
      - tilt  UP   → positive pitch (already matches; InsightFace reports positive)
    Negating yaw only keeps the backend aligned with the frontend (MediaPipe)
    and the protocol ranges, e.g. step 2 (turn left) targets
    ``yaw ∈ [-45, -30]`` and step 4 (tilt up) targets ``pitch ∈ [20, 35]``.
    Negating pitch as well makes step 4/5 always fail with "Face pose not in
    target range".
    """
    if pose is None or len(pose) < 3:
        return None, None, None
    yaw = -float(pose[1])
    pitch = float(pose[0])
    roll = float(pose[2])
    return yaw, pitch, roll


def _resolve_providers(ctx_id: int) -> list[str]:
    """Pick ONNX Runtime execution providers for the requested device.

    GPU acceleration requires ``onnxruntime-gpu`` (a separate wheel from
    ``onnxruntime``); only enable CUDA when the GPU-capable wheel is actually
    importable, otherwise ONNX Runtime would fall back to CPU silently but
    log a warning on every session creation. The CPU wheel is always
    available, so it always ends the list as a final fallback.
    """
    requested = ctx_id >= 0
    if not requested:
        return ["CPUExecutionProvider"]
    try:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
    except Exception:
        return ["CPUExecutionProvider"]
    providers: list[str] = []
    if "CUDAExecutionProvider" in available:
        providers.append("CUDAExecutionProvider")
    if "CPUExecutionProvider" in available:
        providers.append("CPUExecutionProvider")
    return providers or ["CPUExecutionProvider"]


class InsightFaceProvider:
    """Real provider backed by InsightFace buffalo_l.

    Frames from OpenCV (cv2.VideoCapture, cv2.imread) are BGR — which is the
    colour space the buffalo_l weights were trained on (the official
    InsightFace examples feed cv2 frames directly). We therefore pass frames
    through ``app.get()`` *without* any BGR↔RGB conversion. Converting to RGB
    here swaps the red/blue channels and measurably lowers both RetinaFace
    detection confidence and ArcFace embedding quality.
    """

    def __init__(
        self,
        ctx_id: int | None = None,
        *,
        num_threads: int = 2,
        providers: list[str] | None = None,
    ) -> None:
        import os

        from insightface.app import FaceAnalysis

        # ctx_id selects CPU (-1) vs GPU (>=0). Defaults to the FA_FACE_CTX_ID
        # env var so deployments can opt into GPU without code changes; falls
        # back to CPU. (GPU also requires onnxruntime-gpu; see _resolve_providers.)
        if ctx_id is None:
            ctx_id = int(os.environ.get("FA_FACE_CTX_ID", "-1"))
        if providers is None:
            providers = _resolve_providers(ctx_id)

        # Cap ONNX Runtime thread pools BEFORE loading any model.
        # InsightFace creates its ONNX sessions internally during prepare();
        # the only reliable way to limit threads is via environment variables
        # and the global ONNX Runtime default, set before the first session.
        os.environ.setdefault("OMP_NUM_THREADS", str(num_threads))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(num_threads))
        try:
            import onnxruntime as ort
            ort.set_default_logger_severity(3)
        except Exception:
            pass

        self.ctx_id = ctx_id
        self.app = FaceAnalysis(
            name="buffalo_l",
            root=str(MODEL_DIR),
            providers=providers,
        )
        self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        logger.info(
            "InsightFace buffalo_l loaded (ctx_id=%s, providers=%s, det_size=(640,640), num_threads=%d)",
            ctx_id, providers, num_threads,
        )

    def detect(
        self,
        frame: np.ndarray,
        *,
        with_embeddings: bool = True,
        min_size_ratio: float = 0.0,
        frame_width: int | None = None,
        min_det_score: float = 0.0,
    ) -> list[FaceDetection]:
        # NOTE: do NOT convert BGR→RGB — see the class docstring. buffalo_l
        # is trained on cv2 (BGR) frames; passing RGB swaps channels and
        # degrades both detection and embedding quality.
        faces = self.app.get(frame)
        out: list[FaceDetection] = []
        width = frame_width or frame.shape[1]
        min_w = min_size_ratio * width
        for f in faces:
            # Drop low-confidence detections up front. RetinaFace returns
            # every candidate bbox with a score; keeping ghost detections
            # pollutes the gallery (enrollment) and inflates false matches
            # (recognition), because ArcFace still embeds them.
            score = float(f.det_score)
            if score < min_det_score:
                continue
            x1, y1, x2, y2 = (int(v) for v in f.bbox)
            if (x2 - x1) < min_w:
                continue
            yaw = pitch = roll = None
            pose = getattr(f, "pose", None)
            if pose is not None:
                yaw, pitch, roll = parse_insightface_pose(pose)
            emb = None
            if with_embeddings and f.embedding is not None:
                # Explicit L2-normalise so cosine distance / pgvector ops are
                # well-defined even if a future model pack returns raw vectors.
                emb = np.asarray(f.embedding, dtype=np.float32).reshape(-1)
                n = float(np.linalg.norm(emb))
                if n > 0:
                    emb = emb / n
            out.append(
                FaceDetection(
                    bbox=(x1, y1, x2, y2),
                    score=score,
                    embedding=emb,
                    yaw=yaw,
                    pitch=pitch,
                    roll=roll,
                )
            )
        # Highest-confidence first — multi-face frames process the primary
        # subject before lower-quality secondary detections.
        out.sort(key=lambda d: d.score, reverse=True)
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
        min_det_score: float = 0.0,
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
