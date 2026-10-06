# REST API

Flask app in `app/`. Every backtest runs on the synthetic sample data (`data/sample_data.csv`), and the responses say so in a `data` object. Request and response bodies are JSON. Errors come back as `{"error": "<message>"}`, with status 400 for a missing field, 404 for an unknown id and 500 for anything else.

Money amounts are stored as `NUMERIC` and returned as JSON numbers. Timestamps are ISO 8601 in UTC with the offset, e.g. `2023-01-03T00:00:00+00:00`; dates are `YYYY-MM-DD`. See [database.md](database.md).

Base URL: `http://localhost:8000` with `make run` or `make dev`.

| Method | Route | What it does |
| --- | --- | --- |
| POST | `/api/backtest/` | Run a backtest and store it |
| GET | `/api/backtest/<id>` | A stored run: metrics, equity curve and trades |
| GET | `/api/backtest/list?limit=50&strategy_id=` | Recent runs, newest first |
| POST | `/api/backtest/compare` | Two stored runs side by side |
| POST | `/api/backtest/regime-analysis` | One backtest, with daily returns split by regime |
| GET | `/api/strategies/` | Strategies and their stored parameters |
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
  "symbols": ["AAPL", "MSFT"]
}
```

`strategy_name`, `start_date`, `end_date` and `initial_capital` are required. `risk_config_name` defaults to `"No Risk Management"`. `symbols` defaults to every symbol in the file. Optionally, `market_regime` is a free-text label stored with the run; it does not change the data.

The backtest runs inside the request. Response fields:

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
- `data`: `{"synthetic": true, "file": "data/sample_data.csv", "description": "..."}`

## GET /api/backtest/&lt;id&gt;

The stored run:

- `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `initial_capital`, `symbols`, `market_regime`, `status`, `created_at`
- `metrics`: the stored subset; no profit factor or streaks
- `equity_curve`: one entry per bar, with `timestamp`, `equity`, `cash` and `positions_value`
- `trades`: closed round trips, each with `symbol`, `entry_date`, `exit_date`, `entry_price`, `exit_price`, `quantity`, `side`, `pnl`, `pnl_pct` and `status`. `side` is the side of the closing order, which is `"sell"` because the engine is long-only.
- `data`

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
