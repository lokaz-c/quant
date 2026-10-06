"""Store each run's strategy parameters and the baseline run it is compared with

- backtest_runs.strategy_parameters: the parameters the run actually used
  (the strategy's stored defaults merged with the request's overrides). Before
  this, a run could only be traced to the strategy row, whose parameters can
  change.
- backtest_runs.baseline_run_id: for a run made with "compare to baseline",
  the run with the risk layer off on the same inputs. ON DELETE SET NULL, so
  deleting a baseline leaves the managed run in place.

Existing rows get NULL for both.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade() -> None:
    # batch mode: SQLite can't add a foreign key constraint with ALTER TABLE
    with op.batch_alter_table('backtest_runs') as batch:
        batch.add_column(sa.Column('strategy_parameters', JSONB, nullable=True))
        batch.add_column(sa.Column('baseline_run_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_backtest_runs_baseline_run_id', 'backtest_runs',
                                 ['baseline_run_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('backtest_runs') as batch:
        batch.drop_constraint('fk_backtest_runs_baseline_run_id', type_='foreignkey')
        batch.drop_column('baseline_run_id')
        batch.drop_column('strategy_parameters')
