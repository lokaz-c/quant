"""Baseline: the schema db/init.sql created before Alembic

Same tables, column types, defaults, constraints and indexes as the old
db/init.sql, so a database created by that file can be adopted with
`alembic stamp 0001` (init_db.py does this automatically) and then upgraded.
Constraint names are left to the database, which gives the same names init.sql
produced on PostgreSQL (e.g. strategies_name_key, trades_backtest_run_id_fkey).

On SQLite, JSONB becomes JSON and everything else is the same DDL.

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')
NOW = sa.text('CURRENT_TIMESTAMP')


def upgrade() -> None:
    op.create_table(
        'strategies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text()),
        sa.Column('parameters', JSONB),
        sa.Column('created_at', sa.DateTime(), server_default=NOW),
        sa.Column('updated_at', sa.DateTime(), server_default=NOW),
    )
    op.create_table(
        'risk_configs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('max_position_size', sa.Float()),
        sa.Column('max_portfolio_exposure', sa.Float()),
        sa.Column('stop_loss_pct', sa.Float()),
        sa.Column('take_profit_pct', sa.Float()),
        sa.Column('max_drawdown_pct', sa.Float()),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=NOW),
    )
    op.create_table(
        'backtest_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('strategies.id')),
        sa.Column('risk_config_id', sa.Integer(), sa.ForeignKey('risk_configs.id')),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('initial_capital', sa.Float(), nullable=False),
        sa.Column('symbols', JSONB),
        sa.Column('market_regime', sa.String(50)),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('created_at', sa.DateTime(), server_default=NOW),
        sa.Column('completed_at', sa.DateTime()),
    )
    op.create_table(
        'backtest_metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('backtest_run_id', sa.Integer(),
                  sa.ForeignKey('backtest_runs.id', ondelete='CASCADE')),
        sa.Column('total_return', sa.Float()),
        sa.Column('cagr', sa.Float()),
        sa.Column('max_drawdown', sa.Float()),
        sa.Column('volatility', sa.Float()),
        sa.Column('sharpe_ratio', sa.Float()),
        sa.Column('win_rate', sa.Float()),
        sa.Column('avg_win', sa.Float()),
        sa.Column('avg_loss', sa.Float()),
        sa.Column('num_trades', sa.Integer()),
        sa.Column('final_equity', sa.Float()),
        sa.Column('created_at', sa.DateTime(), server_default=NOW),
    )
    op.create_table(
        'equity_curve',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('backtest_run_id', sa.Integer(),
                  sa.ForeignKey('backtest_runs.id', ondelete='CASCADE')),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('equity', sa.Float(), nullable=False),
        sa.Column('cash', sa.Float()),
        sa.Column('positions_value', sa.Float()),
    )
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('backtest_run_id', sa.Integer(),
                  sa.ForeignKey('backtest_runs.id', ondelete='CASCADE')),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('entry_date', sa.DateTime(), nullable=False),
        sa.Column('exit_date', sa.DateTime()),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('exit_price', sa.Float()),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('pnl', sa.Float()),
        sa.Column('pnl_pct', sa.Float()),
        sa.Column('status', sa.String(20), server_default='open'),
    )
    op.create_index('idx_backtest_runs_strategy', 'backtest_runs', ['strategy_id'])
    op.create_index('idx_backtest_runs_dates', 'backtest_runs', ['start_date', 'end_date'])
    op.create_index('idx_equity_curve_run', 'equity_curve', ['backtest_run_id'])
    op.create_index('idx_trades_run', 'trades', ['backtest_run_id'])


def downgrade() -> None:
    for table in ('trades', 'equity_curve', 'backtest_metrics', 'backtest_runs',
                  'risk_configs', 'strategies'):
        op.drop_table(table)
