"""add user preferences column

Revision ID: 20260606_add_user_preferences
Revises: 20260603_add_run_collaboration_memory
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "20260606_add_user_preferences"
down_revision = "20260603_add_run_collaboration_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferences", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferences")
