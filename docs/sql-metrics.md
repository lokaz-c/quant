# SQL cross-check

`sql/metrics.sql` recomputes the engine's risk metrics inside PostgreSQL from a stored run's `equity_curve`, using window functions. CI checks that they agree with the Python metrics in `backtest_engine/metrics.py`. The aim is to verify the Python code with an independent implementation, and to show what the stored data supports on its own.

## Queries

| Name | Returns | Window functions |
| --- | --- | --- |
| `run_metrics` | one row: points, returns, max drawdown (%), annualised volatility (%), full-period Sharpe | `MAX(equity) OVER (ORDER BY "timestamp" ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` for the running peak, `LAG(equity) OVER (ORDER BY "timestamp")` for daily returns, then `MAX`, `AVG` and `STDDEV_SAMP` |
| `drawdown_curve` | each point's equity, running peak and drawdown (%) | the same running `MAX() OVER` |
| `rolling_sharpe` | Sharpe over each trailing 63 daily returns (about a quarter), from the first full window | `AVG()` and `STDDEV_SAMP()` over `WINDOW w AS (ORDER BY "timestamp" ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)` |

They take bind parameters `:run_id`, `:trading_days` (252), `:risk_free_rate` (0.02) and `:window` (63). `app/services/sql_metrics.py` binds them from the constants in `backtest_engine/metrics.py`, so both sides read one definition. The file also runs in psql:

```bash
psql "$DATABASE_URL" -v run_id=1 -v trading_days=252 -v risk_free_rate=0.02 -v window=63 -f sql/metrics.sql
```

SQLite has window functions but no `STDDEV_SAMP`, so the cross-check needs PostgreSQL.

## Conventions

These are the same on both sides. Each one is a choice that would make the numbers disagree if one side did it differently.

- **Daily return** r_t = equity_t / equity_{t-1} - 1. The first point has no return: `LAG` gives NULL there, and `AVG`/`STDDEV_SAMP` skip NULLs; pandas' `pct_change()` gives NaN, which the Python code drops. In the rolling query the first row is filtered out before the window, so each window holds 63 returns, as `rolling(63)` does in pandas.
- **Sample standard deviation** (n - 1): `STDDEV_SAMP` in SQL, `Series.std()` in pandas (ddof=1 by default). numpy's `np.std` defaults to the population formula (ddof=0) and would not match.
- **Annualisation**: mean x 252, standard deviation x sqrt(252). **Sharpe** = (annualised mean - 0.02) / annualised standard deviation.
- **Drawdown** is measured from the running peak of the stored curve, starting at its first point. That point equals the initial capital, because the first bar's orders fill at its close and so don't change equity.
- **Window frame**: an `ORDER BY` window defaults to `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, which includes rows that tie on the sort key. The queries spell out `ROWS`. Because `equity_curve(backtest_run_id, timestamp)` is unique (migration `0002`), there are no ties, so the two frames are the same here.

One difference: **where volatility is zero, Sharpe is undefined.** The SQL returns NULL, while `PerformanceMetrics.sharpe_ratio()` returns 0.0. The new `PerformanceMetrics.rolling_sharpe()` returns NaN for those windows, to line up with the SQL. A test pins this down with a flat equity curve.

## Tolerances

Two comparisons per run (`tests/test_sql_metrics.py`, `app/services/sql_metrics.py`):

1. **Formula check.** Python metrics on the equity values read back from the database, against SQL on the same rows. Only the arithmetic differs (float64 against `NUMERIC`). Tolerance 1e-9.
2. **End to end.** The engine's metrics, which the API reports, are computed from float64 equity that is never stored. They are compared with SQL on the stored `NUMERIC(18, 4)` curve. Storing at 4 decimal places moves each equity value by at most $0.00005, and each daily return by at most about 2e-9 while equity stays above $50,000. In the worst case that is 2e-7 percentage points of drawdown and 3e-6 points of volatility. Tolerance 1e-5 for max drawdown, volatility and full-period Sharpe. Rolling Sharpe is more sensitive: in windows spent mostly in cash, the daily standard deviation is tiny and Sharpe is dominated by the risk-free term, so the rounding error grows with |Sharpe|. Its tolerance is 1e-4 relative to max(|Sharpe|, 1).

CI runs the check on PostgreSQL 15 for each strategy, with the risk layer off and with the Conservative profile, on 5 symbols over 2022-2023 (6 runs). It also runs a known-answer case (a 20% drawdown that a later, higher peak must not reset) and the flat-curve case. The tests fail if the SQL uses `STDDEV_POP`, keeps the first point's NULL return in the rolling window, or takes the peak over the whole run instead of a running peak.

## Result

`make sql-check` starts a throwaway PostgreSQL container and runs `scripts/sql_check.py`. The script stores the 12 runs behind `docs/results.md` (5 symbols, 2020-2024, every strategy x risk profile), prints both sets of metrics side by side, and exits non-zero if any difference exceeds the tolerances. Its summary when this page was written:

```
Largest differences over all runs:
- formula (Python on the stored values against SQL; tolerance 1e-09): max_drawdown 7.1e-15, drawdown_curve 1.4e-14, volatility 4.4e-15, sharpe_ratio 6.3e-15, rolling_sharpe 2.4e-11
- end to end (tolerance 1e-05; rolling Sharpe 0.0001 relative): max_drawdown 4.0e-08, drawdown_curve 9.4e-08, volatility 3.4e-08, sharpe_ratio 6.5e-09, rolling_sharpe 2.0e-05, rolling_sharpe_rel 8.0e-07
Lowest rolling Sharpe (SQL): -27.83, Moving Average Crossover, Conservative, window ending 2024-05-07. Mostly-cash windows have a tiny standard deviation, and idle cash earns nothing against the 2% risk-free rate.
All within tolerance: yes
```

The formula check agrees to floating-point noise, and the end-to-end differences are the expected effect of storing at 4 decimal places. The check found no bug in the Python metrics. It did make the zero-volatility convention explicit, and it showed how unstable a 63-day Sharpe is when a strategy spends most of a quarter in cash.
