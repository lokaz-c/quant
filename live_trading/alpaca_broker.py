"""
Alpaca adapter for paper trading, on the alpaca-py SDK (requirements-live.txt).

Paper trading is the default. Live trading needs two explicit opt-ins:
paper=False *and* the environment variable QUANT_ALLOW_LIVE_TRADING=yes.
Without both, the constructor raises LiveTradingNotAllowed before any API
client is created.

Credentials come from ALPACA_API_KEY / ALPACA_SECRET_KEY (see .env.example).
Paper and live accounts have different keys.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

import pandas as pd

LIVE_TRADING_ENV_VAR = 'QUANT_ALLOW_LIVE_TRADING'
LIVE_TRADING_CONFIRMATION = 'yes'

BAR_COLUMNS = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']


class LiveTradingNotAllowed(RuntimeError):
    """Raised when live (real-money) trading is requested without the explicit opt-in."""


def live_trading_allowed() -> bool:
    return os.getenv(LIVE_TRADING_ENV_VAR, '').strip().lower() == LIVE_TRADING_CONFIRMATION


@dataclass
class LivePosition:
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class AccountSnapshot:
    equity: float
    cash: float
    buying_power: float


class AlpacaBroker:
    """Thin wrapper over alpaca-py's TradingClient and StockHistoricalDataClient."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
        trading_client: Any = None,
        data_client: Any = None,
    ):
        # The guard runs first, so a live client is never constructed by accident
        if not paper and not live_trading_allowed():
            raise LiveTradingNotAllowed(
                f'Live trading is disabled. Pass paper=False and set '
                f'{LIVE_TRADING_ENV_VAR}={LIVE_TRADING_CONFIRMATION} to enable it.'
            )
        self.paper = paper

        if trading_client is None or data_client is None:
            api_key = api_key or os.getenv('ALPACA_API_KEY')
            secret_key = secret_key or os.getenv('ALPACA_SECRET_KEY')
            if not api_key or not secret_key:
                raise ValueError('Set ALPACA_API_KEY and ALPACA_SECRET_KEY, or pass the keys in.')
            # Imported here so the backtester does not depend on the SDK
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.trading.client import TradingClient

            if trading_client is None:
                trading_client = TradingClient(api_key, secret_key, paper=paper)
            if data_client is None:
                data_client = StockHistoricalDataClient(api_key, secret_key)

        self.trading = trading_client
        self.data = data_client

    def get_account(self) -> AccountSnapshot:
        account = self.trading.get_account()
        return AccountSnapshot(
            equity=float(account.equity),
            cash=float(account.cash),
            buying_power=float(account.buying_power),
        )

    def get_positions(self) -> List[LivePosition]:
        return [
            LivePosition(
                symbol=p.symbol,
                quantity=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
            )
            for p in self.trading.get_all_positions()
        ]

    def get_daily_bars(self, symbols: Sequence[str], lookback_days: int = 150) -> pd.DataFrame:
        """Daily bars in the backtester's column layout, oldest first."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        request = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=lookback_days),
            feed=DataFeed.IEX,  # the free plan's real-time feed
        )
        frame = self.data.get_stock_bars(request).df
        if frame.empty:
            return pd.DataFrame(columns=BAR_COLUMNS)
        frame = frame.reset_index()  # index is (symbol, timestamp)
        return frame[BAR_COLUMNS].sort_values(['timestamp', 'symbol']).reset_index(drop=True)

    def submit_market_order(self, symbol: str, qty: float, side: str) -> str:
        """Day market order; returns the order id."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        order = self.trading.submit_order(order_data=MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        ))
        return str(order.id)

    def close_position(self, symbol: str) -> None:
        self.trading.close_position(symbol)

    def is_market_open(self) -> bool:
        return bool(self.trading.get_clock().is_open)
