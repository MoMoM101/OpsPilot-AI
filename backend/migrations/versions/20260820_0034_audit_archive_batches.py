"""Add immutable audit archive batch manifests.

Revision ID: 20260820_0034
Revises: 20260815_0033
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0034"
down_revision: str | Sequence[str] | None = "20260815_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_archive_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(length=1000), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_archive_batches"),
        sa.UniqueConstraint("storage_uri", name="uq_audit_archive_batches_storage_uri"),
    )
    op.create_index(
        "ix_audit_archive_batches_created",
        "audit_archive_batches",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_archive_batches_created", table_name="audit_archive_batches")
    op.drop_table("audit_archive_batches")
