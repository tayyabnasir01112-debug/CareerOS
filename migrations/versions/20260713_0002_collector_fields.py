"""Add normalized collector fields to jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision: str = "20260713_0002"
down_revision: str | None = "20260713_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("jobs")}
    with op.batch_alter_table("jobs") as batch_op:
        if "source_updated_at" not in existing:
            batch_op.add_column(sa.Column("source_updated_at", UTCDateTime(), nullable=True))
        if "collected_at" not in existing:
            batch_op.add_column(sa.Column("collected_at", UTCDateTime(), nullable=True))
        if "salary_text" not in existing:
            batch_op.add_column(sa.Column("salary_text", sa.Text(), nullable=True))
    op.execute("UPDATE jobs SET collected_at = discovered_at WHERE collected_at IS NULL")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("collected_at", existing_type=UTCDateTime(), nullable=False)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("jobs")}
    with op.batch_alter_table("jobs") as batch_op:
        for name in ("salary_text", "collected_at", "source_updated_at"):
            if name in existing:
                batch_op.drop_column(name)
