"""Cosine similarity matching against enrolled embeddings (SRS §3.4.5).

Uses pgvector HNSW index for approximate nearest-neighbour search, replacing
the previous brute-force numpy scan. The query runs inside PostgreSQL via the
`<=>` cosine-distance operator, which leverages the HNSW index on
`face_embeddings.embedding_vec`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding


def _l2_normalise(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Pure-numpy cosine similarity — still used by enrollment verify()."""
    a = _l2_normalise(a.astype(np.float32))
    b = _l2_normalise(b.astype(np.float32))
    return float(np.dot(a, b))


@dataclass
class MatchResult:
    employee_id: str
    score: float


def best_match(embedding: np.ndarray, db: Session) -> MatchResult | None:
    """Return the highest-scoring (employee_id, score) from the gallery.

    Uses pgvector's `<=>` cosine-distance operator with an HNSW index for
    sub-millisecond ANN search at 100+ employee scale.
    """
    vec = embedding.tolist()
    row = db.execute(
        select(
            FaceEmbedding.employee_id,
            (1 - FaceEmbedding.embedding_vec.cosine_distance(vec)).label("similarity"),
        )
        .join(Employee, Employee.id == FaceEmbedding.employee_id)
        .where(Employee.is_active.is_(True), Employee.is_blocked.is_(False), Employee.is_enrolled.is_(True))
        .order_by(FaceEmbedding.embedding_vec.cosine_distance(vec).asc())
        .limit(1)
    ).first()

    if row is None:
        return None
    return MatchResult(employee_id=row.employee_id, score=float(row.similarity))
