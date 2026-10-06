"""
Trend Following / Breakout Strategy
Enters long when price breaks above recent high
Exits when price breaks below recent low or trailing stop
"""
import pandas as pd
from typing import Any, Dict, Optional
from ..strategy_base import BARS_SEEN, StrategyBase
from ..portfolio import Portfolio, Order


class TrendFollowing(StrategyBase):
    """Breakout-based trend following strategy"""

    PARAMETER_LIMITS = {
        'lookback_period': (int, 2, 250),
        'atr_period': (int, 2, 100),
        'atr_multiplier': (float, 0.5, 10),
    }

    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        default_params = {
            'lookback_period': 20,
            'atr_period': 14,
            'atr_multiplier': 2.0
        }
        params = {**default_params, **(parameters or {})}
        super().__init__('Trend Following', params)

        self.lookback_period = params['lookback_period']
        self.atr_period = params['atr_period']
        self.atr_multiplier = params.get('atr_multiplier', 2.0)

    def calculate_atr(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR)"""
        high = data['high']
        low = data['low']
        close = data['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """The channel over the previous N bars, and ATR"""
        # The current bar must be excluded from the channel: its high is >= its
        # close and its low <= its close, so comparing the close with a window
        # that includes it can never signal. shift(1) keeps row t on rows < t.
        return pd.DataFrame({
            'highest': bars['high'].rolling(window=self.lookback_period).max().shift(1),
            'lowest': bars['low'].rolling(window=self.lookback_period).min().shift(1),
            'atr': self.calculate_atr(bars, self.atr_period),
        }, index=bars.index)

    def signal(self, symbol: str, bar: Dict[str, Any], portfolio: Portfolio) -> Optional[Order]:
        """Buy a breakout above the channel while flat; exit below the channel or the stop"""
        if bar[BARS_SEEN] < self.lookback_period + 1:
            return None
        if pd.isna(bar['highest']) or pd.isna(bar['atr']):
            return None

        current_price = bar['close']
        has_position = symbol in portfolio.positions

        # Buy signal: close breaks above the previous N-bar high
        if current_price > bar['highest'] and not has_position:
            quantity = self.calculate_position_size(symbol, current_price, portfolio)
            if quantity > 0:
                return Order(
                    symbol=symbol,
                    quantity=quantity,
                    side='buy',
                    timestamp=bar['timestamp']
                )

        # Sell signal: price breaks below recent low or trailing stop
        elif has_position:
            position = portfolio.positions[symbol]

            # Chandelier-style stop: trail below the lookback high, not the current price
            stop_price = bar['highest'] - (bar['atr'] * self.atr_multiplier)

            if current_price < bar['lowest'] or current_price < stop_price:
                return Order(
                    symbol=symbol,
                    quantity=position.quantity,
                    side='sell',
                    timestamp=bar['timestamp']
                )

        return None
