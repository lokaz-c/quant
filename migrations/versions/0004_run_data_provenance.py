"""Record where each run's bars came from

Runs can now use bars from the market-data service as well as the local
synthetic generator, and the service itself serves both Alpaca and synthetic
data. Each run records:

- backtest_runs.data_source: 'synthetic' (the local generator's file) or
  'market-data' (the service, through the local cache)
- backtest_runs.reported_source: what the service said the bars are:
  'alpaca', 'synthetic', or 'mixed' when the run's symbols disagree. Always
  'synthetic' for the local generator (ck_backtest_runs_local_is_synthetic).
- backtest_runs.symbol_sources: the service's source for each symbol
- backtest_runs.price_adjustment: 'split' or 'raw' for market-data runs

Every run before this revision used the local generator, so existing rows
get data_source = reported_source = 'synthetic', which is what the server
defaults write. The defaults stay: a writer that forgets the columns labels
a run synthetic, never real.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')

CHECKS = {
    'ck_backtest_runs_data_source': "data_source IN ('synthetic', 'market-data')",
    'ck_backtest_runs_reported_source': "reported_source IN ('synthetic', 'alpaca', 'mixed')",
    'ck_backtest_runs_price_adjustment': "price_adjustment IN ('split', 'raw')",
    'ck_backtest_runs_local_is_synthetic': "data_source = 'market-data' OR reported_source = 'synthetic'",
}


def upgrade() -> None:
    # batch mode: SQLite can't add CHECK constraints with ALTER TABLE
    with op.batch_alter_table('backtest_runs') as batch:
        batch.add_column(sa.Column('data_source', sa.String(20), nullable=False, server_default='synthetic'))
        batch.add_column(sa.Column('reported_source', sa.String(20), nullable=False, server_default='synthetic'))
        batch.add_column(sa.Column('symbol_sources', JSONB, nullable=True))
        batch.add_column(sa.Column('price_adjustment', sa.String(10), nullable=True))
        for name, condition in CHECKS.items():
            batch.create_check_constraint(name, condition)


def downgrade() -> None:
    with op.batch_alter_table('backtest_runs') as batch:
        for name in CHECKS:
            batch.drop_constraint(name, type_='check')
        batch.drop_column('price_adjustment')
        batch.drop_column('symbol_sources')
        batch.drop_column('reported_source')
        batch.drop_column('data_source')
