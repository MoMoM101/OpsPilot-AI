"""Add durable model request and token accounting.

Revision ID: 20260811_0014
Revises: 20260811_0013
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0014"
down_revision: str | Sequence[str] | None = "20260811_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, default in (
        ("model_request_limit", "20"),
        ("model_requests_used", "0"),
        ("model_input_tokens_used", "0"),
        ("model_output_tokens_used", "0"),
    ):
        op.add_column(
            "investigation_runs",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
    for name in ("model_requests", "model_input_tokens", "model_output_tokens"):
        op.add_column(
            "investigation_checkpoints",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for name in ("model_output_tokens", "model_input_tokens", "model_requests"):
        op.drop_column("investigation_checkpoints", name)
    for name in (
        "model_output_tokens_used",
        "model_input_tokens_used",
        "model_requests_used",
        "model_request_limit",
    ):
        op.drop_column("investigation_runs", name)
