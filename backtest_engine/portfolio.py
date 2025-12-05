"""
Portfolio and position management
Tracks holdings, cash, equity, and executes trades
"""
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class Position:
    """Represents a position in a security"""
    symbol: str
    quantity: float
    entry_price: float
    entry_date: datetime
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        """Current market value of position"""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        """Original cost of position"""
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized profit/loss"""
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        """Unrealized profit/loss percentage"""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100


@dataclass
class Order:
    """Represents a trade order"""
    symbol: str
    quantity: float
    side: str  # 'buy' or 'sell'
    order_type: str = 'market'
    price: Optional[float] = None
    timestamp: Optional[datetime] = None


@dataclass
class ExecutedTrade:
    """Represents an executed trade"""
    symbol: str
    entry_date: datetime
    exit_date: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    side: str
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    status: str = 'open'


class Portfolio:
    """Manages portfolio state and execution"""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.equity_history: List[Dict] = []
        self.trades: List[ExecutedTrade] = []

    @property
    def positions_value(self) -> float:
        """Total market value of all positions"""
        return sum(pos.market_value for pos in self.positions.values())

    @property
    def equity(self) -> float:
        """Total portfolio equity (cash + positions)"""
        return self.cash + self.positions_value

    @property
    def total_return(self) -> float:
        """Total return percentage"""
        if self.initial_capital == 0:
            return 0.0
        return ((self.equity - self.initial_capital) / self.initial_capital) * 100

    def update_prices(self, prices: Dict[str, float]):
        """Update current prices for all positions"""
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.current_price = prices[symbol]

    def execute_order(self, order: Order, current_price: float, timestamp: datetime) -> bool:
        """
        Execute a trade order

        Returns True if executed, False otherwise
        """
        if order.side == 'buy':
            return self._execute_buy(order, current_price, timestamp)
        elif order.side == 'sell':
            return self._execute_sell(order, current_price, timestamp)
        return False

    def _execute_buy(self, order: Order, price: float, timestamp: datetime) -> bool:
        """Execute a buy order"""
        cost = order.quantity * price

        if cost > self.cash:
            # Insufficient funds
            return False

        self.cash -= cost

        # Add to position or create new
        if order.symbol in self.positions:
            pos = self.positions[order.symbol]
            # Update average entry price
            total_quantity = pos.quantity + order.quantity
            total_cost = pos.cost_basis + cost
            pos.entry_price = total_cost / total_quantity
            pos.quantity = total_quantity
            pos.current_price = price
        else:
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                quantity=order.quantity,
                entry_price=price,
                entry_date=timestamp,
                current_price=price
            )

        # Record trade
        trade = ExecutedTrade(
            symbol=order.symbol,
            entry_date=timestamp,
            exit_date=None,
            entry_price=price,
            exit_price=None,
            quantity=order.quantity,
            side='buy',
            status='open'
        )
        self.trades.append(trade)

        return True

    def _execute_sell(self, order: Order, price: float, timestamp: datetime) -> bool:
        """Execute a sell order"""
        if order.symbol not in self.positions:
            return False

        pos = self.positions[order.symbol]

        if order.quantity > pos.quantity:
            # Trying to sell more than owned
            return False

        # Calculate proceeds
        proceeds = order.quantity * price
        self.cash += proceeds

        # Calculate P&L
        cost_basis = order.quantity * pos.entry_price
        pnl = proceeds - cost_basis
        pnl_pct = (pnl / cost_basis) * 100 if cost_basis > 0 else 0

        # Update or close position
        if order.quantity == pos.quantity:
            # Close entire position
            entry_date = pos.entry_date
            entry_price = pos.entry_price
            del self.positions[order.symbol]
        else:
            # Partial close
            entry_date = pos.entry_date
            entry_price = pos.entry_price
            pos.quantity -= order.quantity

        # Record trade
        trade = ExecutedTrade(
            symbol=order.symbol,
            entry_date=entry_date,
            exit_date=timestamp,
            entry_price=entry_price,
            exit_price=price,
            quantity=order.quantity,
            side='sell',
            pnl=pnl,
            pnl_pct=pnl_pct,
            status='closed'
        )
        self.trades.append(trade)

        return True

    def record_equity(self, timestamp: datetime):
        """Record current equity snapshot"""
        self.equity_history.append({
            'timestamp': timestamp,
            'equity': self.equity,
            'cash': self.cash,
            'positions_value': self.positions_value
        })

    def get_position_size_pct(self, symbol: str) -> float:
        """Get position size as percentage of equity"""
        if symbol not in self.positions or self.equity == 0:
            return 0.0
        return (self.positions[symbol].market_value / self.equity) * 100

    def get_total_exposure_pct(self) -> float:
        """Get total portfolio exposure as percentage"""
        if self.equity == 0:
            return 0.0
        return (self.positions_value / self.equity) * 100

    def close_all_positions(self, prices: Dict[str, float], timestamp: datetime):
        """Close all open positions at current prices"""
        symbols_to_close = list(self.positions.keys())

        for symbol in symbols_to_close:
            if symbol in prices:
                pos = self.positions[symbol]
                order = Order(
                    symbol=symbol,
                    quantity=pos.quantity,
                    side='sell',
                    timestamp=timestamp
                )
                self.execute_order(order, prices[symbol], timestamp)

    def get_open_trades(self) -> List[ExecutedTrade]:
        """Get all open trades"""
        return [t for t in self.trades if t.status == 'open']

    def get_closed_trades(self) -> List[ExecutedTrade]:
        """Get all closed trades"""
        return [t for t in self.trades if t.status == 'closed']
