"""add agent coordination tables (registry + locks)

Revision ID: 20260603_agent_coordination
Revises: 20260603_run_collab_memory
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260603_agent_coordination"
down_revision = "20260603_run_collab_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="idle"),
        sa.Column("assigned_task_id", sa.String(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "agent_id", name="uq_agent_registry_run_agent"),
    )
    op.create_index("ix_agent_registry_run_id", "agent_registry", ["run_id"], unique=False)
    op.create_index("ix_agent_registry_job_id", "agent_registry", ["job_id"], unique=False)
    op.create_index("ix_agent_registry_agent_id", "agent_registry", ["agent_id"], unique=False)
    op.create_index("ix_agent_registry_role", "agent_registry", ["role"], unique=False)
    op.create_index("ix_agent_registry_status", "agent_registry", ["status"], unique=False)
    op.create_index(
        "ix_agent_registry_assigned_task_id",
        "agent_registry",
        ["assigned_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_registry_last_heartbeat",
        "agent_registry",
        ["last_heartbeat"],
        unique=False,
    )
    op.create_index("ix_agent_registry_created_at", "agent_registry", ["created_at"], unique=False)
    op.create_index("ix_agent_registry_updated_at", "agent_registry", ["updated_at"], unique=False)

    op.create_table(
        "agent_locks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("holder_agent_id", sa.String(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "resource", name="uq_agent_locks_run_resource"),
    )
    op.create_index("ix_agent_locks_run_id", "agent_locks", ["run_id"], unique=False)
    op.create_index("ix_agent_locks_job_id", "agent_locks", ["job_id"], unique=False)
    op.create_index("ix_agent_locks_resource", "agent_locks", ["resource"], unique=False)
    op.create_index(
        "ix_agent_locks_holder_agent_id",
        "agent_locks",
        ["holder_agent_id"],
        unique=False,
    )
    op.create_index("ix_agent_locks_acquired_at", "agent_locks", ["acquired_at"], unique=False)
    op.create_index("ix_agent_locks_expires_at", "agent_locks", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_locks_expires_at", table_name="agent_locks")
    op.drop_index("ix_agent_locks_acquired_at", table_name="agent_locks")
    op.drop_index("ix_agent_locks_holder_agent_id", table_name="agent_locks")
    op.drop_index("ix_agent_locks_resource", table_name="agent_locks")
    op.drop_index("ix_agent_locks_job_id", table_name="agent_locks")
    op.drop_index("ix_agent_locks_run_id", table_name="agent_locks")
    op.drop_table("agent_locks")

    op.drop_index("ix_agent_registry_updated_at", table_name="agent_registry")
    op.drop_index("ix_agent_registry_created_at", table_name="agent_registry")
    op.drop_index("ix_agent_registry_last_heartbeat", table_name="agent_registry")
    op.drop_index("ix_agent_registry_assigned_task_id", table_name="agent_registry")
    op.drop_index("ix_agent_registry_status", table_name="agent_registry")
    op.drop_index("ix_agent_registry_role", table_name="agent_registry")
    op.drop_index("ix_agent_registry_agent_id", table_name="agent_registry")
    op.drop_index("ix_agent_registry_job_id", table_name="agent_registry")
    op.drop_index("ix_agent_registry_run_id", table_name="agent_registry")
    op.drop_table("agent_registry")
