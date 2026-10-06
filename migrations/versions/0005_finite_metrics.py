"""Undefined metrics are NULL with a recorded reason; no NaN or infinity

The engine now returns None for a metric with no value for a run (Sharpe
with zero volatility or fewer than two daily returns, win rate with no closed
trades, and so on) instead of NaN, an infinity or a stand-in 0.0. This
revision makes the table hold the same convention:

- backtest_metrics.undefined_metrics: JSON, metric name -> why it is NULL,
  e.g. {"sharpe_ratio": "zero volatility"}.
- CHECK constraints on the double precision metric columns: NULL or a finite
  number. PostgreSQL's double precision accepts 'NaN', 'Infinity' and
  '-Infinity', and a run with one daily return used to store NaN volatility
  and Sharpe there. NaN compares greater than every number in PostgreSQL, so
  it fails the BETWEEN test like the infinities. SQLite stores NaN as NULL
  and an infinity as a REAL outside the range, which the same test rejects.

Existing non-finite values become NULL before the constraints are added.
Their reason was never recorded; the API reports that (docs/api.md).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')

# The double precision columns of backtest_metrics (the NUMERIC money columns
# are written from finite engine values and need no check)
METRIC_COLUMNS = ('total_return', 'cagr', 'max_drawdown', 'volatility', 'sharpe_ratio', 'win_rate')
DOUBLE_MAX = '1.7976931348623157e308'


def in_range(column: str) -> str:
    return f'{column} BETWEEN -{DOUBLE_MAX} AND {DOUBLE_MAX}'


def finite(column: str) -> str:
    return f'{column} IS NULL OR {in_range(column)}'


def upgrade() -> None:
    for column in METRIC_COLUMNS:
        op.execute(f'UPDATE backtest_metrics SET {column} = NULL WHERE NOT ({in_range(column)})')
    # batch mode: SQLite can't add CHECK constraints with ALTER TABLE
    with op.batch_alter_table('backtest_metrics') as batch:
        batch.add_column(sa.Column('undefined_metrics', JSONB, nullable=True))
        for column in METRIC_COLUMNS:
            batch.create_check_constraint(f'ck_backtest_metrics_{column}_finite', finite(column))


def downgrade() -> None:
    with op.batch_alter_table('backtest_metrics') as batch:
        for column in METRIC_COLUMNS:
            batch.drop_constraint(f'ck_backtest_metrics_{column}_finite', type_='check')
        batch.drop_column('undefined_metrics')
