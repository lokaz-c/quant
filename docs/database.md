# Database

The schema is managed by Alembic (`alembic.ini`, `migrations/`). The SQLAlchemy models in `app/models/database.py` must match the head revision; `tests/test_migrations.py` checks this by running Alembic's autogenerate comparison against a freshly migrated database.

## Creating and upgrading a database

```bash
make migrate            # alembic upgrade head on $DATABASE_URL (default sqlite:///quant.db)
python init_db.py       # the same upgrade, then seed strategies and risk profiles from config/
```

`make run` (Docker) and `make dev` both run `init_db.py` once before the app starts. Nothing else creates tables: the old `db/init.sql` and `Base.metadata.create_all()` paths are gone.

A database created before Alembic, by `db/init.sql` or `create_all()`, has the tables but no `alembic_version` table. `init_db.py` stamps it as revision `0001` and then upgrades it, so an existing Docker volume keeps its runs. Plain `alembic upgrade head` does not do this; it would try to create tables that already exist. Use `alembic stamp 0001` first in that case.

New migration: change the models, then `alembic revision --autogenerate -m "..."`, read the generated file, and add a test. Autogenerate does not detect CHECK constraints, so write those by hand.

## Revisions

| Revision | What it does |
| --- | --- |
| `0001` | Baseline: the schema `db/init.sql` used to create. On PostgreSQL, `pg_dump --schema-only` of a database built by `alembic upgrade 0001` is identical to one built by the old `init.sql` (checked before `init.sql` was deleted). |
| `0002` | Money columns to `NUMERIC`, timestamps to `TIMESTAMPTZ`, CHECK constraints, and a unique index on `equity_curve(backtest_run_id, timestamp)`. |
| `0003` | `backtest_runs.strategy_parameters` (the parameters a run used: the stored defaults merged with the request's overrides) and `backtest_runs.baseline_run_id` (a self-reference to the unmanaged run on the same inputs, `ON DELETE SET NULL`). Existing rows get `NULL`. |

## Column types

| Columns | Type | Why |
| --- | --- | --- |
| `backtest_runs.initial_capital`, `backtest_metrics.final_equity`, `avg_win`, `avg_loss`, `equity_curve.equity`, `cash`, `positions_value`, `trades.pnl` | `NUMERIC(18, 4)` | Dollar amounts. See below. |
| `trades.entry_price`, `exit_price` | `NUMERIC(18, 4)` | Per-share prices. SEC Rule 612 sets the smallest quote increment for US stocks: $0.0001 below $1.00, and $0.01 (or $0.005 under the 2024 amendment) above. Four decimal places hold any of them exactly. The synthetic data has two. |
| `trades.quantity` | `NUMERIC(18, 9)` | The engine sizes positions in fractional shares (equity x weight / price). Alpaca, the paper-trading broker, accepts quantities with up to 9 decimal places. |
| returns, drawdown, volatility, Sharpe, win rate, `pnl_pct`, the risk limits in `risk_configs` | `double precision` | Dimensionless ratios computed in float64 by numpy and pandas. Storing them as `NUMERIC` would suggest an exactness they never had. |
| every timestamp | `TIMESTAMPTZ` | An instant, not a wall-clock reading. See below. |
| `start_date`, `end_date` | `DATE` | Unchanged. |

**Why `NUMERIC(18, 4)` for money.** Precision 18 leaves 14 digits before the decimal point, which is far beyond any balance this simulator produces. It also means every value fits a signed 64-bit integer count of ten-thousandths of a dollar, if another service ever reads these columns as fixed-point integers. Four decimal places rather than two (cents), because these columns are not cash-ledger entries. They are marks and averages: fractional-share quantity times price, and mean P&L per trade. Rounding them to cents would add up to half a cent of error to every equity point. At four places the stored value is within $0.00005 of the engine's float, about 5e-10 of a $100,000 account. That keeps drawdown and Sharpe computed in SQL from the stored curve within a tight tolerance of the engine's own numbers.

The engine itself still computes in float64; `NUMERIC` makes the stored record exact and stops the database from adding its own binary rounding. Values read back are `decimal.Decimal`. The API converts them to JSON numbers (`_num` in `app/services/backtest_service.py`), because Flask would otherwise serialise a `Decimal` as a string. `PerformanceMetrics` and `returns_by_regime` cast equity to float, because pandas' `pct_change` raises `TypeError` on a column of `Decimal`s.

**Why `TIMESTAMPTZ`.** The app has always written UTC: `datetime.utcnow()` for `created_at` and `completed_at`, and bar dates at midnight for equity points and trades. `TIMESTAMP WITHOUT TIME ZONE` stores the wall time and drops that fact, so a reader in another time zone could shift it. Migration `0002` converts with `USING col AT TIME ZONE 'UTC'`. Without that clause PostgreSQL reads the old values in the session's `TimeZone` setting. A test runs the upgrade with the session set to `America/New_York` and checks that midnight UTC stays midnight UTC. `UTCDateTime` in the models writes naive datetimes as UTC and always returns aware UTC datetimes, so the API now returns timestamps with an offset, e.g. `2023-01-03T00:00:00+00:00`.

## Constraints and indexes

CHECK constraints list exactly the values the code writes:

| Constraint | Allowed values | Written by |
| --- | --- | --- |
| `ck_backtest_runs_status` | `pending`, `running`, `completed`, `failed` | the column default; `BacktestService.run_backtest` |
| `ck_trades_side` | `buy`, `sell` | `Portfolio` (stored trades are closed round trips, so `sell`) |
| `ck_trades_status` | `open`, `closed` | `Portfolio` (only `closed` is stored) |

`ix_equity_curve_run_timestamp` is a unique index on `equity_curve(backtest_run_id, timestamp)`. It is unique because the engine records exactly one equity point per bar, so a duplicate would mean a bug, and it would distort any metric computed from the curve. It is the access path for loading a run's curve in time order. It replaces the single-column `idx_equity_curve_run`, which it makes redundant: a B-tree on `(a, b)` also serves lookups on `a`.

## SQLite

SQLite is supported for local development (`make dev`) and the default test run.

- Migrations use Alembic batch mode on SQLite, because it can't `ALTER` a column type or add a constraint in place. Batch mode rebuilds each table and copies the rows. On PostgreSQL the same migration runs as plain `ALTER TABLE`.
- CHECK constraints and the unique index work the same as on PostgreSQL; the constraint tests run on both.
- SQLite has no fixed-point type. `NUMERIC(18, 4)` columns have NUMERIC affinity and store an integer or an 8-byte float, so precision and scale are not enforced. SQLAlchemy rounds to the declared scale when reading.
- SQLite has no time zone type. Timestamps are stored as UTC text and `UTCDateTime` attaches UTC when reading them.
- `JSONB` is `JSON` on SQLite.

## Tests

`tests/test_migrations.py` runs on SQLite and, when `QUANT_TEST_POSTGRES_URL` is set, on PostgreSQL:

- upgrade to head on an empty database, then downgrade to base;
- the models match the head revision;
- each CHECK constraint and the unique index reject a bad row, and the same statement with valid values succeeds;
- a pre-Alembic database is stamped and upgraded with its rows intact;
- PostgreSQL only: the column types after the upgrade, and that existing rows survive the upgrade and the downgrade (values rounded to the new scale, timestamps unchanged).

The API tests in `tests/test_api.py` also run on both databases. `make test-pg` starts a throwaway `postgres:15-alpine` container and runs the whole suite against it. CI uses a PostgreSQL service container and sets `QUANT_REQUIRE_POSTGRES=1`, so a missing database fails the build instead of skipping the tests.
