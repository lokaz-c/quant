"""
SQL cross-check on the benchmark runs -> stdout

Runs the same 12 backtests as `make results` (every strategy, with the risk
layer off and under each risk profile, 5 symbols, 2020-2024), stores them in
the PostgreSQL database at DATABASE_URL, and compares the window-function
metrics in sql/metrics.sql with the Python metrics. Exits 1 if any
difference exceeds the tolerances in app/services/sql_metrics.py.

    make sql-check      # throwaway PostgreSQL container, then this script

It writes 12 runs into the database it is pointed at.
"""
import contextlib
import io
import sys

from app.models.database import engine
from app.services.backtest_service import BacktestService
from app.services.sql_metrics import (
    END_TO_END_TOL, FORMULA_TOL, ROLLING_REL_TOL, compare_with_python, within_tolerance,
)
from backtest_engine.metrics import ROLLING_SHARPE_WINDOW
from init_db import init_database
from scripts.results import BenchmarkConfig, load_risk_profiles


def _sharpe(value) -> str:
    return 'undefined' if value is None else f'{value:.6f}'


def main() -> int:
    if engine.dialect.name != 'postgresql':
        print(f'DATABASE_URL must point to PostgreSQL (got {engine.dialect.name}); '
              'try `make sql-check`', file=sys.stderr)
        return 2

    config = BenchmarkConfig()
    with contextlib.redirect_stdout(io.StringIO()):
        init_database()

    rows, worst_formula, worst_end_to_end, ok = [], {}, {}, True
    lowest = None  # (rolling Sharpe, strategy, profile, window end)
    for strategy in config.strategies:
        for profile in load_risk_profiles(config.risk_profiles):
            with contextlib.redirect_stdout(io.StringIO()):
                # The benchmark runs are on the synthetic file, whatever the default source
                stored, results = BacktestService().run_backtest_with_results(
                    strategy, profile.name, config.start_date, config.end_date,
                    config.initial_capital, list(config.symbols), data_source='synthetic')
            with engine.connect() as conn:
                c = compare_with_python(conn, stored['backtest_id'], results['equity_curve'],
                                        config.initial_capital)
            ok &= within_tolerance(c)
            if c['rolling_min'] and (lowest is None or c['rolling_min'][0] < lowest[0]):
                lowest = (*c['rolling_min'][:1], strategy, profile.name, c['rolling_min'][1])
            for worst, key in ((worst_formula, 'formula'), (worst_end_to_end, 'end_to_end')):
                for k, v in c[key].items():
                    worst[k] = max(worst.get(k, 0.0), v)
            e2e = c['end_to_end']
            rows.append(
                f"| {strategy} | {profile.name} | {c['engine']['max_drawdown']:.6f} | "
                f"{c['sql']['max_drawdown']:.6f} | {_sharpe(c['engine']['sharpe_ratio'])} | "
                f"{_sharpe(c['sql']['sharpe_ratio'])} | {c['undefined_windows']} of {c['rolling_windows']} | "
                f"{e2e['max_drawdown']:.1e} | {e2e['volatility']:.1e} | {e2e['sharpe_ratio']:.1e} | "
                f"{e2e['rolling_sharpe_rel']:.1e} |")

    print(f'SQL cross-check: {len(rows)} runs, {", ".join(config.symbols)}, '
          f'{config.start_date} to {config.end_date}, rolling window {ROLLING_SHARPE_WINDOW} days')
    print()
    print('Max drawdown in %. "Undefined windows": rolling windows with zero volatility, '
          'NULL in SQL and NaN in Python. The last four columns are the end-to-end '
          'differences (engine float64 against SQL on the stored NUMERIC curve); the '
          'rolling one is relative to max(|Sharpe|, 1).')
    print()
    print('| Strategy | Risk profile | Max DD, engine | Max DD, SQL | Sharpe, engine | Sharpe, SQL '
          '| Undefined windows | Max DD diff | Volatility diff | Sharpe diff | Rolling Sharpe diff |')
    print('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |')
    print('\n'.join(rows))
    print()
    print('Largest differences over all runs:')
    print(f'- formula (Python on the stored values against SQL; tolerance {FORMULA_TOL:g}): '
          + ', '.join(f'{k} {v:.1e}' for k, v in worst_formula.items() if k != 'rolling_sharpe_rel'))
    print(f'- end to end (tolerance {END_TO_END_TOL:g}; rolling Sharpe {ROLLING_REL_TOL:g} relative): '
          + ', '.join(f'{k} {v:.1e}' for k, v in worst_end_to_end.items()))
    if lowest:
        print(f'Lowest rolling Sharpe (SQL): {lowest[0]:.2f}, {lowest[1]}, {lowest[2]}, window ending '
              f'{lowest[3]:%Y-%m-%d}. Mostly-cash windows have a tiny standard deviation, and idle cash '
              'earns nothing against the 2% risk-free rate.')
    print(f'All within tolerance: {"yes" if ok else "NO"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
