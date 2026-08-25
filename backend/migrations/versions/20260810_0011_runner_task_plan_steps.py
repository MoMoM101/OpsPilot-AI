"""Link Runner tasks to investigation plan steps.

Revision ID: 20260810_0011
Revises: 20260810_0010
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0011"
down_revision: str | Sequence[str] | None = "20260810_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runner_tasks") as batch_op:
        batch_op.add_column(sa.Column("plan_step_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_runner_tasks_plan_step_id_plan_steps",
            "plan_steps",
            ["plan_step_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_runner_tasks_plan_step_id", "runner_tasks", ["plan_step_id"])


def downgrade() -> None:
    op.drop_index("ix_runner_tasks_plan_step_id", table_name="runner_tasks")
    with op.batch_alter_table("runner_tasks") as batch_op:
        batch_op.drop_constraint(
            "fk_runner_tasks_plan_step_id_plan_steps",
            type_="foreignkey",
        )
        batch_op.drop_column("plan_step_id")
