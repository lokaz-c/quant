# REST API

Flask app in `app/`. A backtest runs on the synthetic sample file (`data/sample_data.csv`) or on bars from the market-data service, and every run's `data` object says which, and what the service said the bars are (see [market-data.md](market-data.md)). Request and response bodies are JSON. Errors are RFC 9457 problem details (`application/problem+json`):

```json
{"title": "Bad Request", "status": 400, "detail": "Unknown symbol(s): NOPE",
 "instance": "/api/backtest/", "error": "Unknown symbol(s): NOPE"}
```

`type` is omitted, which RFC 9457 reads as `about:blank`: the status code is the problem type. `error` repeats `detail` for clients written against the earlier `{"error": "<message>"}` bodies. The statuses:

- 400 for invalid input, with the reason: a missing field, an unknown strategy, profile, symbol or data source, a parameter outside its limits, a date range with no bars, a non-positive capital, or a request over the server's caps (see [Limits](#limits-rate-limits-and-api-keys));
- 401 for an `X-API-Key` that is present but not valid;
- 404 for an unknown id or route; 405 for a method the route doesn't take;
- 409 for a strategy name that already exists;
- 413 for a body over 64 KiB;
- 429 when the client address is over a rate limit, with `Retry-After` in seconds;
- 502 when the market-data service fails: down, timing out, rate-limiting past the retries, or answering outside its contract. Nothing is stored;
- 503 with `Retry-After` when the server is already running as many backtests as it allows at once;
- 504 when a backtest runs past the time limit. The run is stopped between two bars and stored with status `failed`;
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
| GET | `/health` | `{"status": "healthy"}`; touches no database (Render's health check) |

Strategies and risk profiles are seeded from `config/strategies.json` and `config/risk_configs.json` by `init_db.py`. `POST /api/strategies/` only stores a record: `name` (1 to 255 characters, unique; a duplicate is a 409), an optional `description` (up to 2,000 characters) and `parameters` (an object with up to 50 entries). A strategy can be run only if `BacktestService.strategy_map` has a class for its name.

## Limits, rate limits and API keys

The API is meant to sit behind a public demo, so it caps what one request and one client can ask for. Every value is an environment variable read at startup (`app/config.py`, `.env.example`); the defaults are below.

| What | Default | Setting |
| --- | --- | --- |
| Symbols per run (omitting `symbols` selects every symbol in the file, which counts too) | 10 | `QUANT_MAX_SYMBOLS` |
| Period per run, calendar days from `start_date` to `end_date` inclusive | 1,827 (the synthetic file's 2020-2024) | `QUANT_MAX_RANGE_DAYS` |
| Time limit per request, both runs of a baseline pair together | 90 s | `QUANT_BACKTEST_TIMEOUT_SECONDS` |
| Backtests running at once in the process | 1 | `QUANT_MAX_CONCURRENT_RUNS` |
| Requests that run a backtest or store a record (`POST /api/backtest/`, `/api/backtest/regime-analysis`, `/api/strategies/`), one shared limit per client address | 5 per minute and 30 per hour | `QUANT_RATE_LIMIT_RUNS` |
| Every other `/api` request, per client address | 120 per minute | `QUANT_RATE_LIMIT_READS` |
| Request body | 64 KiB | fixed |
| `GET /api/backtest/list?limit=` | 1 to 500 | fixed |

Strategy parameters must be within each strategy's `parameter_limits`, and `initial_capital` must be above 0 and at most 1e12. Each symbol is 1 to 20 characters and `market_regime` at most 50, the widths of their columns. `GET /api/data` returns the caps as `limits`, so a client can stay inside them: `{"max_symbols": 10, "max_range_days": 1827, "timeout_seconds": 90.0}`. `/health` and the frontend's files are not rate limited.

**Rate limiting** uses Flask-Limiter with in-memory storage and the moving-window strategy. A client over a limit gets a 429 with `Retry-After` (seconds until the oldest counted request leaves the window) and a problem body. In-memory counters belong to one process. The Docker image runs one gunicorn process with four threads (`gunicorn.conf.py`), and Render's free tier runs a single instance, so the limits are exact. With more processes or instances, each would keep its own counters and the effective limit would multiply; `QUANT_RATE_LIMIT_STORAGE_URI=redis://...` shares them without code changes. The run-slot count is per process for the same reason. `QUANT_RATE_LIMITS=off` turns rate limiting off.

**Client address.** By default it is the TCP peer. Behind a proxy, every request comes from the proxy, so set `QUANT_CLIENT_IP_HEADER` to a header the proxy overwrites on every request. On Render this is Cloudflare's `CF-Connecting-IP`. `X-Forwarded-For` is not a good choice there: Render appends to the client's value instead of replacing it. A header the client controls would let it pick its own rate-limit bucket.

**API key.** `QUANT_API_KEY_SHA256` holds the SHA-256 hex digests of one or more keys, separated by commas. The server stores no keys, and compares digests in constant time. A request with a valid `X-API-Key` header is not rate limited; this is for server-side clients such as TradeDesk. It still gets the caps, the time limit and the run slots. A key that is present but wrong is a 401, so a misconfigured client finds out instead of being limited silently; the market-data service uses the same rule. Without the header, a request is anonymous.

**CORS.** `QUANT_CORS_ORIGINS` lists the exact origins (`https://host[:port]`) that may call `/api` from a browser, for `GET` and `POST` with a `Content-Type` header. The default is none, so there are no CORS headers: the bundled frontend is same-origin, and server-side clients aren't subject to CORS. `*` is refused at startup.

**Time limit.** The engine checks the deadline before each bar and stops with a 504 once it has passed. Python can't kill a running thread from outside, so the check is cooperative. A bar takes well under a millisecond on a laptop, so the overshoot is small. The deadline starts when the request arrives, so a slow market-data fetch counts too. A stopped run is stored with status `failed`. In a container limited to Render's free size (`make deploy-check`), the frontend's default request took 1.7 to 3.7 s and the largest run the default caps allow 8.6 to 10.1 s. Before indicators were precomputed they took about a minute and more than 90 s (a 504); the README's [Deploying](../README.md#deploying) section has the output. The limit stays at 90 s. The backtest no longer needs that much, but a market-data fetch counts against the same limit, and a free Render service that has spun down takes about a minute to answer. A lower limit would turn those first requests into 504s.

**Run slot.** One backtest runs at a time per process, and another run request meanwhile gets a 503 with `Retry-After: 10`. It stays at one. A run is CPU-bound and the instance has 0.1 CPU, so two runs at once would share the CPU rather than finish sooner. A busy slot now clears within seconds, well inside the 10 s retry.

**No async endpoint.** A run happens inside the request; there is no 202-and-poll endpoint. On a single 0.1 CPU instance, a background thread would compete with request threads for the one CPU and the GIL. Queued runs would also be lost whenever the instance restarts or spins down, and a durable queue needs a second service. The time limit, the run slot and the caps bound a request instead.

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
- `symbols` defaults to every symbol in the file; that counts against the symbol cap (25 in the file, 10 allowed by default), so send them.
- `parameters` overrides some or all of the strategy's stored parameters. Each must be a number within the strategy's limits (`parameter_limits` in `GET /api/strategies/`), with whole numbers for periods. MA crossover also needs fast < slow, and RSI needs oversold < overbought. The run stores the full set it used.
- `compare_to_baseline: true` first runs the same inputs with the risk profile whose risk layer is off, stores that run, and links the requested run to it. It is ignored when the chosen profile already has the risk layer off.
- `market_regime` is a free-text label stored with the run; it does not change the data.
- `data_source` is `"synthetic"` or `"market-data"`; the server's default (`QUANT_DATA_SOURCE`) if omitted. `"market-data"` needs `MARKET_DATA_URL` on the server, and explicit `symbols`, each listed by the service's `/v1/symbols` for this server. The bars are fetched once, before anything is stored, and a baseline pair shares them.

`initial_capital` must be above 0 and at most 1,000,000,000,000; equity is stored as `NUMERIC(18, 4)`. Invalid input, or a request over the [caps](#limits-rate-limits-and-api-keys), is rejected with a 400 before any run is stored.

The backtest runs inside the request; with a baseline there are two, and the time limit covers both. Response fields:

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

Newest first, at most `limit` rows (1 to 500, default 50): `id`, `strategy`, `risk_config`, `start_date`, `end_date`, `symbols`, `initial_capital`, `baseline_run_id`, `status`, `total_return`, `max_drawdown`, `sharpe_ratio`, `undefined_metrics` (the reason for any of those three that is `null`; `null` for a run with no metrics), `created_at`, `data_source`, `reported_source`, `synthetic`.

## GET /api/data

The default source, or `?source=synthetic|market-data`. The same label fields as a run's `data`, plus `symbols`, `start_date`, `end_date`, `bars` (business days in the file; `null` for market-data), `available_sources`, `default_source` and `limits` (the [caps](#limits-rate-limits-and-api-keys) on a run). For market-data, the label comes from the sources of every symbol the service lists for this server.

```json
{"source": "synthetic", "reported_source": "synthetic", "synthetic": true, "description": "...",
 "file": "data/sample_data.csv", "symbols": ["AAPL", "ABNB", "..."], "start_date": "2020-01-01",
 "end_date": "2024-12-31", "bars": 1305, "available_sources": ["synthetic"], "default_source": "synthetic",
 "limits": {"max_symbols": 10, "max_range_days": 1827, "timeout_seconds": 90.0}}
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

Only the synthetic file has regime labels. When market-data is the server's default, send `"data_source": "synthetic"`; otherwise the request is a 400. The run counts against the same rate limit, caps and time limit as `POST /api/backtest/`; without `symbols` it would select all 25 and exceed the default symbol cap.

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
