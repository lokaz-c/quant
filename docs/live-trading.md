# Paper trading on Alpaca

`live_trading/` runs one of the backtest strategies against an Alpaca account on daily bars. It uses **paper trading by default**. Alpaca is the only broker implemented.

## Paper-only by default

`AlpacaBroker` uses Alpaca's paper endpoint unless two things are both true:

1. the code passes `paper=False`, and
2. the environment variable `QUANT_ALLOW_LIVE_TRADING` is exactly `yes`.

If either is missing, the constructor raises `LiveTradingNotAllowed` before any API client is created. The command-line entry point always uses paper. Tests cover the guard, including near-miss values like `1`, `true` and `YES please` (`tests/test_live_trading.py`).

## Setup

1. Create an Alpaca account and open the paper trading dashboard at https://app.alpaca.markets. Paper accounts have their own API keys, separate from live keys.
2. `make install-live`, which runs `pip install -r requirements-live.txt` and adds `alpaca-py`.
3. Copy `.env.example` to `.env`, or export the variables: `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` with the paper keys. Leave `QUANT_ALLOW_LIVE_TRADING` empty.
4. Run one cycle: `python -m live_trading.live_trader --strategy ma --symbols AAPL,MSFT --once`. Leave out `--once` to repeat every `--interval` seconds (default 300) until Ctrl+C. Strategies: `ma`, `rsi`, `trend`.

## What a cycle does

1. Skips the cycle if the market is closed (Alpaca's clock).
2. Fetches about 150 calendar days of daily bars from the IEX feed, which is included in Alpaca's free data plan.
3. Builds an engine `Portfolio` from the account's cash and positions. The strategy sees the same interface as in a backtest.
4. Calls the strategy's `generate_signals`. With a `RiskConfig`, the engine's risk rules also apply: stop-loss, take-profit, drawdown halt and position and exposure caps.
5. Sends the orders:
   - Buys are whole-share day market orders, capped at `max_position_size` of equity (default 10%) and `max_positions` open positions (default 5).
   - Sells close the whole position.

## Scope and limits

- Tested only with fake clients, no network. The tests check the guard, the mapping of alpaca-py objects, that orders are valid `MarketOrderRequest`s, and the trader's routing, rounding and caps.
- It has not been run against a funded account. It has not been run against the paper endpoint from CI either, because that needs keys.
- The strategies work on daily bars, so running more than once a day mostly repeats the same decision.
- Fills, partial fills and rejections are not reconciled; the next cycle reads positions from the broker again.
- Brokers that were listed in old docs but never implemented are not supported. That includes TD Ameritrade, whose API was retired in May 2024 when its accounts moved to Schwab.
