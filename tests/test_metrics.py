"""
Unit tests for performance metrics
"""
import pytest
from datetime import datetime, timedelta
import pandas as pd
from backtest_engine.metrics import PerformanceMetrics


def test_total_return_calculation():
    """Test total return calculation"""
    equity_curve = [
        {'timestamp': datetime.now(), 'equity': 100000, 'cash': 100000, 'positions_value': 0},
        {'timestamp': datetime.now(), 'equity': 110000, 'cash': 50000, 'positions_value': 60000}
    ]

    metrics = PerformanceMetrics(equity_curve, [], 100000)
    total_return = metrics.total_return()

    assert total_return == 10.0  # 10% return


def test_max_drawdown_calculation():
    """Test max drawdown calculation"""
    base_date = datetime.now()

    equity_curve = [
        {'timestamp': base_date, 'equity': 100000, 'cash': 100000, 'positions_value': 0},
        {'timestamp': base_date + timedelta(days=1), 'equity': 110000, 'cash': 110000, 'positions_value': 0},
        {'timestamp': base_date + timedelta(days=2), 'equity': 95000, 'cash': 95000, 'positions_value': 0},
        {'timestamp': base_date + timedelta(days=3), 'equity': 105000, 'cash': 105000, 'positions_value': 0}
    ]

    metrics = PerformanceMetrics(equity_curve, [], 100000)
    max_dd = metrics.max_drawdown()

    # Max drawdown from peak of 110000 to 95000 = 13.64%
    assert abs(max_dd - 13.64) < 0.1


def test_win_rate_calculation():
    """Test win rate calculation"""
    trades = [
        {'status': 'closed', 'pnl': 500},
        {'status': 'closed', 'pnl': -200},
        {'status': 'closed', 'pnl': 300},
        {'status': 'closed', 'pnl': -100},
        {'status': 'open', 'pnl': None}
    ]

    metrics = PerformanceMetrics([], trades, 100000)
    win_rate = metrics.win_rate()

    # 2 wins out of 4 closed trades = 50%
    assert win_rate == 50.0


def test_avg_win_loss():
    """Test average win and loss calculations"""
    trades = [
        {'status': 'closed', 'pnl': 500},
        {'status': 'closed', 'pnl': 300},
        {'status': 'closed', 'pnl': -200},
        {'status': 'closed', 'pnl': -100}
    ]

    metrics = PerformanceMetrics([], trades, 100000)

    avg_win = metrics.avg_win()
    avg_loss = metrics.avg_loss()

    assert avg_win == 400.0  # (500 + 300) / 2
    assert avg_loss == -150.0  # (-200 + -100) / 2


def test_profit_factor():
    """Test profit factor calculation"""
    trades = [
        {'status': 'closed', 'pnl': 1000},
        {'status': 'closed', 'pnl': 500},
        {'status': 'closed', 'pnl': -300},
        {'status': 'closed', 'pnl': -200}
    ]

    metrics = PerformanceMetrics([], trades, 100000)
    profit_factor = metrics.profit_factor()

    # Gross profit = 1500, Gross loss = 500
    # Profit factor = 1500 / 500 = 3.0
    assert profit_factor == 3.0


def test_num_trades():
    """Test number of trades count"""
    trades = [
        {'status': 'closed', 'pnl': 100},
        {'status': 'closed', 'pnl': -50},
        {'status': 'open', 'pnl': None}
    ]

    metrics = PerformanceMetrics([], trades, 100000)
    num_trades = metrics.num_trades()

    assert num_trades == 2  # Only closed trades


def test_sharpe_ratio():
    """Test Sharpe ratio calculation"""
    # Create equity curve with positive returns
    base_date = datetime.now()
    equity_values = [100000 + i * 100 for i in range(100)]  # Steady growth

    equity_curve = [
        {
            'timestamp': base_date + timedelta(days=i),
            'equity': equity_values[i],
            'cash': equity_values[i],
            'positions_value': 0
        }
        for i in range(100)
    ]

    metrics = PerformanceMetrics(equity_curve, [], 100000)
    sharpe = metrics.sharpe_ratio()

    # Should be positive for positive returns
    assert sharpe > 0


def test_empty_data():
    """Test metrics with empty data"""
    metrics = PerformanceMetrics([], [], 100000)

    assert metrics.total_return() == 0.0
    assert metrics.max_drawdown() == 0.0
    assert metrics.num_trades() == 0
