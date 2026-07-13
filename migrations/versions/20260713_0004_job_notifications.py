"""Add persisted job notification delivery state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_notifications" not in inspector.get_table_names():
        op.create_table(
            "job_notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("evaluation_id", sa.Integer(), nullable=False),
            sa.Column("channel_type", sa.String(30), nullable=False),
            sa.Column("evaluation_fingerprint", sa.String(64), nullable=False),
            sa.Column("status", sa.String(7), nullable=False),
            sa.Column("provider_response_id", sa.String(255), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_category", sa.String(50), nullable=True),
            sa.Column("error_summary", sa.String(500), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["evaluation_id"], ["job_evaluations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "channel_type",
                "evaluation_fingerprint",
                name="channel_evaluation_fingerprint",
            ),
        )
        inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("job_notifications")}
    for name, columns in (
        ("ix_job_notifications_job_id", ["job_id"]),
        ("ix_job_notifications_evaluation_id", ["evaluation_id"]),
        ("ix_job_notifications_status", ["status"]),
    ):
        if name not in indexes:
            op.create_index(name, "job_notifications", columns)


def downgrade() -> None:
    if "job_notifications" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("job_notifications")
