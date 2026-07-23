"""pgvector HNSW index on face_embeddings

Revision ID: a2c7e5f1d904
Revises: e91d131e8b03
Create Date: 2026-07-01 12:00:00.000000
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a2c7e5f1d904"
down_revision = "e91d131e8b03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add native vector column (nullable first so existing rows don't break)
    op.execute("ALTER TABLE face_embeddings ADD COLUMN embedding_vec vector(512)")

    # 3. Populate from legacy JSON column
    op.execute(
        "UPDATE face_embeddings SET embedding_vec = embedding_json::vector WHERE embedding_vec IS NULL"
    )

    # 4. Make NOT NULL now that all rows are populated
    op.execute("ALTER TABLE face_embeddings ALTER COLUMN embedding_vec SET NOT NULL")

    # 5. Create HNSW index for approximate nearest-neighbour cosine search
    op.execute(
        """
        CREATE INDEX idx_face_embeddings_vec_hnsw
          ON face_embeddings USING hnsw (embedding_vec vector_cosine_ops)
          WITH (m = 16, ef_construction = 200)
        """
    )


def downgrade() -> None:
    # 1. Drop HNSW index
    op.execute("DROP INDEX IF EXISTS idx_face_embeddings_vec_hnsw")

    # 2. Drop vector column
    op.execute("ALTER TABLE face_embeddings DROP COLUMN embedding_vec")

    # 3. Drop pgvector extension (only if no other tables use it)
    op.execute("DROP EXTENSION IF EXISTS vector")
