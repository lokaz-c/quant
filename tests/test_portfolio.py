"""
Unit tests for portfolio management
"""
import pytest
from datetime import datetime
from backtest_engine.portfolio import Portfolio, Order, Position


def test_portfolio_initialization():
    """Test portfolio initializes correctly"""
    portfolio = Portfolio(initial_capital=100000)

    assert portfolio.initial_capital == 100000
    assert portfolio.cash == 100000
    assert portfolio.equity == 100000
    assert len(portfolio.positions) == 0


def test_buy_order_execution():
    """Test executing a buy order"""
    portfolio = Portfolio(initial_capital=100000)

    order = Order(
        symbol='AAPL',
        quantity=100,
        side='buy'
    )

    timestamp = datetime.now()
    success = portfolio.execute_order(order, price=150.0, timestamp=timestamp)

    assert success is True
    assert portfolio.cash == 100000 - (100 * 150)
    assert 'AAPL' in portfolio.positions
    assert portfolio.positions['AAPL'].quantity == 100


def test_sell_order_execution():
    """Test executing a sell order"""
    portfolio = Portfolio(initial_capital=100000)

    # First buy
    buy_order = Order(symbol='AAPL', quantity=100, side='buy')
    portfolio.execute_order(buy_order, price=150.0, timestamp=datetime.now())

    # Then sell
    sell_order = Order(symbol='AAPL', quantity=50, side='sell')
    success = portfolio.execute_order(sell_order, price=160.0, timestamp=datetime.now())

    assert success is True
    assert portfolio.positions['AAPL'].quantity == 50
    assert portfolio.cash > 100000 - (100 * 150)  # Made profit


def test_insufficient_funds():
    """Test buying with insufficient funds"""
    portfolio = Portfolio(initial_capital=1000)

    order = Order(symbol='AAPL', quantity=100, side='buy')
    success = portfolio.execute_order(order, price=150.0, timestamp=datetime.now())

    assert success is False
    assert len(portfolio.positions) == 0


def test_sell_without_position():
    """Test selling without owning the position"""
    portfolio = Portfolio(initial_capital=100000)

    order = Order(symbol='AAPL', quantity=100, side='sell')
    success = portfolio.execute_order(order, price=150.0, timestamp=datetime.now())

    assert success is False


def test_position_pnl_calculation():
    """Test position P&L calculation"""
    position = Position(
        symbol='AAPL',
        quantity=100,
        entry_price=150.0,
        entry_date=datetime.now(),
        current_price=160.0
    )

    assert position.cost_basis == 15000
    assert position.market_value == 16000
    assert position.unrealized_pnl == 1000
    assert abs(position.unrealized_pnl_pct - 6.67) < 0.1


def test_equity_calculation():
    """Test total equity calculation"""
    portfolio = Portfolio(initial_capital=100000)

    # Buy some stocks
    order = Order(symbol='AAPL', quantity=100, side='buy')
    portfolio.execute_order(order, price=150.0, timestamp=datetime.now())

    # Update prices
    portfolio.update_prices({'AAPL': 160.0})

    expected_equity = portfolio.cash + (100 * 160.0)
    assert portfolio.equity == expected_equity


def test_total_return():
    """Test total return calculation"""
    portfolio = Portfolio(initial_capital=100000)

    # Simulate profit
    order = Order(symbol='AAPL', quantity=100, side='buy')
    portfolio.execute_order(order, price=150.0, timestamp=datetime.now())
    portfolio.update_prices({'AAPL': 165.0})

    # Return should be positive
    assert portfolio.total_return > 0
