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


def test_returns_by_regime_attributes_each_day_to_its_regime():
    from backtest_engine.metrics import returns_by_regime

    dates = [datetime(2024, 1, d) for d in (1, 2, 3, 4)]
    equity_curve = [{'timestamp': d, 'equity': e} for d, e in zip(dates, [100.0, 110.0, 99.0, 99.0])]
    regimes = {dates[0]: 'bull', dates[1]: 'bull', dates[2]: 'bear', dates[3]: 'bear'}

    result = returns_by_regime(equity_curve, regimes, regime_order=['bull', 'bear', 'sideways'])

    assert list(result) == ['bull', 'bear']  # no days in sideways, so no entry
    assert result['bull']['days'] == 1
    assert result['bull']['compounded_return_pct'] == pytest.approx(10.0)
    assert result['bear']['days'] == 2
    assert result['bear']['compounded_return_pct'] == pytest.approx(-10.0)


def test_decimal_equity_gives_the_same_metrics_as_float():
    # A stored run's equity comes back from NUMERIC columns as Decimal
    from decimal import Decimal
    values = ['100000.0000', '101250.5000', '99800.2500', '102400.7500', '101900.0000']
    dates = pd.bdate_range('2023-01-02', periods=len(values))
    as_float = [{'timestamp': d, 'equity': float(v)} for d, v in zip(dates, values)]
    as_decimal = [{'timestamp': d, 'equity': Decimal(v)} for d, v in zip(dates, values)]
    trades = [{'status': 'closed', 'pnl': Decimal('12.5')}, {'status': 'closed', 'pnl': Decimal('-3')}]

    expected = PerformanceMetrics(as_float, [{**t, 'pnl': float(t['pnl'])} for t in trades], 100000).calculate_all()
    assert PerformanceMetrics(as_decimal, trades, 100000).calculate_all() == pytest.approx(expected)


def test_returns_by_regime_matches_utc_timestamps_to_naive_dates():
    # Stored runs have ISO timestamps with +00:00; the data file's dates are naive
    from backtest_engine.metrics import returns_by_regime
    curve = [{'timestamp': f'2023-01-0{d}T00:00:00+00:00', 'equity': e}
             for d, e in [(2, 100.0), (3, 110.0), (4, 99.0)]]
    labels = {pd.Timestamp('2023-01-03'): 'bull', pd.Timestamp('2023-01-04'): 'bear'}
    result = returns_by_regime(curve, labels)
    assert result['bull']['compounded_return_pct'] == pytest.approx(10.0)
    assert result['bear']['compounded_return_pct'] == pytest.approx(-10.0)
