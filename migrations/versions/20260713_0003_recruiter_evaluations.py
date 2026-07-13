"""Extend job evaluations for structured recruiter results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[sa.Column[object], ...] = (
    sa.Column("evaluator_type", sa.String(50), nullable=True),
    sa.Column("structured_result", sa.JSON(), nullable=True),
    sa.Column("should_prepare_application", sa.Boolean(), nullable=True),
    sa.Column("input_hash", sa.String(64), nullable=True),
    sa.Column("job_content_fingerprint", sa.String(64), nullable=True),
    sa.Column("candidate_profile_fingerprint", sa.String(64), nullable=True),
    sa.Column("preference_fingerprint", sa.String(64), nullable=True),
    sa.Column("prompt_fingerprint", sa.String(64), nullable=True),
    sa.Column("status", sa.String(30), nullable=True),
    sa.Column("api_response_id", sa.String(255), nullable=True),
    sa.Column("input_tokens", sa.Integer(), nullable=True),
    sa.Column("output_tokens", sa.Integer(), nullable=True),
    sa.Column("total_tokens", sa.Integer(), nullable=True),
    sa.Column("duration_ms", sa.Integer(), nullable=True),
    sa.Column("error_category", sa.String(50), nullable=True),
    sa.Column("error_summary", sa.String(500), nullable=True),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("job_evaluations")}
    with op.batch_alter_table("job_evaluations") as batch_op:
        for column in _COLUMNS:
            if column.name not in existing:
                batch_op.add_column(column)
        batch_op.alter_column("match_score", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("recommendation", existing_type=sa.String(50), nullable=True)
        batch_op.alter_column("summary", existing_type=sa.Text(), nullable=True)
    op.execute(
        "UPDATE job_evaluations SET evaluator_type = 'legacy', status = 'success', "
        "should_prepare_application = 0, input_hash = '', job_content_fingerprint = '', "
        "candidate_profile_fingerprint = '', preference_fingerprint = '', "
        "prompt_fingerprint = '' WHERE evaluator_type IS NULL"
    )
    with op.batch_alter_table("job_evaluations") as batch_op:
        for name in (
            "evaluator_type",
            "should_prepare_application",
            "input_hash",
            "job_content_fingerprint",
            "candidate_profile_fingerprint",
            "preference_fingerprint",
            "prompt_fingerprint",
            "status",
        ):
            batch_op.alter_column(name, nullable=False)
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_evaluations")}
    if "ix_job_evaluations_input_hash" not in indexes:
        op.create_index("ix_job_evaluations_input_hash", "job_evaluations", ["input_hash"])
    if "ix_job_evaluations_status" not in indexes:
        op.create_index("ix_job_evaluations_status", "job_evaluations", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_evaluations")}
    for index_name in ("ix_job_evaluations_input_hash", "ix_job_evaluations_status"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="job_evaluations")
    existing = {column["name"] for column in sa.inspect(bind).get_columns("job_evaluations")}
    with op.batch_alter_table("job_evaluations") as batch_op:
        for column in reversed(_COLUMNS):
            if column.name in existing:
                batch_op.drop_column(column.name)
