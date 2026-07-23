"""Cosine similarity matching against enrolled embeddings (SRS §3.4.5).

Uses pgvector HNSW index for approximate nearest-neighbour search, replacing
the previous brute-force numpy scan. The query runs inside PostgreSQL via the
`<=>` cosine-distance operator, which leverages the HNSW index on
`face_embeddings.embedding_vec`.

Accuracy extras on top of pure ANN:
  - Query vectors are L2-normalised before the search so cosine distance is
    well-defined even if a provider returns un-normalised embeddings.
  - Optional *match margin*: when the best score is within ``margin`` of the
    best score of a *different* employee, the match is rejected as ambiguous.
    This is the standard open-set guard against look-alike false accepts.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding

# How many ANN neighbours to pull when evaluating the second-best employee.
# Must be large enough that a multi-embedding gallery (up to 7 poses/person)
# still surfaces a different employee if one exists.
_TOP_K = 32


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


def best_match(
    embedding: np.ndarray,
    db: Session,
    *,
    margin: float = 0.0,
) -> MatchResult | None:
    """Return the highest-scoring (employee_id, score) from the gallery.

    Uses pgvector's `<=>` cosine-distance operator with an HNSW index for
    sub-millisecond ANN search at 100+ employee scale.

    When ``margin > 0``, also requires that the best employee's score beats
    the best *other* employee's score by at least ``margin``. Ambiguous
    near-ties are returned as ``None`` (caller treats as no-match).
    """
    vec = _l2_normalise(np.asarray(embedding, dtype=np.float32)).tolist()
    rows = db.execute(
        select(
            FaceEmbedding.employee_id,
            (1 - FaceEmbedding.embedding_vec.cosine_distance(vec)).label("similarity"),
        )
        .join(Employee, Employee.id == FaceEmbedding.employee_id)
        .where(Employee.is_active.is_(True), Employee.is_blocked.is_(False), Employee.is_enrolled.is_(True))
        .order_by(FaceEmbedding.embedding_vec.cosine_distance(vec).asc())
        .limit(_TOP_K)
    ).all()

    if not rows:
        return None

    best_emp = rows[0].employee_id
    best_score = float(rows[0].similarity)

    if margin > 0:
        # First row for a *different* employee is their best (rows are
        # ordered by distance ascending). Same-employee pose variants are
        # skipped so multi-pose enrollment doesn't self-suppress.
        second_score: float | None = None
        for row in rows[1:]:
            if row.employee_id != best_emp:
                second_score = float(row.similarity)
                break
        if second_score is not None and (best_score - second_score) < margin:
            return None

    return MatchResult(employee_id=best_emp, score=best_score)
