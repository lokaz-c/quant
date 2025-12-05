"""
RSI Mean Reversion Strategy
Buys when RSI is oversold
Sells when RSI is overbought
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from ..strategy_base import StrategyBase
from ..portfolio import Portfolio, Order


class RSIMeanReversion(StrategyBase):
    """RSI-based mean reversion strategy"""

    def __init__(self, parameters: Dict[str, Any] = None):
        default_params = {
            'rsi_period': 14,
            'oversold': 30,
            'overbought': 70
        }
        params = {**default_params, **(parameters or {})}
        super().__init__('RSI Mean Reversion', params)

        self.rsi_period = params['rsi_period']
        self.oversold = params['oversold']
        self.overbought = params['overbought']

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = prices.diff()

        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """Generate signals based on RSI levels"""
        orders = []

        # Group by symbol
        for symbol in data['symbol'].unique():
            symbol_data = data[data['symbol'] == symbol].copy()

            if len(symbol_data) < self.rsi_period + 1:
                continue

            # Calculate RSI
            symbol_data['rsi'] = self.calculate_rsi(symbol_data['close'], self.rsi_period)

            # Get latest values
            latest = symbol_data.iloc[-1]

            if pd.isna(latest['rsi']):
                continue

            current_price = latest['close']
            has_position = symbol in portfolio.positions

            # Buy signal: RSI oversold
            if latest['rsi'] < self.oversold and not has_position:
                quantity = self.calculate_position_size(symbol, current_price, portfolio)
                if quantity > 0:
                    orders.append(Order(
                        symbol=symbol,
                        quantity=quantity,
                        side='buy',
                        timestamp=latest['timestamp']
                    ))

            # Sell signal: RSI overbought
            elif latest['rsi'] > self.overbought and has_position:
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
