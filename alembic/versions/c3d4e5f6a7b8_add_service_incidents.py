"""add service_incidents + service_incident_updates

Revision ID: c3d4e5f6a7b8
Revises: 7c2e9a4f1b83
Create Date: 2026-07-07

Backing store for the public status page (GET /api/status). SQLite dev/test
DBs get these tables via Base.metadata.create_all; Postgres (prod) needs this
migration under `alembic upgrade head`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "7c2e9a4f1b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_incidents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="investigating"),
        sa.Column("impact", sa.String(length=20), nullable=False, server_default="minor"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "service_incident_updates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["service_incidents.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_service_incident_updates_incident_id",
        "service_incident_updates",
        ["incident_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_incident_updates_incident_id",
        table_name="service_incident_updates",
    )
    op.drop_table("service_incident_updates")
    op.drop_table("service_incidents")
