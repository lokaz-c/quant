# REST API

Flask app in `app/`. A backtest runs on the synthetic sample file (`data/sample_data.csv`) or on bars from the market-data service, and every run's `data` object says which, and what the service said the bars are (see [market-data.md](market-data.md)). Request and response bodies are JSON. Errors come back as `{"error": "<message>"}`:

- 400 for invalid input, with the reason (a missing field, an unknown strategy, profile, symbol or data source, a parameter outside its limits, a date range with no bars, a non-positive capital);
- 404 for an unknown id;
- 502 when the market-data service fails: down, timing out, rate-limiting past the retries, or answering outside its contract. Nothing is stored;
- 500 for anything else. Its message is generic and the details go to the server log, because exception text can include SQL.

Bodies are strict JSON (RFC 8259) both ways: the server never writes `NaN`, `Infinity` or `-Infinity`, and a request that contains them, or a number too large for a double such as `1e400`, is a 400. A metric that has no value for a run is `null`, with the reason in `undefined_metrics`; see [Undefined metrics](#undefined-metrics).

Money amounts are stored as `NUMERIC` and returned as JSON numbers. Timestamps are ISO 8601 in UTC with the offset, e.g. `2023-01-03T00:00:00+00:00`; dates are `YYYY-MM-DD`. See [database.md](database.md).

Base URL: `http://localhost:8000` with `make run` or `make dev`. The same server serves the React frontend at `/` (from `frontend/dist`; a 503 explains how to build it if it is missing).

| Method | Route | What it does |
| --- | --- | --- |
| POST | `/api/backtest/` | Run a backtest and store it, optionally with its unmanaged baseline |
| GET | `/api/backtest/<id>` | A stored run: metrics, equity curve and trades |
| GET | `/api/backtest/list?limit=50&strategy_id=` | Recent runs, newest first |
| POST | `/api/backtest/compare` | Two stored runs side by side |
| POST | `/api/backtest/regime-analysis` | One backtest, with daily returns split by regime |
| GET | `/api/data?source=` | The data source a run would use: its label, symbols and date range |
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
  "compare_to_baseline": true,
  "data_source": "market-data"
}
```

`strategy_name`, `start_date`, `end_date` and `initial_capital` are required. The other fields:

- `risk_config_name` defaults to `"No Risk Management"`.
- `symbols` defaults to every symbol in the file.
- `parameters` overrides some or all of the strategy's stored parameters. Each must be a number within the strategy's limits (`parameter_limits` in `GET /api/strategies/`), with whole numbers for periods. MA crossover also needs fast < slow, and RSI needs oversold < overbought. The run stores the full set it used.
- `compare_to_baseline: true` first runs the same inputs with the risk profile whose risk layer is off, stores that run, and links the requested run to it. It is ignored when the chosen profile already has the risk layer off.
- `market_regime` is a free-text label stored with the run; it does not change the data.
- `data_source` is `"synthetic"` or `"market-data"`; the server's default (`QUANT_DATA_SOURCE`) if omitted. `"market-data"` needs `MARKET_DATA_URL` on the server, and explicit `symbols`, each listed by the service's `/v1/symbols` for this server. The bars are fetched once, before anything is stored, and a baseline pair shares them.

`initial_capital` must be above 0 and at most 1,000,000,000,000; equity is stored as `NUMERIC(18, 4)`. Invalid input is rejected with a 400 before any run is stored.

The backtest runs inside the request; with a baseline there are two. Response fields:

- `backtest_id` (int) and `status` (`"completed"`)
- `metrics`:
  - `total_return`, `cagr`, `max_drawdown`, `volatility`, `win_rate`: percentages
  - `sharpe_ratio`
  - `avg_win`, `avg_loss`: dollars per closed trade
  - `num_trades`: closed trades
  - `final_equity`
  - `profit_factor`: gross profit / gross loss; `null` when no closed trade lost money
  - `max_consecutive_wins`, `max_consecutive_losses`
- `undefined_metrics`: the reason for each `null` in `metrics`, e.g. `{"profit_factor": "no losing trades"}`; `{}` when every metric is defined
- `summary`: `equity`, `cash`, `positions` and `total_return` after the forced close on the last bar
- `baseline`: `{"backtest_id", "risk_config", "metrics", "undefined_metrics"}` for the baseline run, or `null`
- `data`: where the bars came from:
  - `source`: `"synthetic"` (the local file) or `"market-data"`
  - `reported_source`: what the service reported: `"alpaca"`, `"synthetic"`, or `"mixed"` when the symbols disagree; always `"synthetic"` for the local file
  - `synthetic`: `false` only when `source` is `"market-data"` and the service reported `"alpaca"` for every symbol
  - `description`: one sentence for display
  - local file: `file`; market-data: `symbol_sources` (`{"AAPL": "alpaca", ...}`) and `adjustment` (`"split"` or `"raw"`)

```json
{"source": "market-data", "reported_source": "synthetic", "synthetic": true,
 "description": "Synthetic daily bars generated by the market-data service (it labels them source=synthetic). They are not market prices.",
 "symbol_sources": {"S001": "synthetic", "S002": "synthetic"}, "adjustment": "split"}
```

## GET /api/backtest/&lt;id&gt;

The stored run:

- `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `initial_capital`, `symbols`, `market_regime`, `status`, `created_at`
- `strategy_parameters`: the parameters the run used; `null` for runs stored before they were recorded
- `baseline_run_id`: the run's unmanaged baseline, or `null`
- `metrics`: the stored subset; no profit factor or streaks. `null` for a run with no metrics (status `failed`)
- `undefined_metrics`: the reason for each `null` in `metrics`; `null` when `metrics` is
- `equity_curve`: one entry per bar, with `timestamp`, `equity`, `cash` and `positions_value`
- `trades`: closed round trips, each with `symbol`, `entry_date`, `exit_date`, `entry_price`, `exit_price`, `quantity`, `side`, `pnl`, `pnl_pct` and `status`. `side` is the side of the closing order, which is `"sell"` because the engine is long-only.
- `data`: as stored with the run (migration `0004`); runs from before it read as the local synthetic file

## GET /api/backtest/list

Newest first: `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `symbols`, `initial_capital`, `baseline_run_id`, `status`, `total_return`, `max_drawdown`, `sharpe_ratio`, `undefined_metrics` (the reason for any of those three that is `null`; `null` for a run with no metrics), `created_at`, `data_source`, `reported_source`, `synthetic`.

## GET /api/data

The default source, or `?source=synthetic|market-data`. The same label fields as a run's `data`, plus `symbols`, `start_date`, `end_date`, `bars` (business days in the file; `null` for market-data), `available_sources` and `default_source`. For market-data, the label comes from the sources of every symbol the service lists for this server.

```json
{"source": "synthetic", "reported_source": "synthetic", "synthetic": true, "description": "...",
 "file": "data/sample_data.csv", "symbols": ["AAPL", "ABNB", "..."], "start_date": "2020-01-01",
 "end_date": "2024-12-31", "bars": 1305, "available_sources": ["synthetic"], "default_source": "synthetic"}
```

## GET /api/strategies/

Each strategy has `id`, `name`, `description`, `parameters` (stored defaults) and `parameter_limits`, e.g. `{"fast_period": {"type": "int", "min": 2, "max": 200}}`. `parameter_limits` is `null` for a stored strategy with no implementation.

## POST /api/backtest/compare

`{"baseline_id": 1, "comparison_id": 2}` returns:

- `baseline` and `comparison`, each with `id`, `strategy`, `risk_config`, `metrics` and `undefined_metrics`
- `differences`:
  - `total_return_diff`, `max_drawdown_diff`, `sharpe_ratio_diff`: comparison minus baseline; `null` if the metric is undefined for either run
  - `drawdown_improvement_pct`: the drawdown reduction as a percentage of the baseline's drawdown; `null` if the baseline had no drawdown
- `undefined_differences`: the reason for each `null` in `differences`, e.g. `{"sharpe_ratio_diff": "sharpe_ratio is undefined for the comparison run"}`

A run with no metrics (status `failed`) is a 400.

## POST /api/backtest/regime-analysis

Same body as a backtest, except that `start_date` and `end_date` are optional and default to the whole file. The service runs and stores one backtest. It then attributes each daily portfolio return to that day's regime from the data's `regime` column. The response:

- `backtest_id`, `metrics`, `undefined_metrics` and `data`
- `by_regime`: for each of `bull`, `bear` and `sideways`, the fields `days`, `compounded_return_pct`, `annualized_mean_return_pct`, `annualized_volatility_pct` (`null` for a regime with a single day) and `undefined_metrics`

Only the synthetic file has regime labels. When market-data is the server's default, send `"data_source": "synthetic"`; otherwise the request is a 400.

## Undefined metrics

Some metrics have no value for some runs: a ratio whose denominator is zero, or a mean or standard deviation over too few values. Python's `json` module would write these as the bare tokens `NaN` or `Infinity`, which are not JSON (`JSON.parse` rejects them). The API's convention instead:

- the metric is `null`;
- the object that holds it has a sibling `undefined_metrics` object (`undefined_differences` for the comparison's `differences`) mapping each `null` metric to the reason. Every `null` metric has an entry, and nothing else does.

| Metric | `null` when | Reason |
| --- | --- | --- |
| `volatility` | fewer than two daily returns (the sample standard deviation needs two) | `fewer than two daily returns` |
| `sharpe_ratio` | fewer than two daily returns, or zero volatility | `fewer than two daily returns`, `zero volatility` |
| `cagr` | the run covers a single day | `the run starts and ends on the same day` |
| `win_rate` | no closed trades | `no closed trades` |
| `avg_win` | no closed trades, or none that won | `no closed trades`, `no winning trades` |
| `avg_loss` | no closed trades, or none that lost | `no closed trades`, `no losing trades` |
| `profit_factor` | no closed trades, or none that lost (the ratio would be infinite, or 0/0 when every trade broke even) | `no closed trades`, `no losing trades` |
| any | the computed value is not finite (a CAGR that overflows over a very short run) | `the result is not a finite number` |

`total_return`, `max_drawdown`, `num_trades`, `final_equity` and the streaks are always numbers. A profit factor of 0 (losing trades, no winners) is a number, as is a win rate of 0. Runs stored before migration `0005` may have a `null` with the reason `undefined; the reason was not recorded for this run`, and keep the 0.0 Sharpe the engine used to report for a flat curve. The database stores `NULL` and the reasons (see [database.md](database.md#undefined-metrics)), and `sql/metrics.sql` returns `NULL` in the same cases. The frontend shows `n/a` with the reason.

Trend Following on the synthetic AAPL series, 2023-01-01 to 2023-06-30, makes one trade, a winner. Its response (other fields left out):

```json
"metrics": {"total_return": 0.7534502051473246, "win_rate": 100.0, "avg_win": 753.4502051473319,
            "avg_loss": null, "num_trades": 1, "profit_factor": null, ...},
"undefined_metrics": {"avg_loss": "no losing trades", "profit_factor": "no losing trades"}
```

The JSON encoder runs with `allow_nan=False` (`app/strict_json.py`), so a non-finite value that slips through is a 500 and a logged error rather than invalid JSON, and the test suite fails.

## Example

```bash
curl -s -X POST http://localhost:8000/api/backtest/ \
  -H "Content-Type: application/json" \
  -d '{"strategy_name":"RSI Mean Reversion","risk_config_name":"Moderate","start_date":"2022-01-01","end_date":"2023-12-31","initial_capital":100000,"symbols":["AAPL","MSFT"]}'
```

The tests in `tests/test_api.py` exercise these routes against a temporary SQLite database and, with `make test-pg` or in CI, against PostgreSQL.
