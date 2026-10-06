"""
RSI Mean Reversion Strategy
Buys when RSI is oversold
Sells when RSI is overbought
"""
import pandas as pd
from typing import Any, Dict, Optional
from ..strategy_base import BARS_SEEN, StrategyBase
from ..portfolio import Portfolio, Order


class RSIMeanReversion(StrategyBase):
    """RSI-based mean reversion strategy"""

    PARAMETER_LIMITS = {
        'rsi_period': (int, 2, 100),
        'oversold': (float, 1, 99),
        'overbought': (float, 1, 99),
    }

    @classmethod
    def check_parameters(cls, parameters):
        if parameters['oversold'] >= parameters['overbought']:
            raise ValueError('oversold must be less than overbought')

    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
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

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """RSI from simple averages of gains and losses"""
        return pd.DataFrame({'rsi': self.calculate_rsi(bars['close'], self.rsi_period)}, index=bars.index)

    def signal(self, symbol: str, bar: Dict[str, Any], portfolio: Portfolio) -> Optional[Order]:
        """Buy below the oversold level while flat, sell above the overbought level"""
        # One more bar than the period: the first price change needs two closes
        if bar[BARS_SEEN] < self.rsi_period + 1:
            return None
        if pd.isna(bar['rsi']):
            return None

        current_price = bar['close']
        has_position = symbol in portfolio.positions

        # Buy signal: RSI oversold
        if bar['rsi'] < self.oversold and not has_position:
            quantity = self.calculate_position_size(symbol, current_price, portfolio)
            if quantity > 0:
                return Order(
                    symbol=symbol,
                    quantity=quantity,
                    side='buy',
                    timestamp=bar['timestamp']
                )

        # Sell signal: RSI overbought
        elif bar['rsi'] > self.overbought and has_position:
            position = portfolio.positions[symbol]
            return Order(
                symbol=symbol,
                quantity=position.quantity,
                side='sell',
                timestamp=bar['timestamp']
            )

        return None
