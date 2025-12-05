"""
Moving Average Crossover Strategy
Generates buy signals when fast MA crosses above slow MA
Generates sell signals when fast MA crosses below slow MA
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from ..strategy_base import StrategyBase
from ..portfolio import Portfolio, Order


class MovingAverageCrossover(StrategyBase):
    """Moving Average Crossover Strategy"""

    def __init__(self, parameters: Dict[str, Any] = None):
        default_params = {
            'fast_period': 20,
            'slow_period': 50
        }
        params = {**default_params, **(parameters or {})}
        super().__init__('Moving Average Crossover', params)

        self.fast_period = params['fast_period']
        self.slow_period = params['slow_period']

        # Track historical data for MA calculation
        self.data_buffer = {}

    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """Generate signals based on MA crossover"""
        orders = []

        # Group by symbol
        for symbol in data['symbol'].unique():
            symbol_data = data[data['symbol'] == symbol].copy()

            if len(symbol_data) < self.slow_period:
                continue

            # Calculate moving averages
            symbol_data['fast_ma'] = symbol_data['close'].rolling(window=self.fast_period).mean()
            symbol_data['slow_ma'] = symbol_data['close'].rolling(window=self.slow_period).mean()

            # Get latest values
            latest = symbol_data.iloc[-1]
            prev = symbol_data.iloc[-2] if len(symbol_data) > 1 else None

            if prev is None or pd.isna(latest['fast_ma']) or pd.isna(latest['slow_ma']):
                continue

            current_price = latest['close']
            has_position = symbol in portfolio.positions

            # Buy signal: fast MA crosses above slow MA
            if (latest['fast_ma'] > latest['slow_ma'] and
                prev['fast_ma'] <= prev['slow_ma'] and
                not has_position):

                quantity = self.calculate_position_size(symbol, current_price, portfolio)
                if quantity > 0:
                    orders.append(Order(
                        symbol=symbol,
                        quantity=quantity,
                        side='buy',
                        timestamp=latest['timestamp']
                    ))

            # Sell signal: fast MA crosses below slow MA
            elif (latest['fast_ma'] < latest['slow_ma'] and
                  prev['fast_ma'] >= prev['slow_ma'] and
                  has_position):

                position = portfolio.positions[symbol]
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
