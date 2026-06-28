"""Cosine similarity matching against enrolled embeddings (SRS §3.4.5).

Implemented now (it is pure numpy) but wired into the recognition
pipeline in a later slice. The engine service in this slice uses
`get_provider().detect()` to prove the provider path end-to-end.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _l2_normalise(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = _l2_normalise(a.astype(np.float32))
    b = _l2_normalise(b.astype(np.float32))
    return float(np.dot(a, b))


@dataclass
class MatchResult:
    employee_id: str
    score: float


def best_match(embedding: np.ndarray, gallery: list[tuple[str, np.ndarray]]) -> MatchResult | None:
    """Return the highest-scoring (employee_id, score) from the gallery.

    `gallery` is a list of (employee_id, embedding) tuples. Returns None
    when the gallery is empty.
    """
    if not gallery:
        return None
    best_eid, best_emb = max(
        ((eid, emb) for eid, emb in gallery),
        key=lambda item: cosine_similarity(embedding, item[1]),
    )
    return MatchResult(employee_id=best_eid, score=cosine_similarity(embedding, best_emb))
