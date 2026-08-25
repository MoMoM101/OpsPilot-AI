"""Enforce one-time Action authorization consumption.

Revision ID: 20260814_0030
Revises: 20260814_0029
Create Date: 2026-08-14
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0030"
down_revision: str | Sequence[str] | None = "20260814_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _duplicate_action_authorizations(connection: Any) -> list[tuple[str, str, list[str]]]:
    duplicates: list[tuple[str, str, list[str]]] = []
    for column in ("policy_decision_id", "approval_id"):
        rows = connection.execute(
            sa.text(
                f"""
                SELECT {column} AS authorization_id, id, created_at
                FROM action_requests
                WHERE {column} IS NOT NULL
                  AND {column} IN (
                      SELECT {column}
                      FROM action_requests
                      WHERE {column} IS NOT NULL
                      GROUP BY {column}
                      HAVING COUNT(*) > 1
                  )
                ORDER BY {column}, created_at, id
                """
            )
        ).mappings()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(str(row["authorization_id"]), []).append(str(row["id"]))
        duplicates.extend(
            (column, authorization_id, action_ids)
            for authorization_id, action_ids in grouped.items()
        )
    return duplicates


def _assert_authorizations_are_unique(connection: Any) -> None:
    duplicates = _duplicate_action_authorizations(connection)
    if not duplicates:
        return
    details = "; ".join(
        f"{column}={authorization_id}: keep={action_ids[0]}, remove={action_ids[1:]}"
        for column, authorization_id, action_ids in duplicates
    )
    raise RuntimeError(
        "Cannot enforce one-time Action authorization consumption: historical duplicates "
        f"were found. {details}. Export the duplicate Action aggregates for audit, retain the "
        "earliest Action by (created_at, id), remove the later duplicate aggregate roots, and "
        "rerun this migration. No historical data was changed automatically."
    )


def upgrade() -> None:
    _assert_authorizations_are_unique(op.get_bind())
    op.create_unique_constraint(
        "uq_action_requests_policy_decision_id",
        "action_requests",
        ["policy_decision_id"],
    )
    op.create_unique_constraint(
        "uq_action_requests_approval_id",
        "action_requests",
        ["approval_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_action_requests_approval_id", "action_requests", type_="unique"
    )
    op.drop_constraint(
        "uq_action_requests_policy_decision_id", "action_requests", type_="unique"
    )
