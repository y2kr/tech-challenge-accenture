from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "studies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("nct_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sponsor", sa.String(), nullable=False),
        sa.Column("overall_status", sa.String(), nullable=False),
        sa.Column("last_source_update", sa.Date(), nullable=False),
        sa.Column(
            "raw_current", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("current_snapshot_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("source in ('live', 'replay')", name="ck_studies_source"),
        sa.UniqueConstraint("source", "nct_id", name="uq_studies_source_nct_id"),
    )
    op.create_table(
        "study_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("study_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "normalised_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "study_id", "content_hash", name="uq_study_snapshots_study_hash"
        ),
    )
    op.create_foreign_key(
        "fk_studies_current_snapshot_id",
        "studies",
        "study_snapshots",
        ["current_snapshot_id"],
        ["id"],
    )
    op.create_table(
        "change_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("study_id", sa.BigInteger(), nullable=False),
        sa.Column("before_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("after_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column(
            "structured_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="unreviewed",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["before_snapshot_id"], ["study_snapshots.id"]),
        sa.ForeignKeyConstraint(["after_snapshot_id"], ["study_snapshots.id"]),
    )


def downgrade() -> None:
    op.drop_table("change_events")
    op.drop_constraint("fk_studies_current_snapshot_id", "studies", type_="foreignkey")
    op.drop_table("study_snapshots")
    op.drop_table("studies")
