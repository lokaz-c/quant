"""
Alembic migrations, on SQLite and on a real PostgreSQL (see conftest.py).

- upgrade to head on an empty database, then downgrade back to base
- the models match the head revision (no autogenerate diff)
- the CHECK constraints and the unique equity-curve index reject bad rows
- a pre-Alembic database is adopted (stamped 0001, then upgraded)
- PostgreSQL only: the column types, and that existing rows survive the
  FLOAT -> NUMERIC and TIMESTAMP -> TIMESTAMPTZ conversion and its downgrade
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.database import Base
from init_db import alembic_config, upgrade_to_head

TABLES = {'strategies', 'risk_configs', 'backtest_runs', 'backtest_metrics',
          'equity_curve', 'trades'}
HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


@pytest.fixture(params=['sqlite', pytest.param('postgres', marks=pytest.mark.postgres)])
def db_engine(request):
    url = request.getfixturevalue(f'{request.param}_url')
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_engine(postgres_url):
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


def migrate(engine, action, target):
    with engine.begin() as conn:
        getattr(command, action)(alembic_config(conn), target)


def revision(engine):
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def insert_run(conn, status='completed'):
    conn.execute(text("INSERT INTO strategies (id, name) VALUES (1, 'MA')"))
    conn.execute(text("INSERT INTO risk_configs (id, name) VALUES (1, 'Conservative')"))
    conn.execute(text(
        "INSERT INTO backtest_runs (id, strategy_id, risk_config_id, start_date, end_date, "
        "initial_capital, status) VALUES (1, 1, 1, '2023-01-01', '2023-12-31', 100000, :status)"
    ), {'status': status})


def test_head_is_the_latest_revision():
    assert HEAD == '0002'


def test_upgrade_to_head_and_downgrade_to_base(db_engine):
    migrate(db_engine, 'upgrade', 'head')
    assert revision(db_engine) == HEAD
    assert set(inspect(db_engine).get_table_names()) == TABLES | {'alembic_version'}

    migrate(db_engine, 'downgrade', 'base')
    assert revision(db_engine) is None
    assert set(inspect(db_engine).get_table_names()) == {'alembic_version'}


def test_models_match_the_head_revision(db_engine):
    migrate(db_engine, 'upgrade', 'head')
    with db_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={'compare_type': True})
        assert compare_metadata(context, Base.metadata) == []


GOOD_TRADE = {'side': 'sell', 'status': 'closed'}


@pytest.mark.parametrize('statement, params', [
    ("INSERT INTO trades (backtest_run_id, symbol, entry_date, entry_price, quantity, side, status) "
     "VALUES (1, 'AAPL', '2023-01-03', 100, 1, :side, :status)", {'side': 'short', 'status': 'closed'}),
    ("INSERT INTO trades (backtest_run_id, symbol, entry_date, entry_price, quantity, side, status) "
     "VALUES (1, 'AAPL', '2023-01-03', 100, 1, :side, :status)", {'side': 'sell', 'status': 'filled'}),
    ("UPDATE backtest_runs SET status = :status WHERE id = 1", {'status': 'done'}),
    ("INSERT INTO equity_curve (backtest_run_id, timestamp, equity) "
     "VALUES (1, '2023-01-03', 100000)", {}),  # a second point for the same bar
], ids=['trade-side', 'trade-status', 'run-status', 'duplicate-equity-point'])
def test_constraints_reject_bad_rows(db_engine, statement, params):
    migrate(db_engine, 'upgrade', 'head')
    with db_engine.begin() as conn:
        insert_run(conn)
        conn.execute(text("INSERT INTO equity_curve (backtest_run_id, timestamp, equity) "
                          "VALUES (1, '2023-01-03', 100000)"))
        # the same statements with valid values go through
        conn.execute(text(
            "INSERT INTO trades (backtest_run_id, symbol, entry_date, entry_price, quantity, side, status) "
            "VALUES (1, 'AAPL', '2023-01-03', 100, 1, :side, :status)"), GOOD_TRADE)
        conn.execute(text("UPDATE backtest_runs SET status = 'failed' WHERE id = 1"))

    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text(statement), params)


def test_constraint_values_match_what_the_code_writes():
    from app.models.database import RUN_STATUSES, TRADE_SIDES, TRADE_STATUSES
    from backtest_engine.portfolio import ExecutedTrade

    assert ExecutedTrade.__dataclass_fields__['status'].default in TRADE_STATUSES
    assert set(TRADE_SIDES) == {'buy', 'sell'}
    assert set(TRADE_STATUSES) == {'open', 'closed'}
    assert set(RUN_STATUSES) == {'pending', 'running', 'completed', 'failed'}


def test_pre_alembic_database_is_stamped_and_upgraded(db_engine):
    # A database created by the old db/init.sql has the baseline tables and no
    # alembic_version table
    migrate(db_engine, 'upgrade', '0001')
    with db_engine.begin() as conn:
        insert_run(conn)
        conn.execute(text('DROP TABLE alembic_version'))

    upgrade_to_head(db_engine)

    assert revision(db_engine) == HEAD
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT initial_capital FROM backtest_runs')).scalar() == 100000
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE backtest_runs SET status = 'done'"))


@pytest.mark.postgres
def test_postgres_column_types(pg_engine):
    migrate(pg_engine, 'upgrade', 'head')
    with pg_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema = 'public'"
        )).all()
    types = {(r.table_name, r.column_name): (r.data_type, r.numeric_precision, r.numeric_scale)
             for r in rows}

    money = ('numeric', 18, 4)
    for column in ('backtest_runs.initial_capital', 'backtest_metrics.avg_win',
                   'backtest_metrics.avg_loss', 'backtest_metrics.final_equity',
                   'equity_curve.equity', 'equity_curve.cash', 'equity_curve.positions_value',
                   'trades.entry_price', 'trades.exit_price', 'trades.pnl'):
        assert types[tuple(column.split('.'))] == money, column
    assert types[('trades', 'quantity')] == ('numeric', 18, 9)

    for column in ('backtest_metrics.total_return', 'backtest_metrics.sharpe_ratio',
                   'backtest_metrics.max_drawdown', 'trades.pnl_pct', 'risk_configs.stop_loss_pct'):
        assert types[tuple(column.split('.'))][0] == 'double precision', column

    timestamps = [key for key, value in types.items() if value[0].startswith('timestamp')]
    assert len(timestamps) == 9
    assert all(types[key][0] == 'timestamp with time zone' for key in timestamps)


@pytest.mark.postgres
def test_postgres_existing_rows_survive_the_type_changes(postgres_url):
    # A session time zone other than UTC: without `USING ... AT TIME ZONE 'UTC'`
    # the stored wall times would be read as New York time and shift by 5 hours
    engine = create_engine(postgres_url, connect_args={'options': '-c timezone=America/New_York'})
    try:
        migrate(engine, 'upgrade', '0001')
        with engine.begin() as conn:
            insert_run(conn)
            conn.execute(text(
                "INSERT INTO equity_curve (backtest_run_id, timestamp, equity, cash) "
                "VALUES (1, '2023-01-03 00:00:00', 100123.456789, 5000.5)"))
            conn.execute(text(
                "INSERT INTO trades (backtest_run_id, symbol, entry_date, entry_price, quantity, side, status) "
                "VALUES (1, 'AAPL', '2023-01-03', 187.42, 12.3456789012345, 'sell', 'closed')"))

        migrate(engine, 'upgrade', 'head')
        with engine.connect() as conn:
            point = conn.execute(text('SELECT timestamp, equity, cash FROM equity_curve')).one()
            trade = conn.execute(text('SELECT entry_price, quantity FROM trades')).one()
        assert point.timestamp == datetime(2023, 1, 3, tzinfo=timezone.utc)
        assert point.equity == Decimal('100123.4568')   # rounded to 4 decimal places
        assert point.cash == Decimal('5000.5000')
        assert trade.entry_price == Decimal('187.4200')
        assert trade.quantity == Decimal('12.345678901')

        migrate(engine, 'downgrade', '0001')
        with engine.connect() as conn:
            point = conn.execute(text('SELECT timestamp, equity FROM equity_curve')).one()
        assert point.timestamp == datetime(2023, 1, 3)  # naive again, same wall time
        assert point.equity == pytest.approx(100123.4568)
    finally:
        engine.dispose()
