"""Users and sign-in sessions

Revision ID: 002_users_and_sessions
Revises: 001_initial_schema
Create Date: 2026-11-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_users_and_sessions"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), primary_key=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_username", "auth_sessions", ["username"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_username", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
