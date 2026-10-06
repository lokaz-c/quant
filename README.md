# Quant Portfolio Simulator

A backtesting engine for daily-bar trading strategies, with a risk-management layer, a metrics module, a Flask REST API and a small web dashboard. Results are stored in PostgreSQL.

**The bundled price data is synthetic.** `data/sample_data.csv` (25 symbols, 2020–2024, 32,625 rows) is written by `python -m backtest_engine.data_loader` (seed 42): a seeded Markov chain switches between bull, bear and sideways regimes using the transition matrix in `config/data_generator.json`, and each symbol's closes follow a geometric Brownian motion with the current regime's drift and volatility. The regime of each day is in the `regime` column. Ticker names are labels only. Any CSV with the columns `timestamp, symbol, open, high, low, close, volume` can be used instead; nothing in the engine depends on the data being synthetic.

## How it fits together

```
templates/index.html   Chart.js dashboard: pick a strategy, risk profile and date range, see the equity curve
app/routes/            Flask blueprints: /api/backtest, /api/strategies, /api/risk-configs
app/services/          BacktestService: loads data, runs the engine, writes results to PostgreSQL
backtest_engine/       Backtester, Portfolio, RiskManager, PerformanceMetrics, StrategyBase + 3 strategies
db/init.sql            strategies, risk_configs, backtest_runs, backtest_metrics, equity_curve, trades
live_trading/          Alpaca paper-trading adapter on alpaca-py (see below)
tests/                 pytest: data generator, regimes, strategies, metrics, portfolio, risk, API, live trading
```

The engine steps through the data one trading day at a time. On each bar it marks positions to the close, applies stop-loss / take-profit and drawdown checks, asks the strategy for orders, runs those orders through the risk rules, and fills them at that bar's close. Open positions are closed on the last bar.

## Run it

Docker (starts PostgreSQL 15 and the app; the sample data is committed):

```bash
docker-compose up --build
# http://localhost:8000  (QUANT_PORT=... to change; macOS uses 5000 for AirPlay)
```

Local:

```bash
pip install -r requirements.txt
python init_db.py                         # SQLite by default; set DATABASE_URL for PostgreSQL
python -m backtest_engine.data_loader     # optional: regenerates data/sample_data.csv
python -m app.main                        # http://localhost:8000
```

Python 3.11. `make help` lists the other targets (test, generate-data, run-example, db-shell).

## Use it

From Python:

```python
from backtest_engine.backtester import Backtester
from backtest_engine.data_loader import DataLoader
from backtest_engine.risk import RiskConfig
from backtest_engine.strategies.moving_average import MovingAverageCrossover

loader = DataLoader("data/sample_data.csv")
risk = RiskConfig(name="Conservative", max_position_size=0.15, stop_loss_pct=0.05)
results = Backtester(MovingAverageCrossover(), loader, 100_000, risk).run()
print(results["metrics"]["sharpe_ratio"])
```

From the API:

| Method | Route | What it does |
| --- | --- | --- |
| POST | `/api/backtest/` | Run a backtest: `strategy_name`, `risk_config_name`, `start_date`, `end_date`, `initial_capital`, `symbols` |
| GET | `/api/backtest/<id>` | Metrics, equity curve and trades for a run |
| GET | `/api/backtest/list` | Recent runs |
| POST | `/api/backtest/compare` | Two runs side by side (`baseline_id`, `comparison_id`) |
| POST | `/api/backtest/regime-analysis` | One backtest, with daily returns split by the generator's regime labels |
| GET, POST | `/api/strategies/` | List strategies, register a strategy with parameters |
| GET | `/api/risk-configs/` | List risk profiles |
| GET | `/health` | Liveness check |

```bash
curl -X POST http://localhost:5000/api/backtest/ -H "Content-Type: application/json" \
  -d '{"strategy_name":"RSI Mean Reversion","risk_config_name":"Moderate","start_date":"2022-01-01","end_date":"2023-12-31","initial_capital":100000,"symbols":["AAPL","MSFT"]}'
```

## Strategies

All three subclass `StrategyBase` and implement `generate_signals(data, portfolio) -> List[Order]`; a new strategy is one file plus an entry in `BacktestService.strategy_map`.

- **Moving Average Crossover** — long when the 20-day MA crosses above the 50-day, flat when it crosses back.
- **RSI Mean Reversion** — 14-day RSI; buy below 30, sell above 70.
- **Trend Following** — enter when the close breaks above the previous 20-day high; exit on a break below the previous 20-day low or a chandelier-style stop (20-day high minus 2 × 14-day ATR).

## Risk rules

`RiskConfig` fields, each optional: `max_position_size` and `max_portfolio_exposure` (fractions of equity; oversized orders are cut down, not rejected), `stop_loss_pct`, `take_profit_pct`, and `max_drawdown_pct` (stops trading for the run once breached). Four profiles are seeded from `config/risk_configs.json`: Conservative (15% max position, 60% max exposure, 5% stop, 15% take-profit, halt at 20% drawdown), Moderate (20% / 80% / 8% / 20% / 30%), Aggressive (30% / 100% / 12% / 30% / 40%) and a no-limits baseline for comparison.

## Metrics

Total return, CAGR, max drawdown, annualised volatility, Sharpe (2% risk-free), win rate, average win / loss, profit factor, trade count, longest win / loss streaks, monthly returns and the full equity curve.

## Tests and CI

84 pytest tests cover the data generator (cross-process determinism, Markov transition frequencies and regime durations), strategies, metrics, portfolio accounting, risk rules, the Flask API and the paper-trading adapter. GitHub Actions runs them on Python 3.10 and 3.11; mypy runs on the engine as an advisory step.

```bash
pytest                     # or: make test
pytest --cov=backtest_engine --cov=app
```

## Live trading (experimental)

`live_trading/` wraps Alpaca's alpaca-py SDK (`AlpacaBroker`) and runs one of the backtest strategies on daily bars (`LiveTrader`). Paper trading is the default; live trading requires both `paper=False` and `QUANT_ALLOW_LIVE_TRADING=yes`. Install with `pip install -r requirements-live.txt`. The tests use fake clients; nothing here has been run against a funded account. Alpaca is the only broker implemented.

## Known limitations

- Fills happen at the same bar's close with no commission, slippage or partial fills, so results are optimistic.
- The sample data is synthetic (above). Real backtests need real, survivorship-bias-free data.
- Single-process: a backtest runs inside the request that started it.

## Deploying

`Dockerfile`, `docker-compose.yml`, `Procfile`, `render.yaml` and `runtime.txt` are included; the app serves under gunicorn and reads `DATABASE_URL` and `SECRET_KEY` from the environment (`.env.example`).

## License

MIT.
