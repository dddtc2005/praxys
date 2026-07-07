"""add system_announcements.translations

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-07

Issue #355: bilingual announcements. Adds a per-locale ``translations`` JSON
override ({"zh": {title, body, link_text}}) alongside the canonical English
top-level fields. SQLite dev/test DBs get the column via
Base.metadata.create_all; Postgres (prod) needs this migration under
`alembic upgrade head`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable so existing rows keep a NULL (serialized as {}) and
    # single-language announcements keep working unchanged.
    op.add_column(
        "system_announcements",
        sa.Column("translations", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_announcements", "translations")
