"""Money columns to NUMERIC, timestamps to TIMESTAMPTZ, CHECK constraints, equity-curve index

Types (see docs/database.md for the reasoning):
- money (capital, equity, cash, position value, P&L, average win/loss):
  NUMERIC(18, 4)
- trade prices: NUMERIC(18, 4)
- trade quantity: NUMERIC(18, 9)
- ratios and percentages (returns, drawdown, Sharpe, risk limits, pnl_pct)
  stay double precision

Timestamps: every TIMESTAMP becomes TIMESTAMPTZ. The app has always written
UTC (datetime.utcnow() and bar dates at midnight), so existing values are
converted with `AT TIME ZONE 'UTC'`. Without the USING clause PostgreSQL
would read them in the session's TimeZone, which shifts them when that
isn't UTC.

CHECK constraints list the values the code writes:
- backtest_runs.status: pending (column default), running, completed, failed
  (BacktestService)
- trades.side: buy, sell (Portfolio)
- trades.status: open, closed (Portfolio)

Index: a unique index on equity_curve(backtest_run_id, timestamp). The engine
records one equity point per bar, so a duplicate would be a bug, and the
window functions in the SQL metrics order by timestamp within a run. It
replaces the single-column idx_equity_curve_run, which it makes redundant
(the composite index serves lookups on its leading column).

On SQLite, batch mode rebuilds each table: SQLite can't ALTER a column type
or add a constraint in place. SQLite has no time zone type or fixed-point
type, so there the timestamp change is a no-op and NUMERIC values are
stored with NUMERIC affinity (an integer or an 8-byte float).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(18, 4)
PRICE = sa.Numeric(18, 4)
QUANTITY = sa.Numeric(18, 9)

# table -> [(column, new type, nullable)]
NUMERIC_COLUMNS = {
    'backtest_runs': [('initial_capital', MONEY, False)],
    'backtest_metrics': [('avg_win', MONEY, True), ('avg_loss', MONEY, True),
                         ('final_equity', MONEY, True)],
    'equity_curve': [('equity', MONEY, False), ('cash', MONEY, True),
                     ('positions_value', MONEY, True)],
    'trades': [('entry_price', PRICE, False), ('exit_price', PRICE, True),
               ('quantity', QUANTITY, False), ('pnl', MONEY, True)],
}

# table -> [(column, nullable)]
TIMESTAMP_COLUMNS = {
    'strategies': [('created_at', True), ('updated_at', True)],
    'risk_configs': [('created_at', True)],
    'backtest_runs': [('created_at', True), ('completed_at', True)],
    'backtest_metrics': [('created_at', True)],
    'equity_curve': [('timestamp', False)],
    'trades': [('entry_date', False), ('exit_date', True)],
}

CHECKS = {
    'backtest_runs': [
        ('ck_backtest_runs_status', "status IN ('pending', 'running', 'completed', 'failed')"),
    ],
    'trades': [
        ('ck_trades_side', "side IN ('buy', 'sell')"),
        ('ck_trades_status', "status IN ('open', 'closed')"),
    ],
}

TABLES = ['strategies', 'risk_configs', 'backtest_runs', 'backtest_metrics',
          'equity_curve', 'trades']


def _utc(column: str) -> str:
    # timestamp -> timestamptz: read the stored wall time as UTC.
    # timestamptz -> timestamp: the UTC wall time of the stored instant.
    return f'"{column}" AT TIME ZONE \'UTC\''


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            for column, new_type, nullable in NUMERIC_COLUMNS.get(table, []):
                batch.alter_column(column, type_=new_type, existing_type=sa.Float(),
                                   existing_nullable=nullable)
            for column, nullable in TIMESTAMP_COLUMNS.get(table, []):
                batch.alter_column(column, type_=sa.DateTime(timezone=True),
                                   existing_type=sa.DateTime(), existing_nullable=nullable,
                                   postgresql_using=_utc(column))
            for name, condition in CHECKS.get(table, []):
                batch.create_check_constraint(name, condition)

    op.create_index('ix_equity_curve_run_timestamp', 'equity_curve',
                    ['backtest_run_id', 'timestamp'], unique=True)
    # IF EXISTS: a SQLite file made by the old create_all() path never had it
    op.drop_index('idx_equity_curve_run', table_name='equity_curve', if_exists=True)


def downgrade() -> None:
    op.create_index('idx_equity_curve_run', 'equity_curve', ['backtest_run_id'])
    op.drop_index('ix_equity_curve_run_timestamp', table_name='equity_curve')

    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            for name, _ in CHECKS.get(table, []):
                batch.drop_constraint(name, type_='check')
            for column, nullable in TIMESTAMP_COLUMNS.get(table, []):
                batch.alter_column(column, type_=sa.DateTime(),
                                   existing_type=sa.DateTime(timezone=True),
                                   existing_nullable=nullable,
                                   postgresql_using=_utc(column))
            for column, old_type, nullable in NUMERIC_COLUMNS.get(table, []):
                batch.alter_column(column, type_=sa.Float(), existing_type=old_type,
                                   existing_nullable=nullable)
