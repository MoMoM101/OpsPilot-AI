"""Initial control-plane tables.

Revision ID: 20260807_0001
Revises:
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

incident_status = sa.Enum(
    "DETECTED",
    "CORRELATING",
    "INVESTIGATING",
    "DIAGNOSED",
    "PLANNING",
    "WAITING_APPROVAL",
    "REMEDIATING",
    "VERIFYING",
    "RESOLVED",
    "CLOSED",
    "OBSERVABILITY_LOST",
    "NEEDS_HUMAN",
    "MITIGATED_NOT_RESOLVED",
    "FAILED",
    "CANCELLED",
    name="incident_status",
    native_enum=False,
)
incident_severity = sa.Enum(
    "critical",
    "high",
    "medium",
    "low",
    name="incident_severity",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "environments",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_environments"),
        sa.UniqueConstraint("name", name="uq_environments_name"),
        sa.UniqueConstraint("slug", name="uq_environments_slug"),
    )
    op.create_index("ix_environments_slug", "environments", ["slug"])
    op.create_table(
        "resources",
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("criticality", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_resources_environment_id_environments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
        sa.UniqueConstraint("environment_id", "name", name="uq_resources_environment_id"),
    )
    op.create_index("ix_resources_environment_id", "resources", ["environment_id"])
    op.create_index("ix_resources_kind", "resources", ["kind"])
    op.create_table(
        "resource_relations",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["resources.id"],
            name="fk_resource_relations_source_id_resources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["resources.id"],
            name="fk_resource_relations_target_id_resources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resource_relations"),
        sa.UniqueConstraint(
            "source_id",
            "target_id",
            "relation_type",
            name="uq_resource_relations_source_id",
        ),
    )
    op.create_table(
        "incidents",
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", incident_status, nullable=False),
        sa.Column("severity", incident_severity, nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.String(100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name="fk_incidents_resource_id_resources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index("ix_incidents_resource_id", "incidents", ["resource_id"])
    op.create_index(
        "ix_incidents_severity_created_at",
        "incidents",
        ["severity", "created_at"],
    )
    op.create_index(
        "ix_incidents_status_updated_at",
        "incidents",
        ["status", "updated_at"],
    )
    op.create_table(
        "incident_events",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_events_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_events"),
    )
    op.create_index(
        "ix_incident_events_incident_occurred",
        "incident_events",
        ["incident_id", "occurred_at"],
    )
    op.create_table(
        "evidence",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_evidence_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_incident_id", "evidence", ["incident_id"])


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("incident_events")
    op.drop_table("incidents")
    op.drop_table("resource_relations")
    op.drop_table("resources")
    op.drop_table("environments")
