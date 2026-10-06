"""
Base class for trading strategies
All strategies must inherit from StrategyBase
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
import pandas as pd
from .portfolio import Portfolio, Order


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

    def __init__(self, name: str, parameters: Dict[str, Any] = None):
        self.name = name
        self.parameters = parameters or {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """
        Generate trading signals based on current market data and portfolio state

        Args:
            data: OHLCV bars for every symbol, up to and including the current bar
            portfolio: Current portfolio state

        Returns:
            List of Order objects to execute
        """
        pass

    @abstractmethod
    def on_bar(self, bar: pd.Series, portfolio: Portfolio) -> List[Order]:
        """
        Called on each new bar of data

        Args:
            bar: Current bar data (single row from DataFrame)
            portfolio: Current portfolio state

        Returns:
            List of Order objects to execute
        """
        pass

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
