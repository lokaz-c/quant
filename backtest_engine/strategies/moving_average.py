"""
Moving Average Crossover Strategy
Generates buy signals when fast MA crosses above slow MA
Generates sell signals when fast MA crosses below slow MA
"""
import pandas as pd
from typing import Any, Dict, Optional
from ..strategy_base import BARS_SEEN, StrategyBase
from ..portfolio import Portfolio, Order


class MovingAverageCrossover(StrategyBase):
    """Moving Average Crossover Strategy"""

    # Periods are bars; the upper bounds keep the warm-up well inside the
    # 1,305-bar sample file
    PARAMETER_LIMITS = {
        'fast_period': (int, 2, 200),
        'slow_period': (int, 3, 400),
    }

    @classmethod
    def check_parameters(cls, parameters):
        if parameters['fast_period'] >= parameters['slow_period']:
            raise ValueError('fast_period must be less than slow_period')

    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        default_params = {
            'fast_period': 20,
            'slow_period': 50
        }
        params = {**default_params, **(parameters or {})}
        super().__init__('Moving Average Crossover', params)

        self.fast_period = params['fast_period']
        self.slow_period = params['slow_period']

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Both moving averages, and their values one bar earlier (for the crossover)"""
        fast_ma = bars['close'].rolling(window=self.fast_period).mean()
        slow_ma = bars['close'].rolling(window=self.slow_period).mean()
        return pd.DataFrame({
            'fast_ma': fast_ma,
            'slow_ma': slow_ma,
            'prev_fast_ma': fast_ma.shift(1),
            'prev_slow_ma': slow_ma.shift(1),
        }, index=bars.index)

    def signal(self, symbol: str, bar: Dict[str, Any], portfolio: Portfolio) -> Optional[Order]:
        """Buy on a cross up while flat, sell the position on a cross down"""
        if bar[BARS_SEEN] < self.slow_period:
            return None
        if pd.isna(bar['fast_ma']) or pd.isna(bar['slow_ma']):
            return None

        current_price = bar['close']
        has_position = symbol in portfolio.positions

        # Buy signal: fast MA crosses above slow MA
        if (bar['fast_ma'] > bar['slow_ma'] and
            bar['prev_fast_ma'] <= bar['prev_slow_ma'] and
            not has_position):

            quantity = self.calculate_position_size(symbol, current_price, portfolio)
            if quantity > 0:
                return Order(
                    symbol=symbol,
                    quantity=quantity,
                    side='buy',
                    timestamp=bar['timestamp']
                )

        # Sell signal: fast MA crosses below slow MA
        elif (bar['fast_ma'] < bar['slow_ma'] and
              bar['prev_fast_ma'] >= bar['prev_slow_ma'] and
              has_position):

            position = portfolio.positions[symbol]
            return Order(
                symbol=symbol,
                quantity=position.quantity,
                side='sell',
                timestamp=bar['timestamp']
            )

        return None
