"""add users table

Revision ID: 20260527_add_users
Revises: 20260422_agent_def_versions
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_add_users"
down_revision = "20260422_agent_def_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
