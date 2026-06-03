"""add run collaboration memory tables

Revision ID: 20260603_run_collab_memory
Revises: 20260527_add_skills
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260603_run_collab_memory"
down_revision = "20260527_add_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("from_agent_id", sa.String(), nullable=True),
        sa.Column("to_agent_id", sa.String(), nullable=True),
        sa.Column("step_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("outputs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("assumptions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("risks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("artifact_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_handoffs_run_id", "agent_handoffs", ["run_id"], unique=False)
    op.create_index("ix_agent_handoffs_job_id", "agent_handoffs", ["job_id"], unique=False)
    op.create_index(
        "ix_agent_handoffs_from_agent_id",
        "agent_handoffs",
        ["from_agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_handoffs_to_agent_id",
        "agent_handoffs",
        ["to_agent_id"],
        unique=False,
    )
    op.create_index("ix_agent_handoffs_step_id", "agent_handoffs", ["step_id"], unique=False)
    op.create_index("ix_agent_handoffs_task_id", "agent_handoffs", ["task_id"], unique=False)
    op.create_index("ix_agent_handoffs_created_at", "agent_handoffs", ["created_at"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("step_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("producing_agent_id", sa.String(), nullable=True),
        sa.Column("artifact_type", sa.String(), nullable=False, server_default="file"),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_id", "path", name="uq_artifacts_run_step_path"),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"], unique=False)
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"], unique=False)
    op.create_index("ix_artifacts_step_id", "artifacts", ["step_id"], unique=False)
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"], unique=False)
    op.create_index(
        "ix_artifacts_producing_agent_id",
        "artifacts",
        ["producing_agent_id"],
        unique=False,
    )
    op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"], unique=False)
    op.create_index("ix_artifacts_path", "artifacts", ["path"], unique=False)
    op.create_index("ix_artifacts_storage_key", "artifacts", ["storage_key"], unique=False)
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"], unique=False)
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_artifacts_created_at", table_name="artifacts")
    op.drop_index("ix_artifacts_sha256", table_name="artifacts")
    op.drop_index("ix_artifacts_storage_key", table_name="artifacts")
    op.drop_index("ix_artifacts_path", table_name="artifacts")
    op.drop_index("ix_artifacts_artifact_type", table_name="artifacts")
    op.drop_index("ix_artifacts_producing_agent_id", table_name="artifacts")
    op.drop_index("ix_artifacts_task_id", table_name="artifacts")
    op.drop_index("ix_artifacts_step_id", table_name="artifacts")
    op.drop_index("ix_artifacts_job_id", table_name="artifacts")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("ix_agent_handoffs_created_at", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_task_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_step_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_to_agent_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_from_agent_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_job_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_run_id", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")
