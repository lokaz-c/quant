"""
Base class for trading strategies
All strategies must inherit from StrategyBase

A strategy has two parts:

- indicators(bars): its indicator columns for one symbol's bars, computed with
  vectorised pandas over the whole series. The value in row t may depend only
  on rows 0..t (no look-ahead).
- signal(symbol, bar, portfolio): the order for one symbol at one bar, decided
  from that bar's prices and indicator values and the portfolio, or None.

The Backtester calls prepare() once per run, which computes indicators() once
per symbol over every bar of the run, and then calls signal() for each symbol
on each bar it has. generate_signals(data, portfolio) gives the same decision
for the latest bar of a history: it recomputes the indicators over that
history. Live trading uses it, and the tests use it as the per-bar reference
for the engine.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Hashable, List, Optional, Tuple

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from .portfolio import Portfolio, Order

# Key in every bar passed to signal(): how many bars of this symbol there are
# up to and including this one. Strategies use it for their warm-up period.
BARS_SEEN = 'bars_seen'


class SymbolBars:
    """
    One symbol's bars and a strategy's indicator values, held as column
    arrays. bar(k) returns row k as a dict, with the same value types as
    DataFrame.iloc[k] (numpy scalars, Timestamps), without building a pandas
    object per bar.
    """

    def __init__(self, bars: pd.DataFrame, indicators: pd.DataFrame):
        if not indicators.index.equals(bars.index):
            raise ValueError("indicators() must return one row per bar, with the bars' index")
        columns = {name: bars[name] for name in bars.columns}
        columns.update({name: indicators[name] for name in indicators.columns})
        self.names: List[str] = [str(name) for name in columns] + [BARS_SEEN]
        self.values: List[Any] = [
            series.tolist() if is_datetime64_any_dtype(series) else series.to_numpy()
            for series in columns.values()
        ] + [np.arange(1, len(bars) + 1)]

    def __len__(self) -> int:
        return len(self.values[-1])

    def bar(self, k: int) -> Dict[str, Any]:
        """Row k: the bar's columns (timestamp, OHLCV, ...), its indicators and BARS_SEEN"""
        return {name: column[k] for name, column in zip(self.names, self.values)}


class StrategyBase(ABC):
    """Abstract base class for all trading strategies"""

    # name -> (type, min, max), inclusive. Subclasses list every parameter they
    # read; validate_parameters() checks user-supplied values against it.
    PARAMETER_LIMITS: Dict[str, Tuple[type, float, float]] = {}

    @classmethod
    def validate_parameters(cls, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check a full parameter set (defaults merged with overrides). Returns it
        with ints as int and floats as float; raises ValueError with a message
        fit for an API client.
        """
        unknown = set(parameters) - set(cls.PARAMETER_LIMITS)
        if unknown:
            raise ValueError(f"Unknown parameter(s) for {cls.__name__}: {', '.join(sorted(unknown))}")
        cleaned = {}
        for name, (kind, low, high) in cls.PARAMETER_LIMITS.items():
            if name not in parameters:
                raise ValueError(f"Missing parameter: {name}")
            value = parameters[name]
            # bool is an int subclass; reject it explicitly
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if kind is int and float(value) != int(value):
                raise ValueError(f"{name} must be a whole number")
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low:g} and {high:g}")
            cleaned[name] = kind(value)
        cls.check_parameters(cleaned)
        return cleaned

    @classmethod
    def check_parameters(cls, parameters: Dict[str, Any]) -> None:
        """Cross-parameter rules; raise ValueError. Override in subclasses."""

    @classmethod
    def parameter_limits(cls) -> Dict[str, Dict[str, Any]]:
        """PARAMETER_LIMITS in a JSON-friendly form, for the API"""
        return {name: {'type': kind.__name__, 'min': low, 'max': high}
                for name, (kind, low, high) in cls.PARAMETER_LIMITS.items()}

    def __init__(self, name: str, parameters: Optional[Dict[str, Any]] = None):
        self.name = name
        self.parameters = parameters or {}

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """
        Indicator columns for one symbol's bars

        Args:
            bars: one symbol's OHLCV bars, oldest first

        Returns:
            A DataFrame with the same index as `bars` and one column per
            indicator. The value in row t may use rows 0..t only: the engine
            computes this once over the whole run, so a value that looked at
            later rows would leak the future into earlier decisions.

        Default: no indicators. Override in subclasses.
        """
        return pd.DataFrame(index=bars.index)

    @abstractmethod
    def signal(self, symbol: str, bar: Dict[str, Any], portfolio: Portfolio) -> Optional[Order]:
        """
        Decide what to do with one symbol at one bar

        Args:
            symbol: the symbol
            bar: that bar's columns (timestamp, open, high, low, close, volume,
                and any others in the data), its values from indicators(), and
                BARS_SEEN
            portfolio: current portfolio state, before this bar's orders

        Returns:
            An Order to execute at this bar's close, or None
        """

    def prepare(self, data: pd.DataFrame) -> Dict[Hashable, SymbolBars]:
        """
        Every symbol's bars with this strategy's indicators, computed once per
        symbol over all of `data` (bars of every symbol, each symbol's rows in
        time order). The Backtester calls this before its bar loop.
        """
        prepared: Dict[Hashable, SymbolBars] = {}
        for symbol, positions in data.groupby('symbol', sort=False).indices.items():
            bars = data.iloc[positions]
            prepared[symbol] = SymbolBars(bars, self.indicators(bars))
        return prepared

    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """
        Orders for the latest bar of each symbol in `data`

        Args:
            data: OHLCV bars for every symbol, up to and including the current bar
            portfolio: Current portfolio state

        Recomputes the indicators over the whole history on every call. The
        Backtester precomputes them once per run instead (prepare()), which
        gives the same orders.
        """
        orders = []
        for symbol in data['symbol'].unique():
            bars = data[data['symbol'] == symbol]
            if bars.empty:
                continue
            latest = SymbolBars(bars, self.indicators(bars)).bar(len(bars) - 1)
            order = self.signal(symbol, latest, portfolio)
            if order is not None:
                orders.append(order)
        return orders

    def calculate_position_size(self, symbol: str, price: float, portfolio: Portfolio) -> float:
        """
        Calculate position size based on strategy rules

        Default implementation: equal weight across positions
        Override in subclass for custom sizing
        """
        # Simple equal weight: use 20% of equity per position
        max_position_value = portfolio.equity * 0.20
        quantity = max_position_value / price
        return quantity

    def should_exit(self, position, current_price: float) -> bool:
        """
        Determine if a position should be exited

        Override in subclass for custom exit logic
        """
        return False

    def get_description(self) -> str:
        """Return strategy description"""
        return f"{self.name} - Parameters: {self.parameters}"
