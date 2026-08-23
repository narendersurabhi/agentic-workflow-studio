"""add agent_checkpoints table

Revision ID: 20260608_agent_checkpoints
Revises: 20260608_agent_def_status
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260608_agent_checkpoints"
down_revision = "20260608_agent_def_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("messages_json", sa.Text(), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("instructions", sa.String(), nullable=True),
        sa.Column("allowed_capability_ids_json", sa.Text(), nullable=True),
        sa.Column("max_steps", sa.Integer(), nullable=True),
        sa.Column("steps_taken", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_checkpoints_run_id", "agent_checkpoints", ["run_id"])
    op.create_index("ix_agent_checkpoints_task_id", "agent_checkpoints", ["task_id"])
    op.create_index("ix_agent_checkpoints_status", "agent_checkpoints", ["status"])
    op.create_index("ix_agent_checkpoints_expires_at", "agent_checkpoints", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_checkpoints_expires_at", table_name="agent_checkpoints")
    op.drop_index("ix_agent_checkpoints_status", table_name="agent_checkpoints")
    op.drop_index("ix_agent_checkpoints_task_id", table_name="agent_checkpoints")
    op.drop_index("ix_agent_checkpoints_run_id", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
