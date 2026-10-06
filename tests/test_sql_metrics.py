"""
SQL cross-check (PostgreSQL). sql/metrics.sql computes max drawdown,
volatility, Sharpe and a 63-day rolling Sharpe from a stored run's equity
curve with window functions. They must agree with backtest_engine/metrics.py.

Each seeded backtest runs through BacktestService, which persists it to
PostgreSQL. Two comparisons follow:

1. Formula check: Python metrics on the equity values read back from the
   database, against SQL on the same rows, within FORMULA_TOL (1e-9).
2. End to end: the engine's own metrics (float64 equity, never stored), which
   the API reports, against SQL on the stored NUMERIC(18, 4) curve, within
   END_TO_END_TOL (1e-5) and, for rolling Sharpe, ROLLING_REL_TOL (1e-4,
   relative to max(|Sharpe|, 1)).

app/services/sql_metrics.py explains how the tolerances were derived.
"""
import contextlib
import io
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.services.backtest_service import BacktestService
from app.services.sql_metrics import (
    END_TO_END_TOL, FORMULA_TOL, ROLLING_REL_TOL, compare_with_python, load_queries,
    sql_drawdown_curve, sql_rolling_sharpe, sql_run_metrics, stored_equity_curve, within_tolerance,
)
from backtest_engine.metrics import ROLLING_SHARPE_WINDOW, PerformanceMetrics
from init_db import init_database
from tests.postgres import app_bound_to, fresh_postgres_database

RUN = {
    'start_date': '2022-01-01',
    'end_date': '2023-12-31',
    'initial_capital': 100_000.0,
    'symbols': ['AAPL', 'AMZN', 'GOOGL', 'JPM', 'MSFT'],
}


@pytest.fixture(scope='module')
def pg_engine():
    with fresh_postgres_database() as url:
        engine = create_engine(url)
        with contextlib.redirect_stdout(io.StringIO()):
            init_database(engine)
        with app_bound_to(engine):
            yield engine
        engine.dispose()


def run_and_store(strategy, risk_profile):
    """Run a backtest through the service, which stores it in PostgreSQL;
    also return the engine's in-memory results"""
    with contextlib.redirect_stdout(io.StringIO()):
        return BacktestService().run_backtest_with_results(strategy, risk_profile, **RUN)


def test_the_sql_file_has_the_three_queries():
    assert set(load_queries()) == {'run_metrics', 'drawdown_curve', 'rolling_sharpe'}


@pytest.mark.postgres
@pytest.mark.parametrize('risk_profile', ['No Risk Management', 'Conservative'])
@pytest.mark.parametrize('strategy', ['Moving Average Crossover', 'RSI Mean Reversion', 'Trend Following'])
def test_sql_metrics_match_python(pg_engine, strategy, risk_profile):
    stored, results = run_and_store(strategy, risk_profile)
    run_id = stored['backtest_id']
    with pg_engine.connect() as conn:
        sql = sql_run_metrics(conn, run_id)
        sql_drawdowns = sql_drawdown_curve(conn, run_id)
        sql_rolling = sql_rolling_sharpe(conn, run_id)
        stored_curve = stored_equity_curve(conn, run_id)
        comparison = compare_with_python(conn, run_id, results['equity_curve'], RUN['initial_capital'])

    points = len(results['equity_curve'])
    assert sql['points'] == points and sql['returns'] == points - 1
    assert len(sql_rolling) == points - ROLLING_SHARPE_WINDOW

    # 1. Formula check: the same stored values on both sides
    py = PerformanceMetrics(stored_curve, [], RUN['initial_capital'])
    assert sql['max_drawdown'] == pytest.approx(py.max_drawdown(), abs=FORMULA_TOL)
    assert sql_drawdowns.tolist() == pytest.approx(py.drawdown_series().tolist(), abs=FORMULA_TOL)
    assert sql['volatility'] == pytest.approx(py.volatility(), abs=FORMULA_TOL)
    assert sql['sharpe_ratio'] == pytest.approx(py.sharpe_ratio(), abs=FORMULA_TOL)
    py_rolling = py.rolling_sharpe()
    assert list(py_rolling.index) == list(sql_rolling.index)
    assert py_rolling.isna().tolist() == sql_rolling.isna().tolist()
    defined = py_rolling.notna().values
    assert sql_rolling[defined].tolist() == pytest.approx(py_rolling[defined].tolist(), abs=FORMULA_TOL)

    # 2. End to end: the engine's float64 metrics (what the API reports)
    # against SQL on the stored NUMERIC(18, 4) curve
    engine_metrics = stored['metrics']
    assert sql['max_drawdown'] == pytest.approx(engine_metrics['max_drawdown'], abs=END_TO_END_TOL)
    assert sql['volatility'] == pytest.approx(engine_metrics['volatility'], abs=END_TO_END_TOL)
    assert sql['sharpe_ratio'] == pytest.approx(engine_metrics['sharpe_ratio'], abs=END_TO_END_TOL)
    engine_rolling = PerformanceMetrics(results['equity_curve'], [], RUN['initial_capital']).rolling_sharpe()
    assert engine_rolling.isna().tolist() == sql_rolling.isna().tolist()
    diff = (engine_rolling.values[defined] - sql_rolling.values[defined])
    scale = abs(sql_rolling.values[defined]).clip(min=1.0)
    assert (abs(diff) <= ROLLING_REL_TOL * scale).all()

    # The helper scripts/sql_check.py uses agrees
    assert within_tolerance(comparison)


def insert_curve(engine, equities):
    """A run whose equity curve is exactly `equities`, one point per day"""
    start = datetime(2023, 1, 2, tzinfo=timezone.utc)
    with engine.begin() as conn:
        run_id = conn.execute(text(
            "INSERT INTO backtest_runs (strategy_id, risk_config_id, start_date, end_date, "
            "initial_capital, status) VALUES (1, 1, '2023-01-02', '2023-12-31', :capital, 'completed') "
            "RETURNING id"), {'capital': equities[0]}).scalar()
        conn.execute(text(
            "INSERT INTO equity_curve (backtest_run_id, timestamp, equity) VALUES (:run, :ts, :equity)"),
            [{'run': run_id, 'ts': start + timedelta(days=i), 'equity': e} for i, e in enumerate(equities)])
    return run_id


@pytest.mark.postgres
def test_known_answers(pg_engine):
    # Peak 110 -> trough 88 is a 20% drawdown; the later peak of 120 doesn't reset it
    run_id = insert_curve(pg_engine, [100, 110, 88, 120, 114])
    with pg_engine.connect() as conn:
        sql = sql_run_metrics(conn, run_id)
        drawdowns = sql_drawdown_curve(conn, run_id).round(9).tolist()
    assert sql['max_drawdown'] == pytest.approx(20.0, abs=FORMULA_TOL)
    assert drawdowns == [0.0, 0.0, 20.0, 0.0, 5.0]

    returns = pd.Series([0.10, -0.20, 120 / 88 - 1, 114 / 120 - 1])
    expected_sharpe = (returns.mean() * 252 - 0.02) / (returns.std(ddof=1) * math.sqrt(252))
    assert sql['sharpe_ratio'] == pytest.approx(expected_sharpe, abs=FORMULA_TOL)
    assert sql['volatility'] == pytest.approx(returns.std(ddof=1) * math.sqrt(252) * 100, abs=FORMULA_TOL)


@pytest.mark.postgres
def test_flat_curve_sharpe_is_undefined_in_sql_and_python(pg_engine):
    # With zero volatility Sharpe is undefined: NULL in SQL, None in Python
    # (and null in the API)
    run_id = insert_curve(pg_engine, [100_000] * (ROLLING_SHARPE_WINDOW + 5))
    with pg_engine.connect() as conn:
        sql = sql_run_metrics(conn, run_id)
        rolling = sql_rolling_sharpe(conn, run_id)
    assert sql['max_drawdown'] == 0 and sql['volatility'] == 0
    assert sql['sharpe_ratio'] is None
    assert len(rolling) == 5 and rolling.isna().all()

    curve = [{'timestamp': datetime(2023, 1, 2) + timedelta(days=i), 'equity': 100_000}
             for i in range(ROLLING_SHARPE_WINDOW + 5)]
    py = PerformanceMetrics(curve, [], 100_000)
    assert py.sharpe_ratio() is None
    assert py.rolling_sharpe().isna().all()


@pytest.mark.postgres
def test_one_return_leaves_volatility_and_sharpe_undefined_on_both_sides(pg_engine):
    # Two points give one daily return; the sample standard deviation needs
    # two. STDDEV_SAMP is NULL, and Python gives None, where it used to give NaN
    run_id = insert_curve(pg_engine, [100_000, 101_000])
    with pg_engine.connect() as conn:
        sql = sql_run_metrics(conn, run_id)
        comparison = compare_with_python(conn, run_id, stored_equity_curve(conn, run_id), 100_000)
    assert sql['returns'] == 1
    assert sql['volatility'] is None and sql['sharpe_ratio'] is None

    py = PerformanceMetrics([{'timestamp': datetime(2023, 1, 2), 'equity': 100_000},
                             {'timestamp': datetime(2023, 1, 3), 'equity': 101_000}], [], 100_000)
    assert py.volatility() is None and py.sharpe_ratio() is None
    assert py.undefined == {'volatility': 'fewer than two daily returns',
                            'sharpe_ratio': 'fewer than two daily returns'}
    assert comparison['formula']['volatility'] == 0.0 and comparison['formula']['sharpe_ratio'] == 0.0
