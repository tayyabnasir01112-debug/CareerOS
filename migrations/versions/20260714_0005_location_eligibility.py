"""Persist deterministic location eligibility and evaluation priority."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260713_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("jobs")}
    with op.batch_alter_table("jobs") as batch:
        if "location_classification" not in columns:
            batch.add_column(
                sa.Column(
                    "location_classification",
                    sa.String(39),
                    nullable=False,
                    server_default="UNCLEAR",
                )
            )
        if "location_evidence" not in columns:
            batch.add_column(
                sa.Column("location_evidence", sa.JSON(), nullable=False, server_default="[]")
            )
        if "deterministic_pre_score" not in columns:
            batch.add_column(
                sa.Column(
                    "deterministic_pre_score", sa.Integer(), nullable=False, server_default="0"
                )
            )
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("jobs")}
    if "ix_jobs_location_classification" not in indexes:
        op.create_index("ix_jobs_location_classification", "jobs", ["location_classification"])
    if "ix_jobs_deterministic_pre_score" not in indexes:
        op.create_index("ix_jobs_deterministic_pre_score", "jobs", ["deterministic_pre_score"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("jobs")}
    with op.batch_alter_table("jobs") as batch:
        if "ix_jobs_deterministic_pre_score" in indexes:
            batch.drop_index("ix_jobs_deterministic_pre_score")
        if "ix_jobs_location_classification" in indexes:
            batch.drop_index("ix_jobs_location_classification")
        columns = {item["name"] for item in inspector.get_columns("jobs")}
        for name in (
            "deterministic_pre_score",
            "location_evidence",
            "location_classification",
        ):
            if name in columns:
                batch.drop_column(name)
