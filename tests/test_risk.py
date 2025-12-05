"""
Unit tests for risk management
"""
import pytest
from datetime import datetime
from backtest_engine.portfolio import Portfolio, Order
from backtest_engine.risk import RiskConfig, RiskManager


def test_risk_config_creation():
    """Test creating risk configuration"""
    config = RiskConfig(
        name='Test Config',
        max_position_size=0.2,
        max_portfolio_exposure=0.8,
        stop_loss_pct=0.05,
        take_profit_pct=0.15
    )

    assert config.name == 'Test Config'
    assert config.max_position_size == 0.2
    assert config.enabled is True


def test_max_position_size_enforcement():
    """Test that max position size is enforced"""
    config = RiskConfig(
        name='Conservative',
        max_position_size=0.1,  # 10% max
        enabled=True
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Try to buy 50% of portfolio in one position
    order = Order(symbol='AAPL', quantity=500, side='buy')
    price = 100.0

    # Should be adjusted down
    is_valid = risk_manager.validate_order(order, price, portfolio)

    assert is_valid is True
    # Order quantity should be adjusted to fit within 10% limit
    assert order.quantity * price <= portfolio.equity * 0.1


def test_max_portfolio_exposure():
    """Test max portfolio exposure limit"""
    config = RiskConfig(
        name='Conservative',
        max_portfolio_exposure=0.7,  # 70% max
        enabled=True
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Buy up to 60% exposure
    order1 = Order(symbol='AAPL', quantity=400, side='buy')
    portfolio.execute_order(order1, price=150.0, timestamp=datetime.now())
    portfolio.update_prices({'AAPL': 150.0})

    # Try to buy another 30% (would exceed 70% limit)
    order2 = Order(symbol='GOOGL', quantity=200, side='buy')
    is_valid = risk_manager.validate_order(order2, price=150.0, portfolio)

    # Should still be valid but adjusted
    assert is_valid is True
    # Total exposure should not exceed 70%
    total_value = order2.quantity * 150.0 + portfolio.positions_value
    assert total_value <= portfolio.equity * 0.7


def test_stop_loss_trigger():
    """Test stop loss triggers correctly"""
    config = RiskConfig(
        name='Test',
        stop_loss_pct=0.05,  # 5% stop loss
        enabled=True
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Buy position
    order = Order(symbol='AAPL', quantity=100, side='buy')
    portfolio.execute_order(order, price=100.0, timestamp=datetime.now())

    # Price drops 6% (below stop loss)
    current_prices = {'AAPL': 94.0}
    portfolio.update_prices(current_prices)

    stop_orders = risk_manager.check_stop_loss_take_profit(portfolio, current_prices)

    assert len(stop_orders) > 0
    assert stop_orders[0].side == 'sell'
    assert stop_orders[0].symbol == 'AAPL'


def test_take_profit_trigger():
    """Test take profit triggers correctly"""
    config = RiskConfig(
        name='Test',
        take_profit_pct=0.10,  # 10% take profit
        enabled=True
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Buy position
    order = Order(symbol='AAPL', quantity=100, side='buy')
    portfolio.execute_order(order, price=100.0, timestamp=datetime.now())

    # Price rises 11% (above take profit)
    current_prices = {'AAPL': 111.0}
    portfolio.update_prices(current_prices)

    profit_orders = risk_manager.check_stop_loss_take_profit(portfolio, current_prices)

    assert len(profit_orders) > 0
    assert profit_orders[0].side == 'sell'


def test_max_drawdown_halt():
    """Test that trading halts on max drawdown"""
    config = RiskConfig(
        name='Test',
        max_drawdown_pct=0.15,  # 15% max drawdown
        enabled=True
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Set peak equity
    risk_manager.peak_equity = 100000

    # Simulate 20% loss
    portfolio.cash = 80000

    risk_manager.check_drawdown(portfolio)

    assert risk_manager.trading_halted is True


def test_risk_disabled():
    """Test that risk rules don't apply when disabled"""
    config = RiskConfig(
        name='No Risk',
        max_position_size=0.1,
        enabled=False  # Disabled
    )

    risk_manager = RiskManager(config)
    portfolio = Portfolio(initial_capital=100000)

    # Try to buy 80% of portfolio (would violate if enabled)
    order = Order(symbol='AAPL', quantity=800, side='buy')
    is_valid = risk_manager.validate_order(order, price=100.0, portfolio)

    # Should pass since risk is disabled
    assert is_valid is True
    # Order should not be modified
    assert order.quantity == 800
