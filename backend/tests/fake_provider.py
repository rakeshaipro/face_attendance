"""Synthetic FaceProvider for tests.

Generates deterministic faces with known pose + embedding, so the
enrollment logic can be exercised without InsightFace or a camera.
Frame content is a clean high-contrast synthetic image so the
sharpness/brightness quality checks pass.
"""
from __future__ import annotations

import numpy as np

from app.engine.face_provider import FaceDetection


class FakeFaceProvider:
    """Detects exactly one face with a configurable pose + embedding."""

    def __init__(self, *, yaw: float = 0.0, pitch: float = 0.0,
                 embedding: np.ndarray | None = None,
                 score: float = 0.95) -> None:
        self.yaw = yaw
        self.pitch = pitch
        self.score = score
        # Default: a unique-ish 512-dim unit-ish vector per instance.
        self.embedding = embedding if embedding is not None else _seed_embedding(0)

    def detect(self, frame, *, with_embeddings: bool = True,
               min_size_ratio: float = 0.0, frame_width: int | None = None,
               min_det_score: float = 0.0):
        h, w = frame.shape[:2]
        # A centred face occupying ~40% of frame width.
        fw = int(w * 0.40)
        x1 = (w - fw) // 2
        x2 = x1 + fw
        fh = int(h * 0.40)
        y1 = (h - fh) // 2
        y2 = y1 + fh
        # Honour the min-size + detection-score filters the same way the real
        # provider does (§3.4.11).
        if fw < min_size_ratio * w:
            return []
        if self.score < min_det_score:
            return []
        return [
            FaceDetection(
                bbox=(x1, y1, x2, y2),
                score=self.score,
                embedding=self.embedding if with_embeddings else None,
                yaw=self.yaw,
                pitch=self.pitch,
                roll=0.0,
            )
        ]


class NoFaceProvider:
    """Provider that detects no faces — used for negative-path tests."""

    def detect(self, frame, *, with_embeddings: bool = True,
               min_size_ratio: float = 0.0, frame_width: int | None = None,
               min_det_score: float = 0.0):
        return []


def _seed_embedding(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


def make_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """A sharp, well-lit synthetic BGR frame (passes quality checks)."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Checkerboard-ish high-frequency pattern → high Laplacian variance.
    for y in range(height):
        for x in range(width):
            img[y, x] = 255 if ((x // 4 + y // 4) % 2 == 0) else 0
    # Mid-grey overlay to keep brightness near ideal (~110).
    return (img // 3).astype(np.uint8)


def jpeg_bytes(frame: np.ndarray) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()
