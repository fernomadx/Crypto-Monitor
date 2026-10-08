"""Add derivative_observations for OI time series."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_derivative_observations"
down_revision: Union[str, None] = "0002_weights_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "derivative_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(64), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding", sa.Float(), nullable=True),
        sa.Column("open_interest", sa.Float(), nullable=True),
        sa.Column("open_interest_usd", sa.Float(), nullable=True),
        sa.Column("mark_price", sa.Float(), nullable=True),
        sa.Column("index_price", sa.Float(), nullable=True),
        sa.Column("basis_bps", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_deriv_obs_symbol_time",
        "derivative_observations",
        ["symbol", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deriv_obs_symbol_time", table_name="derivative_observations")
    op.drop_table("derivative_observations")
