"""
Risk management engine
Applies risk rules to limit losses and manage exposure
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from .portfolio import Portfolio, Order, Position


@dataclass
class RiskConfig:
    """Risk management configuration"""
    name: str
    max_position_size: Optional[float] = None  # Max position as % of equity (0-1)
    max_portfolio_exposure: Optional[float] = None  # Max total exposure as % (0-1)
    stop_loss_pct: Optional[float] = None  # Stop loss percentage (0-1)
    take_profit_pct: Optional[float] = None  # Take profit percentage (0-1)
    max_drawdown_pct: Optional[float] = None  # Max drawdown before stopping (0-1)
    enabled: bool = True


class RiskManager:
    """Manages risk rules and validates orders"""

    def __init__(self, config: RiskConfig):
        self.config = config
        self.peak_equity = 0.0
        self.trading_halted = False

    def validate_order(self, order: Order, price: float, portfolio: Portfolio) -> bool:
        """
        Validate if an order should be executed based on risk rules

        Returns True if order passes all risk checks
        """
        if not self.config.enabled:
            return True

        if self.trading_halted:
            return False

        if order.side == 'buy':
            return self._validate_buy_order(order, price, portfolio)
        elif order.side == 'sell':
            return self._validate_sell_order(order, price, portfolio)

        return True

    def _validate_buy_order(self, order: Order, price: float, portfolio: Portfolio) -> bool:
        """Validate buy order against risk rules"""

        # Check max position size
        if self.config.max_position_size is not None:
            order_value = order.quantity * price
            max_position_value = portfolio.equity * self.config.max_position_size

            if order_value > max_position_value:
                # Adjust order size to fit within limits
                order.quantity = max_position_value / price

                if order.quantity <= 0:
                    return False

        # Check max portfolio exposure
        if self.config.max_portfolio_exposure is not None:
            order_value = order.quantity * price
            new_positions_value = portfolio.positions_value + order_value
            new_exposure = new_positions_value / portfolio.equity if portfolio.equity > 0 else 0

            if new_exposure > self.config.max_portfolio_exposure:
                # Calculate maximum allowed order value
                max_exposure_value = portfolio.equity * self.config.max_portfolio_exposure
                max_order_value = max_exposure_value - portfolio.positions_value

                if max_order_value <= 0:
                    return False

                order.quantity = max_order_value / price

        # Check if we have enough cash
        order_value = order.quantity * price
        if order_value > portfolio.cash:
            return False

        return True

    def _validate_sell_order(self, order: Order, price: float, portfolio: Portfolio) -> bool:
        """Validate sell order - typically always allowed"""
        # Check if we have the position
        if order.symbol not in portfolio.positions:
            return False

        position = portfolio.positions[order.symbol]
        if order.quantity > position.quantity:
            return False

        return True

    def check_stop_loss_take_profit(
        self,
        portfolio: Portfolio,
        current_prices: Dict[str, float]
    ) -> List[Order]:
        """
        Check all positions for stop loss or take profit triggers

        Returns list of orders to execute
        """
        if not self.config.enabled:
            return []

        orders = []

        for symbol, position in portfolio.positions.items():
            if symbol not in current_prices:
                continue

            current_price = current_prices[symbol]

            # Calculate P&L percentage
            pnl_pct = ((current_price - position.entry_price) / position.entry_price) if position.entry_price > 0 else 0

            # Check stop loss
            if self.config.stop_loss_pct is not None:
                if pnl_pct <= -self.config.stop_loss_pct:
                    # Trigger stop loss
                    orders.append(Order(
                        symbol=symbol,
                        quantity=position.quantity,
                        side='sell'
                    ))
                    continue

            # Check take profit
            if self.config.take_profit_pct is not None:
                if pnl_pct >= self.config.take_profit_pct:
                    # Trigger take profit
                    orders.append(Order(
                        symbol=symbol,
                        quantity=position.quantity,
                        side='sell'
                    ))

        return orders

    def check_drawdown(self, portfolio: Portfolio):
        """
        Check if portfolio drawdown exceeds maximum allowed

        If exceeded, halt trading
        """
        if not self.config.enabled or self.config.max_drawdown_pct is None:
            return

        # Update peak equity
        if portfolio.equity > self.peak_equity:
            self.peak_equity = portfolio.equity

        # Calculate current drawdown
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - portfolio.equity) / self.peak_equity

            if drawdown >= self.config.max_drawdown_pct:
                self.trading_halted = True

    def apply_risk_adjustments(
        self,
        orders: List[Order],
        portfolio: Portfolio,
        current_prices: Dict[str, float]
    ) -> List[Order]:
        """
        Apply risk rules to a list of orders

        Returns filtered and adjusted orders
        """
        if not self.config.enabled:
            return orders

        validated_orders = []

        for order in orders:
            price = current_prices.get(order.symbol)
            if price is None:
                continue

            if self.validate_order(order, price, portfolio):
                validated_orders.append(order)

        return validated_orders

    def reset(self):
        """Reset risk manager state"""
        self.peak_equity = 0.0
        self.trading_halted = False

    def get_stats(self) -> Dict:
        """Get risk manager statistics"""
        return {
            'peak_equity': self.peak_equity,
            'trading_halted': self.trading_halted,
            'config': {
                'max_position_size': self.config.max_position_size,
                'max_portfolio_exposure': self.config.max_portfolio_exposure,
                'stop_loss_pct': self.config.stop_loss_pct,
                'take_profit_pct': self.config.take_profit_pct,
                'max_drawdown_pct': self.config.max_drawdown_pct
            }
        }
