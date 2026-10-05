# Quant Portfolio Simulator

[![CI](https://github.com/lokaz-c/quant/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lokaz-c/quant/actions/workflows/ci.yml)

A daily-bar backtesting engine with three strategies, a risk layer that can be switched on and off, a performance-metrics module, a Flask REST API with a small dashboard, and a paper-trading adapter for Alpaca. I built it to answer one question: what does a simple risk layer (position caps, stop-losses, a drawdown halt) do to a strategy compared with running it unmanaged? I wanted the answer measured by code anyone can re-run.

**The price data is synthetic.** It comes from a seeded generator: a Markov chain switches between bull, bear and sideways regimes, and each symbol follows a geometric Brownian motion with the current regime's drift and volatility. Ticker names are labels only. See [docs/data.md](docs/data.md). Any CSV with `timestamp, symbol, open, high, low, close, volume` columns can be used instead.

## Architecture

```mermaid
flowchart LR
    subgraph data["Synthetic data"]
        cfg["config/data_generator.json<br/>regimes + transition matrix"] --> gen["generate_sample_data<br/>Markov regimes, GBM prices"]
        gen --> csv[("data/sample_data.csv")]
    end
    csv --> loader["DataLoader"]
    loader --> engine["Backtester<br/>bar-by-bar loop"]
    strategies["Strategies<br/>MA crossover, RSI, breakout"] --> engine
    risk["RiskManager<br/>caps, stops, drawdown halt"] --> engine
    engine --> portfolio["Portfolio<br/>fills at the close"]
    engine --> metrics["PerformanceMetrics"]
    metrics --> service["BacktestService"]
    service --> db[("PostgreSQL or SQLite")]
    api["Flask REST API"] --> service
    ui["Dashboard<br/>Chart.js"] --> api
    strategies --> trader["LiveTrader"]
    risk --> trader
    trader --> broker["AlpacaBroker<br/>paper by default"]
```

On each bar the engine:

1. marks positions to the close;
2. if the risk layer is on, applies stop-loss and take-profit and checks drawdown;
3. asks the strategy for orders;
4. passes them through the risk rules;
5. fills them at that bar's close.

Open positions are closed on the last bar. Each run is stored with its equity curve and trades.

## Run it

```bash
git clone https://github.com/lokaz-c/quant && cd quant
make run          # docker compose up --build: PostgreSQL 15 + the app
# open http://localhost:8000  (QUANT_PORT=9000 make run to use another port)
```

I checked this from a clean clone. It needs Docker. The sample data is committed, and `init_db.py` seeds the strategies and risk profiles from `config/` on start.

Without Docker (Python 3.10 or 3.11, SQLite):

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
make dev          # http://localhost:8000
make test
```

`make help` lists the other targets: `data`, `results`, `bench`, `down`, `db-shell`.

## Results

`make results` runs each strategy with the risk layer off and under each risk profile. It uses 5 symbols, 2020-01-01 to 2024-12-31 (1,305 bars), $100,000 of capital and the seed-42 data file, and writes [docs/results.md](docs/results.md). The run has no randomness and the file has no timestamps, so it is reproducible byte for byte. CI regenerates it and fails if the committed copy is stale. Excerpt, with the risk layer off ("No Risk Management") and with the Conservative profile:

| Strategy | Risk profile | Total return | CAGR | Max drawdown | Volatility | Sharpe | Trades | Win rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Moving Average Crossover | No Risk Management | 1.51% | 0.30% | 20.24% | 6.89% | -0.21 | 58 | 41.38% |
| Moving Average Crossover | Conservative | 16.94% | 3.18% | 5.09% | 4.13% | 0.27 | 61 | 42.62% |
| RSI Mean Reversion | No Risk Management | -29.04% | -6.63% | 37.53% | 7.58% | -1.10 | 71 | 53.52% |
| RSI Mean Reversion | Conservative | -15.79% | -3.38% | 20.63% | 4.88% | -1.06 | 121 | 41.32% |
| Trend Following | No Risk Management | -2.28% | -0.46% | 17.06% | 4.60% | -0.51 | 84 | 39.29% |
| Trend Following | Conservative | -1.87% | -0.38% | 13.26% | 3.41% | -0.68 | 87 | 37.93% |

On this one simulated path, the Conservative profile gave a shallower max drawdown for all three strategies. The looser profiles did less: Aggressive never changed the Trend Following result, and it slightly deepened the RSI drawdown. These figures come from synthetic prices, so they describe the engine's behaviour, not any real-world edge. The full tables, including all profiles and returns split by regime, are in [docs/results.md](docs/results.md).

## Performance

`make bench` times `Backtester.run()` (CSV load, simulation, metrics) and writes [docs/benchmark.md](docs/benchmark.md) with the machine details. The median of 5 runs on an Apple M1 Pro (8 cores, 16 GiB, macOS 26.4, Python 3.11.15):

| Case | Bars (days) | Rows (bars x symbols) | Median |
| --- | ---: | ---: | ---: |
| 5 symbols, 1 year | 262 | 1,310 | 0.49 s |
| 5 symbols, 5 years | 1,305 | 6,525 | 3.46 s |
| 25 symbols, 5 years (full sample file) | 1,305 | 32,625 | 26.72 s |

The machine was busy with other work during this run; its load average is recorded in the benchmark file. Time per bar grows with the amount of data because the engine recomputes indicators over the full history on every bar (see Limitations).

## What's in it

- **Strategies** (`backtest_engine/strategies/`), each a `StrategyBase` subclass implementing `generate_signals(data, portfolio) -> List[Order]`:
  - Moving Average Crossover: 20/50-day; long on a cross up, flat on a cross down.
  - RSI Mean Reversion: 14-day RSI computed from simple averages; buy below 30, sell above 70.
  - Trend Following: buy when the close breaks the previous 20-day high; exit below the previous 20-day low or below a chandelier stop (20-day high minus 2 × ATR(14)).
- **Risk layer** (`backtest_engine/risk.py`): max position size and max exposure (oversized orders are cut down, not rejected), stop-loss, take-profit, and a max-drawdown halt that blocks new entries. There are four profiles in `config/risk_configs.json`, one of them with the risk layer off.
- **Metrics** (`backtest_engine/metrics.py`):
  - returns and risk: total return, CAGR, max drawdown, annualised volatility, Sharpe (2% risk-free)
  - trades: win rate, average win and loss, profit factor, trade count, win and loss streaks
  - returns split by regime
- **API and dashboard** (`app/`, `templates/index.html`): run a backtest, list and compare runs, and run a regime analysis. The dashboard plots the stored equity curve and drawdown and lists the trades. See [docs/api.md](docs/api.md).
- **Storage**: SQLAlchemy models (`app/models/database.py`), with SQLite locally and PostgreSQL in Docker (`db/init.sql`).
- **Paper trading** (`live_trading/`): an alpaca-py adapter and a `LiveTrader` that runs any of the strategies, optionally with the risk layer. Paper trading is the default; live trading needs both `paper=False` and `QUANT_ALLOW_LIVE_TRADING=yes`. See [docs/live-trading.md](docs/live-trading.md).

## Tests and CI

There are 86 pytest tests (`pytest --collect-only -q`). They cover:

- the data generator: cross-process determinism under different `PYTHONHASHSEED` values, and that the committed CSV matches the generator
- the Markov chain: empirical transition frequencies and mean regime durations against the matrix
- strategy signals, metrics, portfolio accounting and risk rules
- the Flask API, on temporary SQLite
- the paper-trading adapter, with fake clients
- that the results report is reproducible

Without `requirements-live.txt` installed (`make install-live`), the three tests that build real alpaca-py objects are skipped. GitHub Actions installs it, runs the suite on Python 3.10 and 3.11, and checks that `docs/results.md` is current. mypy runs on the engine as an advisory step and does not fail the build.

## Limitations

- **Synthetic data only.** Symbols are independent given the shared regime, there are no fat tails within a regime, and the calendar is business days (holidays included). The results describe one simulated path (seed 42).
- **Optimistic fills.** Orders fill at the close of the bar that produced the signal, which assumes you can trade at a price only known at the close. There are no commissions, slippage, partial fills or shorting.
- **Idle cash earns nothing**, while Sharpe subtracts a 2% risk-free rate.
- **No cooldown after a stop-loss.** A strategy can re-enter on the same bar it was stopped out.
- **Runtime grows with history.** Every bar re-filters the data and recomputes indicators over the full history (see the benchmark). A backtest runs inside the HTTP request, and gunicorn's timeout is 300 s.
- **Paper trading is only tested against fake clients.** It has not been run against a funded account.
- **Risk profiles are hand-picked**, not fitted. mypy is advisory, not enforced.

## Docs

- [docs/data.md](docs/data.md): the synthetic data model, its parameters and how it is tested
- [docs/results.md](docs/results.md): benchmark backtests (generated)
- [docs/benchmark.md](docs/benchmark.md): timings (generated)
- [docs/api.md](docs/api.md): REST API
- [docs/live-trading.md](docs/live-trading.md): Alpaca paper trading

## Deploying

`Dockerfile`, `render.yaml`, `Procfile` and `runtime.txt` are included. The app runs under gunicorn and reads `DATABASE_URL` and `SECRET_KEY` from the environment (see `.env.example`). It is not deployed anywhere at the moment.

## License

MIT
