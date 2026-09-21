from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0003"
down_revision: str | Sequence[str] | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_drafts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("change_event_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('proposed', 'approved', 'rejected')",
            name="ck_verification_drafts_status",
        ),
        sa.CheckConstraint(
            "origin in ('ai', 'manual')", name="ck_verification_drafts_origin"
        ),
        sa.ForeignKeyConstraint(
            ["change_event_id"], ["change_events.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "change_event_id", name="uq_verification_drafts_change_event"
        ),
    )
    op.create_table(
        "verification_draft_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("change_event_id", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('proposed', 'approved', 'rejected')",
            name="ck_verification_draft_history_status",
        ),
        sa.CheckConstraint(
            "event in ('generated', 'edited', 'approved', 'rejected')",
            name="ck_verification_draft_history_event",
        ),
        sa.ForeignKeyConstraint(
            ["change_event_id"], ["change_events.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("verification_draft_history")
    op.drop_table("verification_drafts")
