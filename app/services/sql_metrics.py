"""
Run the queries in sql/metrics.sql against a stored run (PostgreSQL only),
and compare them with the Python metrics.

The file holds named queries, each introduced by a `-- name: <name>` line.
They take the bind parameters :run_id, :trading_days, :risk_free_rate and
:window. The conventions are bound from backtest_engine.metrics, so the SQL
and Python sides read the same constants.

SQLite has window functions but no STDDEV_SAMP, so this needs PostgreSQL.

Tolerances (used by tests/test_sql_metrics.py and scripts/sql_check.py):

- FORMULA_TOL: Python metrics on the equity values read back from the
  database, against SQL on the same rows. Only the arithmetic differs
  (float64 against NUMERIC).
- END_TO_END_TOL: the engine's metrics, from float64 equity that is never
  stored, against SQL on the stored NUMERIC(18, 4) curve. Storing at 4
  decimal places moves each equity value by at most $0.00005, so each daily
  return moves by at most about 1e-4 / equity, roughly 2e-9 while equity
  stays above $50,000. Worst-case effects:
  - drawdown: 100 * 1e-4 / 50,000 = 2e-7 percentage points;
  - annualised volatility: 100 * sqrt(252) * 2e-9 = 3e-6 points;
  - full-period Sharpe: (sqrt(252) + |S|) * 2e-9 / (sqrt(252) * daily sd),
    under 1e-6 for the benchmark runs.
- ROLLING_REL_TOL: rolling Sharpe, end to end, relative to max(|Sharpe|, 1).
  In windows spent mostly in cash the daily sd is tiny and Sharpe is
  dominated by the risk-free term (it reaches about -28 on the benchmark
  runs). The rounding error grows with |Sharpe|, so the tolerance is relative.
"""
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import text

from backtest_engine.metrics import (
    RISK_FREE_RATE, ROLLING_SHARPE_WINDOW, TRADING_DAYS_PER_YEAR, PerformanceMetrics,
)

SQL_PATH = Path(__file__).resolve().parents[2] / 'sql' / 'metrics.sql'
_NAME = re.compile(r'^-- name: (\w+)\s*$', re.MULTILINE)

FORMULA_TOL = 1e-9
END_TO_END_TOL = 1e-5
ROLLING_REL_TOL = 1e-4


def load_queries(path: Path = SQL_PATH) -> Dict[str, str]:
    """{name: sql} for each `-- name:` section of the file"""
    source = path.read_text()
    markers = list(_NAME.finditer(source))
    return {
        m.group(1): source[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(source)]
        .strip().rstrip(';')
        for i, m in enumerate(markers)
    }


def _params(run_id: int, window: int = ROLLING_SHARPE_WINDOW) -> Dict:
    return {'run_id': run_id, 'trading_days': TRADING_DAYS_PER_YEAR,
            'risk_free_rate': RISK_FREE_RATE, 'window': window}


def _float(value) -> Optional[float]:
    return None if value is None else float(value)


def _naive_utc(timestamps) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(timestamps)
    # An empty result (a curve shorter than the rolling window) has no time zone
    return index.tz_convert('UTC').tz_localize(None) if index.tz is not None else index


def sql_run_metrics(connection, run_id: int) -> Dict[str, Optional[float]]:
    """points, returns, max_drawdown (%), volatility (%), sharpe_ratio (None if undefined)"""
    row = connection.execute(text(load_queries()['run_metrics']), _params(run_id)).one()
    return {
        'points': row.points,
        'returns': row.returns,
        'max_drawdown': _float(row.max_drawdown_pct),
        'volatility': _float(row.volatility_pct),
        'sharpe_ratio': _float(row.sharpe_ratio),
    }


def sql_drawdown_curve(connection, run_id: int) -> pd.Series:
    """Drawdown (%) at each point, indexed by naive UTC timestamp"""
    rows = connection.execute(text(load_queries()['drawdown_curve']), _params(run_id)).all()
    return pd.Series([float(r.drawdown_pct) for r in rows],
                     index=_naive_utc([r.timestamp for r in rows]), dtype=float)


def sql_rolling_sharpe(connection, run_id: int, window: int = ROLLING_SHARPE_WINDOW) -> pd.Series:
    """Rolling Sharpe indexed by naive UTC timestamp; NaN where volatility is zero"""
    rows = connection.execute(text(load_queries()['rolling_sharpe']), _params(run_id, window)).all()
    return pd.Series([math.nan if r.sharpe_ratio is None else float(r.sharpe_ratio) for r in rows],
                     index=_naive_utc([r.timestamp for r in rows]), dtype=float)


def stored_equity_curve(connection, run_id: int) -> List[Dict]:
    rows = connection.execute(text(
        'SELECT "timestamp", equity FROM equity_curve WHERE backtest_run_id = :run_id '
        'ORDER BY "timestamp"'), {'run_id': run_id}).all()
    return [{'timestamp': ts, 'equity': float(r.equity)}
            for ts, r in zip(_naive_utc([r.timestamp for r in rows]), rows)]


def _differences(py: PerformanceMetrics, connection, run_id: int) -> Dict[str, float]:
    """Largest absolute differences between `py` and the SQL for the run.
    Raises AssertionError if Sharpe is undefined in different places."""
    sql = sql_run_metrics(connection, run_id)
    py_volatility, py_sharpe = py.volatility(), py.sharpe_ratio()  # None where undefined, like NULL
    if (py_volatility is None) != (sql['volatility'] is None):
        raise AssertionError('volatility is undefined on one side only')
    if (py_sharpe is None) != (sql['sharpe_ratio'] is None):
        raise AssertionError('full-period Sharpe is undefined on one side only')

    py_rolling, sql_rolling = py.rolling_sharpe(), sql_rolling_sharpe(connection, run_id)
    py_rolling.index = pd.DatetimeIndex(py_rolling.index)
    if not py_rolling.index.equals(sql_rolling.index):
        raise AssertionError('rolling Sharpe windows end on different dates')
    if not py_rolling.isna().equals(sql_rolling.isna()):
        raise AssertionError('rolling Sharpe is undefined in different windows')
    defined = py_rolling.notna()
    rolling_abs = (py_rolling[defined] - sql_rolling[defined]).abs()
    rolling_rel = rolling_abs / sql_rolling[defined].abs().clip(lower=1.0)

    py_drawdowns = py.drawdown_series()
    py_drawdowns.index = pd.DatetimeIndex(py_drawdowns.index)
    return {
        'max_drawdown': abs(py.max_drawdown() - sql['max_drawdown']),
        'drawdown_curve': float((py_drawdowns - sql_drawdown_curve(connection, run_id)).abs().max()),
        'volatility': 0.0 if py_volatility is None else abs(py_volatility - sql['volatility']),
        'sharpe_ratio': 0.0 if py_sharpe is None else abs(py_sharpe - sql['sharpe_ratio']),
        'rolling_sharpe': float(rolling_abs.max()) if len(rolling_abs) else 0.0,
        'rolling_sharpe_rel': float(rolling_rel.max()) if len(rolling_rel) else 0.0,
    }


def compare_with_python(connection, run_id: int, engine_equity_curve: List[Dict],
                        initial_capital: float) -> Dict:
    """
    SQL metrics for a stored run, and their largest differences from:
    - 'formula': Python on the stored (NUMERIC) equity values;
    - 'end_to_end': Python on the engine's own float64 equity curve.
    """
    sql = sql_run_metrics(connection, run_id)
    stored = PerformanceMetrics(stored_equity_curve(connection, run_id), [], initial_capital)
    engine = PerformanceMetrics(engine_equity_curve, [], initial_capital)
    rolling = sql_rolling_sharpe(connection, run_id)
    return {
        'sql': sql,
        'engine': {'max_drawdown': engine.max_drawdown(), 'volatility': engine.volatility(),
                   'sharpe_ratio': engine.sharpe_ratio()},
        'rolling_windows': int(len(rolling)),
        'undefined_windows': int(rolling.isna().sum()),
        'rolling_min': (float(rolling.min()), rolling.idxmin()) if rolling.notna().any() else None,
        'formula': _differences(stored, connection, run_id),
        'end_to_end': _differences(engine, connection, run_id),
    }


def within_tolerance(comparison: Dict) -> bool:
    formula, end_to_end = comparison['formula'], comparison['end_to_end']
    return (all(value <= FORMULA_TOL for key, value in formula.items() if key != 'rolling_sharpe_rel')
            and all(end_to_end[k] <= END_TO_END_TOL
                    for k in ('max_drawdown', 'drawdown_curve', 'volatility', 'sharpe_ratio'))
            and end_to_end['rolling_sharpe_rel'] <= ROLLING_REL_TOL)
