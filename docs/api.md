# REST API

Flask app in `app/`. Every backtest runs on the synthetic sample data (`data/sample_data.csv`), and the responses say so in a `data` object. Request and response bodies are JSON. Errors come back as `{"error": "<message>"}`:

- 400 for invalid input, with the reason (a missing field, an unknown strategy, profile or symbol, a parameter outside its limits, a date range with no bars, a non-positive capital);
- 404 for an unknown id;
- 500 for anything else. Its message is generic and the details go to the server log, because exception text can include SQL.

Money amounts are stored as `NUMERIC` and returned as JSON numbers. Timestamps are ISO 8601 in UTC with the offset, e.g. `2023-01-03T00:00:00+00:00`; dates are `YYYY-MM-DD`. See [database.md](database.md).

Base URL: `http://localhost:8000` with `make run` or `make dev`. The same server serves the React frontend at `/` (from `frontend/dist`; a 503 explains how to build it if it is missing).

| Method | Route | What it does |
| --- | --- | --- |
| POST | `/api/backtest/` | Run a backtest and store it, optionally with its unmanaged baseline |
| GET | `/api/backtest/<id>` | A stored run: metrics, equity curve and trades |
| GET | `/api/backtest/list?limit=50&strategy_id=` | Recent runs, newest first |
| POST | `/api/backtest/compare` | Two stored runs side by side |
| POST | `/api/backtest/regime-analysis` | One backtest, with daily returns split by regime |
| GET | `/api/data` | The data file: synthetic label, symbols, date range, number of bars |
| GET | `/api/strategies/` | Strategies, their stored parameters and each parameter's limits |
| GET | `/api/strategies/<id>` | One strategy |
| POST | `/api/strategies/` | Store a strategy record (name, description, parameters) |
| GET | `/api/risk-configs/` | Risk profiles |
| GET | `/api/risk-configs/<id>` | One risk profile |
| GET | `/health` | `{"status": "healthy"}` |

Strategies and risk profiles are seeded from `config/strategies.json` and `config/risk_configs.json` by `init_db.py`. `POST /api/strategies/` only stores a record. A strategy can be run only if `BacktestService.strategy_map` has a class for its name.

## POST /api/backtest/

```json
{
  "strategy_name": "Moving Average Crossover",
  "risk_config_name": "Moderate",
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 100000,
  "symbols": ["AAPL", "MSFT"],
  "parameters": {"fast_period": 10},
  "compare_to_baseline": true
}
```

`strategy_name`, `start_date`, `end_date` and `initial_capital` are required. The other fields:

- `risk_config_name` defaults to `"No Risk Management"`.
- `symbols` defaults to every symbol in the file.
- `parameters` overrides some or all of the strategy's stored parameters. Each must be a number within the strategy's limits (`parameter_limits` in `GET /api/strategies/`), with whole numbers for periods. MA crossover also needs fast < slow, and RSI needs oversold < overbought. The run stores the full set it used.
- `compare_to_baseline: true` first runs the same inputs with the risk profile whose risk layer is off, stores that run, and links the requested run to it. It is ignored when the chosen profile already has the risk layer off.
- `market_regime` is a free-text label stored with the run; it does not change the data.

`initial_capital` must be above 0 and at most 1,000,000,000,000; equity is stored as `NUMERIC(18, 4)`. Invalid input is rejected with a 400 before any run is stored.

The backtest runs inside the request; with a baseline there are two. Response fields:

- `backtest_id` (int) and `status` (`"completed"`)
- `metrics`:
  - `total_return`, `cagr`, `max_drawdown`, `volatility`, `win_rate`: percentages
  - `sharpe_ratio`
  - `avg_win`, `avg_loss`: dollars per closed trade
  - `num_trades`: closed trades
  - `final_equity`
  - `profit_factor`
  - `max_consecutive_wins`, `max_consecutive_losses`
- `summary`: `equity`, `cash`, `positions` and `total_return` after the forced close on the last bar
- `baseline`: `{"backtest_id", "risk_config", "metrics"}` for the baseline run, or `null`
- `data`: `{"synthetic": true, "file": "data/sample_data.csv", "description": "..."}`

## GET /api/backtest/&lt;id&gt;

The stored run:

- `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `initial_capital`, `symbols`, `market_regime`, `status`, `created_at`
- `strategy_parameters`: the parameters the run used; `null` for runs stored before they were recorded
- `baseline_run_id`: the run's unmanaged baseline, or `null`
- `metrics`: the stored subset; no profit factor or streaks
- `equity_curve`: one entry per bar, with `timestamp`, `equity`, `cash` and `positions_value`
- `trades`: closed round trips, each with `symbol`, `entry_date`, `exit_date`, `entry_price`, `exit_price`, `quantity`, `side`, `pnl`, `pnl_pct` and `status`. `side` is the side of the closing order, which is `"sell"` because the engine is long-only.
- `data`

## GET /api/backtest/list

Newest first: `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `symbols`, `initial_capital`, `baseline_run_id`, `status`, `total_return`, `max_drawdown`, `sharpe_ratio`, `created_at`.

## GET /api/data

```json
{"synthetic": true, "file": "data/sample_data.csv", "description": "...",
 "symbols": ["AAPL", "ABNB", "..."], "start_date": "2020-01-01", "end_date": "2024-12-31", "bars": 1305}
```

## GET /api/strategies/

Each strategy has `id`, `name`, `description`, `parameters` (stored defaults) and `parameter_limits`, e.g. `{"fast_period": {"type": "int", "min": 2, "max": 200}}`. `parameter_limits` is `null` for a stored strategy with no implementation.

## POST /api/backtest/compare

`{"baseline_id": 1, "comparison_id": 2}` returns:

- `baseline` and `comparison`, each with `id`, `strategy`, `risk_config` and `metrics`
- `differences`:
  - `total_return_diff`, `max_drawdown_diff`, `sharpe_ratio_diff`: comparison minus baseline
  - `drawdown_improvement_pct`: the drawdown reduction as a percentage of the baseline's drawdown

## POST /api/backtest/regime-analysis

Same body as a backtest, except that `start_date` and `end_date` are optional and default to the whole file. The service runs and stores one backtest. It then attributes each daily portfolio return to that day's regime from the data's `regime` column. The response:

- `backtest_id`, `metrics` and `data`
- `by_regime`: for each of `bull`, `bear` and `sideways`, the fields `days`, `compounded_return_pct`, `annualized_mean_return_pct` and `annualized_volatility_pct`

A data file without a `regime` column is rejected.

## Example

```bash
curl -s -X POST http://localhost:8000/api/backtest/ \
  -H "Content-Type: application/json" \
  -d '{"strategy_name":"RSI Mean Reversion","risk_config_name":"Moderate","start_date":"2022-01-01","end_date":"2023-12-31","initial_capital":100000,"symbols":["AAPL","MSFT"]}'
```

The tests in `tests/test_api.py` exercise these routes against a temporary SQLite database and, with `make test-pg` or in CI, against PostgreSQL.
