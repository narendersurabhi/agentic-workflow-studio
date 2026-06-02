"""add skills table

Revision ID: 20260527_add_skills
Revises: 20260527_add_users
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_add_skills"
down_revision = "20260527_add_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skills_owner_id", "skills", ["owner_id"])
    op.create_index("ix_skills_built_in", "skills", ["built_in"])
    op.create_index(
        "ix_skills_name_owner_unique",
        "skills",
        [sa.text("LOWER(name)"), "owner_id"],
        unique=True,
        postgresql_where=sa.text("built_in = FALSE"),
    )
    op.create_index(
        "ix_skills_name_builtin_unique",
        "skills",
        [sa.text("LOWER(name)")],
        unique=True,
        postgresql_where=sa.text("built_in = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_skills_name_builtin_unique", table_name="skills")
    op.drop_index("ix_skills_name_owner_unique", table_name="skills")
    op.drop_index("ix_skills_built_in", table_name="skills")
    op.drop_index("ix_skills_owner_id", table_name="skills")
    op.drop_table("skills")
