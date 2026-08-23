"""add status column to agent_definitions

Revision ID: 20260608_agent_def_status
Revises: 20260606_add_user_preferences
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260608_agent_def_status"
down_revision = "20260606_add_user_preferences"
branch_labels = None
depends_on = None

_VALID_STATUSES = ("draft", "published")


def upgrade() -> None:
    op.add_column(
        "agent_definitions",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="draft",
        ),
    )
    op.create_index(
        "ix_agent_definitions_status",
        "agent_definitions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_definitions_status", table_name="agent_definitions")
    op.drop_column("agent_definitions", "status")
