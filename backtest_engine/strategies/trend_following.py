"""
Trend Following / Breakout Strategy
Enters long when price breaks above recent high
Exits when price breaks below recent low or trailing stop
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from ..strategy_base import StrategyBase
from ..portfolio import Portfolio, Order


class TrendFollowing(StrategyBase):
    """Breakout-based trend following strategy"""

    def __init__(self, parameters: Dict[str, Any] = None):
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

    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """Generate signals based on breakouts"""
        orders = []

        # Group by symbol
        for symbol in data['symbol'].unique():
            symbol_data = data[data['symbol'] == symbol].copy()

            if len(symbol_data) < self.lookback_period + 1:
                continue

            # Calculate indicators
            symbol_data['highest'] = symbol_data['high'].rolling(window=self.lookback_period).max()
            symbol_data['lowest'] = symbol_data['low'].rolling(window=self.lookback_period).min()
            symbol_data['atr'] = self.calculate_atr(symbol_data, self.atr_period)

            # Get latest values
            latest = symbol_data.iloc[-1]

            if pd.isna(latest['highest']) or pd.isna(latest['atr']):
                continue

            current_price = latest['close']
            has_position = symbol in portfolio.positions

            # Buy signal: price breaks above recent high
            if current_price > latest['highest'] and not has_position:
                quantity = self.calculate_position_size(symbol, current_price, portfolio)
                if quantity > 0:
                    orders.append(Order(
                        symbol=symbol,
                        quantity=quantity,
                        side='buy',
                        timestamp=latest['timestamp']
                    ))

            # Sell signal: price breaks below recent low or trailing stop
            elif has_position:
                position = portfolio.positions[symbol]

                # Trailing stop based on ATR
                stop_price = current_price - (latest['atr'] * self.atr_multiplier)

                if current_price < latest['lowest'] or current_price < stop_price:
                    orders.append(Order(
                        symbol=symbol,
                        quantity=position.quantity,
                        side='sell',
                        timestamp=latest['timestamp']
                    ))

        return orders

    def on_bar(self, bar: pd.Series, portfolio: Portfolio) -> List[Order]:
        """Process single bar - not used in batch mode"""
        return []
