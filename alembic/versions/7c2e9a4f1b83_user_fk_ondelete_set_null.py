"""Set ON DELETE SET NULL on nullable user / invitation foreign keys

Prevents dangling FK references when a user (or an invitation) is deleted, so a
delete can't leave an orphaned reference that PostgreSQL's enforced foreign keys
reject (issue #366). Applies to the nullable references held by rows we keep:

* ``users.demo_of``                  -> users.id
* ``app_config.updated_by``          -> users.id
* ``waitlist_signups.invitation_id`` -> invitations.id

``invitations.used_by`` is deliberately NOT changed here: invitation validity is
"is_active AND used_by IS NULL", so a bare SET NULL would recycle a consumed
code. The application (api/account_deletion.py) nulls used_by AND deactivates
the code together instead.

Revision ID: 7c2e9a4f1b83
Revises: b7f1a2c9d3e4
Create Date: 2026-07-04

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c2e9a4f1b83"
down_revision: Union[str, Sequence[str], None] = "b7f1a2c9d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, referencing column, referenced table) for each FK re-created with
# ON DELETE SET NULL. Each is independent; order does not matter.
_TARGETS = (
    ("users", "demo_of", "users"),
    ("app_config", "updated_by", "users"),
    ("waitlist_signups", "invitation_id", "invitations"),
)


def _pg_fk_name(bind, table: str, column: str) -> str | None:
    """Return the live FK constraint name for ``table.column`` on PostgreSQL.

    The baseline created these FKs unnamed, so PostgreSQL assigned its default
    ``{table}_{column}_fkey``. We look the name up from the catalog rather than
    trusting that convention blindly, so the migration is robust to any drift.
    """
    try:
        return bind.execute(
            sa.text(
                """
                SELECT tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_name = :table
                  AND kcu.column_name = :column
                LIMIT 1
                """
            ),
            {"table": table, "column": column},
        ).scalar()
    except Exception:
        # Offline (--sql) mode has no live connection to query the catalog;
        # the caller falls back to the conventional {table}_{column}_fkey name.
        return None


def _recreate_fks(ondelete: Union[str, None]) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (dev / tests) builds the schema from the ORM via create_all,
        # which already reflects these ondelete rules, and does not enforce FKs.
        # No ALTER is needed or possible without a full table rebuild, so skip.
        return
    for table, column, referent in _TARGETS:
        # Defensively clear any pre-existing orphan so re-adding the constraint
        # cannot fail on a stray dangling row.
        op.execute(
            f"UPDATE {table} SET {column} = NULL "
            f"WHERE {column} IS NOT NULL "
            f"AND {column} NOT IN (SELECT id FROM {referent})"
        )
        name = _pg_fk_name(bind, table, column)
        if name is None and context.is_offline_mode():
            # No live connection to resolve the name in --sql mode; assume the
            # conventional PostgreSQL default so the preview still emits a DROP.
            name = f"{table}_{column}_fkey"
        # Only drop when the constraint actually exists; if it is somehow already
        # absent (online), skip to creating it rather than aborting the startup
        # migration on a "constraint does not exist" error.
        if name is not None:
            op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            referent,
            [column],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    _recreate_fks("SET NULL")


def downgrade() -> None:
    _recreate_fks(None)