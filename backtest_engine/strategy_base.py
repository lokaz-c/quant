"""
Base class for trading strategies
All strategies must inherit from StrategyBase
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd
from .portfolio import Portfolio, Order


class StrategyBase(ABC):
    """Abstract base class for all trading strategies"""

    def __init__(self, name: str, parameters: Dict[str, Any] = None):
        self.name = name
        self.parameters = parameters or {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, portfolio: Portfolio) -> List[Order]:
        """
        Generate trading signals based on current market data and portfolio state

        Args:
            data: DataFrame with current and historical market data
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
