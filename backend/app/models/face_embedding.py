"""Per-pose face embeddings (SRS §3.3.16 – §3.3.18).

Each enrollment step produces one 512-dim ArcFace embedding that is
stored individually (never averaged). At recognition time the detected
face is compared against every stored embedding and the best similarity
wins (§3.3.17).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Pose step 1–7 from the guided enrollment protocol (§3.3.5).
    pose_step: Mapped[int] = mapped_column(Integer, nullable=False)
    # 512-dim embedding serialised as JSON for SQLite portability.
    # (SQLite has no native vector type; cosine sim is done in numpy.)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
