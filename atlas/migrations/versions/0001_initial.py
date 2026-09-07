"""Initial ATLAS schema."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("completeness", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False, server_default=""),
        sa.UniqueConstraint("symbol", "timeframe", "open_time", "source", name="uq_candle_identity"),
    )
    op.create_index("ix_candles_symbol_tf_time", "candles", ["symbol", "timeframe", "open_time"])

    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_quality", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "council_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("market_regime", sa.String(64), nullable=False),
        sa.Column("primary_hypothesis", sa.Text(), nullable=False),
        sa.Column("data_quality", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "specialist_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("specialist", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("bias", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data_quality", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_specialist_assessments_decision_id", "specialist_assessments", ["decision_id"])

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=True),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("mfe", sa.Float(), nullable=True),
        sa.Column("hit_target", sa.Boolean(), nullable=True),
        sa.Column("hit_invalidation", sa.Boolean(), nullable=True),
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_prediction_outcomes_decision_id", "prediction_outcomes", ["decision_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_quality", sa.Float(), nullable=False),
        sa.Column("reasoning_quality", sa.Float(), nullable=False),
        sa.Column("data_quality", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_evaluations_decision_id", "evaluations", ["decision_id"])

    op.create_table(
        "data_quality_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "collection_meta",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False, unique=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_latency_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_table("collection_meta")
    op.drop_table("data_quality_incidents")
    op.drop_index("ix_evaluations_decision_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_prediction_outcomes_decision_id", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")
    op.drop_index("ix_specialist_assessments_decision_id", table_name="specialist_assessments")
    op.drop_table("specialist_assessments")
    op.drop_table("council_decisions")
    op.drop_table("market_snapshots")
    op.drop_index("ix_candles_symbol_tf_time", table_name="candles")
    op.drop_table("candles")
