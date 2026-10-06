-- Risk metrics computed in PostgreSQL from a stored run's equity curve.
--
-- They re-derive numbers the Python engine reports (backtest_engine/metrics.py),
-- and tests/test_sql_metrics.py checks that the two agree. The conventions
-- are the same on both sides:
--   * daily return r_t = equity_t / equity_{t-1} - 1. The first point has no
--     previous point, so it has no return (LAG gives NULL; pandas'
--     pct_change gives NaN and the Python code drops it).
--   * standard deviation is the sample one, STDDEV_SAMP (n - 1 denominator),
--     matching pandas' Series.std() default (ddof=1). numpy's np.std
--     defaults to the population formula and would not match.
--   * annualised with :trading_days (252): mean * 252 and sd * sqrt(252).
--   * Sharpe = (annualised mean - :risk_free_rate) / annualised sd, with
--     :risk_free_rate = 0.02 a year.
--   * drawdown is measured from the running peak of the stored curve,
--     starting at its first point (= initial capital: the first bar's fills
--     happen at that bar's close, so they don't change equity).
--   * where Sharpe or volatility is undefined (zero volatility, or fewer
--     than two returns) the SQL returns NULL and PerformanceMetrics returns
--     None, which the API sends as null.
--
-- Bind parameters: :run_id, :trading_days, :risk_free_rate, :window.
-- The app binds them through SQLAlchemy (app/services/sql_metrics.py). In
-- psql: psql -v run_id=1 -v trading_days=252 -v risk_free_rate=0.02 \
--            -v window=63 -f sql/metrics.sql
--
-- The ORDER BY "timestamp" windows are well defined because
-- equity_curve(backtest_run_id, timestamp) is unique (migration 0002). With
-- no ties, the default RANGE frame and the explicit ROWS frame used here
-- are the same thing.

-- name: run_metrics
-- One row per run: point and return counts, max drawdown (%), annualised
-- volatility (%) and full-period Sharpe.
WITH curve AS (
    SELECT
        "timestamp",
        equity,
        MAX(equity) OVER (ORDER BY "timestamp"
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_peak,
        equity / NULLIF(LAG(equity) OVER (ORDER BY "timestamp"), 0) - 1 AS daily_return
    FROM equity_curve
    WHERE backtest_run_id = :run_id
)
SELECT
    COUNT(*)                                                   AS points,
    COUNT(daily_return)                                        AS returns,
    MAX((running_peak - equity) / running_peak) * 100          AS max_drawdown_pct,
    STDDEV_SAMP(daily_return) * SQRT(:trading_days) * 100      AS volatility_pct,
    (AVG(daily_return) * :trading_days - :risk_free_rate)
        / NULLIF(STDDEV_SAMP(daily_return) * SQRT(:trading_days), 0) AS sharpe_ratio
FROM curve;

-- name: drawdown_curve
-- Each point's equity, the running peak so far, and the drawdown from it (%).
SELECT
    "timestamp",
    equity,
    running_peak,
    (running_peak - equity) / running_peak * 100 AS drawdown_pct
FROM (
    SELECT
        "timestamp",
        equity,
        MAX(equity) OVER (ORDER BY "timestamp"
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_peak
    FROM equity_curve
    WHERE backtest_run_id = :run_id
) AS curve
ORDER BY "timestamp";

-- name: rolling_sharpe
-- Sharpe over each trailing :window daily returns (63, about a quarter),
-- reported at the window's last point. Rows start once the window is full,
-- like pandas' rolling(window) with its default min_periods.
WITH returns AS (
    SELECT
        "timestamp",
        equity / NULLIF(LAG(equity) OVER (ORDER BY "timestamp"), 0) - 1 AS daily_return
    FROM equity_curve
    WHERE backtest_run_id = :run_id
),
windowed AS (
    SELECT
        "timestamp",
        COUNT(*)                  OVER w AS n,
        AVG(daily_return)         OVER w AS mean_return,
        STDDEV_SAMP(daily_return) OVER w AS sd_return
    FROM returns
    WHERE daily_return IS NOT NULL      -- the first point has no return
    WINDOW w AS (ORDER BY "timestamp" ROWS BETWEEN :window - 1 PRECEDING AND CURRENT ROW)
)
SELECT
    "timestamp",
    (mean_return * :trading_days - :risk_free_rate)
        / NULLIF(sd_return * SQRT(:trading_days), 0) AS sharpe_ratio
FROM windowed
WHERE n = :window
ORDER BY "timestamp";
