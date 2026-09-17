from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0002"
down_revision: str | Sequence[str] | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_events",
        sa.Column(
            "ai_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_table(
        "follow_up_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("change_event_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="proposed", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('proposed', 'approved', 'rejected')",
            name="ck_follow_up_actions_status",
        ),
        sa.ForeignKeyConstraint(
            ["change_event_id"], ["change_events.id"], ondelete="CASCADE"
        ),
    )
    op.execute(
        sa.text(
            "insert into follow_up_actions (change_event_id, title) "
            "select id, 'Review other studies involving the same intervention' "
            "from change_events"
        )
    )
    op.execute(
        sa.text(
            "insert into follow_up_actions (change_event_id, title) "
            "select id, 'Assign the change to the relevant pipeline analyst' "
            "from change_events"
        )
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("change_event_id", sa.BigInteger(), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["change_event_id"], ["change_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["follow_up_actions.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_entries")
    op.drop_table("follow_up_actions")
    op.drop_column("change_events", "ai_analysis")
