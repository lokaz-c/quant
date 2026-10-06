"""
Unit tests for performance metrics
"""
import math

import numpy as np
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


def test_rolling_sharpe_uses_sample_sd_and_the_same_annualisation():
    import math
    import statistics
    equity = [100.0, 101.0, 100.5, 102.0, 101.0, 103.5]
    curve = [{'timestamp': d, 'equity': e}
             for d, e in zip(pd.bdate_range('2023-01-02', periods=len(equity)), equity)]
    returns = [b / a - 1 for a, b in zip(equity, equity[1:])]

    rolling = PerformanceMetrics(curve, [], 100.0).rolling_sharpe(window=3)

    # The first point has no return, so the first full 3-return window ends at point 3
    assert list(rolling.index) == [c['timestamp'] for c in curve[3:]]
    for i, value in enumerate(rolling):
        window = returns[i:i + 3]
        expected = (statistics.mean(window) * 252 - 0.02) / (statistics.stdev(window) * math.sqrt(252))
        assert value == pytest.approx(expected, abs=1e-12)


def test_rolling_sharpe_is_undefined_in_flat_windows():
    curve = [{'timestamp': d, 'equity': 100.0} for d in pd.bdate_range('2023-01-02', periods=6)]
    metrics = PerformanceMetrics(curve, [], 100.0)
    assert metrics.rolling_sharpe(window=3).isna().all()
    assert metrics.sharpe_ratio() is None  # undefined in full too
    assert metrics.undefined['sharpe_ratio'] == 'zero volatility'


def test_drawdown_series_is_measured_from_the_running_peak():
    curve = [{'timestamp': d, 'equity': e}
             for d, e in zip(pd.bdate_range('2023-01-02', periods=5), [100, 110, 88, 120, 114])]
    metrics = PerformanceMetrics(curve, [], 100)
    assert metrics.drawdown_series().round(9).tolist() == [0.0, 0.0, 20.0, 0.0, 5.0]
    assert metrics.max_drawdown() == pytest.approx(20.0)


def _trades(*pnls):
    return [{'symbol': 'AAPL', 'pnl': pnl, 'status': 'closed'} for pnl in pnls]


def _curve(*equities):
    return [{'timestamp': d, 'equity': e}
            for d, e in zip(pd.bdate_range('2023-01-02', periods=len(equities)), equities)]


def _undefined_after_calculate_all(metrics):
    values = metrics.calculate_all()
    assert set(metrics.undefined) == {k for k, v in values.items() if v is None}
    assert all(math.isfinite(v) for v in values.values() if isinstance(v, float))
    return values, metrics.undefined


def test_no_closed_trades_leaves_the_trade_ratios_undefined():
    values, undefined = _undefined_after_calculate_all(
        PerformanceMetrics(_curve(100.0, 101.0, 102.5), [], 100.0))
    for key in ('win_rate', 'avg_win', 'avg_loss', 'profit_factor'):
        assert values[key] is None and undefined[key] == 'no closed trades'
    assert values['num_trades'] == 0 and values['max_consecutive_wins'] == 0


def test_no_losing_trade_makes_profit_factor_undefined_not_infinite():
    values, undefined = _undefined_after_calculate_all(
        PerformanceMetrics(_curve(100.0, 101.0, 103.0), _trades(50.0, 25.0), 100.0))
    assert values['profit_factor'] is None and undefined['profit_factor'] == 'no losing trades'
    assert values['avg_loss'] is None and undefined['avg_loss'] == 'no losing trades'
    assert values['avg_win'] == 37.5 and values['win_rate'] == 100.0


def test_break_even_trades_only():
    values, undefined = _undefined_after_calculate_all(
        PerformanceMetrics(_curve(100.0, 100.0, 100.0), _trades(0.0, 0.0), 100.0))
    assert values['win_rate'] == 0.0  # defined: 0 winners of 2
    assert undefined == {'avg_win': 'no winning trades', 'avg_loss': 'no losing trades',
                         'profit_factor': 'no losing trades', 'sharpe_ratio': 'zero volatility'}


def test_losing_trades_only_give_a_zero_profit_factor():
    values, undefined = _undefined_after_calculate_all(
        PerformanceMetrics(_curve(100.0, 99.0, 97.0), _trades(-1.0, -2.0), 100.0))
    assert values['profit_factor'] == 0.0
    assert undefined['avg_win'] == 'no winning trades'


def test_one_equity_point():
    values, undefined = _undefined_after_calculate_all(PerformanceMetrics(_curve(100.0), [], 100.0))
    assert values['total_return'] == 0.0 and values['max_drawdown'] == 0.0
    assert undefined['cagr'] == 'the run starts and ends on the same day'
    assert undefined['volatility'] == undefined['sharpe_ratio'] == 'fewer than two daily returns'


def test_one_daily_return_used_to_give_nan():
    values, undefined = _undefined_after_calculate_all(PerformanceMetrics(_curve(100.0, 101.0), [], 100.0))
    assert values['volatility'] is None and values['sharpe_ratio'] is None
    assert undefined['volatility'] == 'fewer than two daily returns'
    assert values['cagr'] is not None


def test_overflowing_cagr_is_undefined_not_infinite():
    # x10,000 in one day: (1e4) ** 365.25 overflows a double
    with np.errstate(over='ignore'):
        values, undefined = _undefined_after_calculate_all(
            PerformanceMetrics(_curve(100.0, 1_000_000.0), [], 100.0))
    assert values['cagr'] is None and undefined['cagr'] == 'the result is not a finite number'
    assert values['total_return'] == pytest.approx(999_900.0)


def test_single_day_regime_has_undefined_volatility():
    from backtest_engine.metrics import returns_by_regime
    dates = pd.bdate_range('2023-01-02', periods=4)
    curve = [{'timestamp': d, 'equity': e} for d, e in zip(dates, [100.0, 101.0, 102.0, 101.0])]
    labels = {dates[1]: 'bull', dates[2]: 'bull', dates[3]: 'bear'}
    result = returns_by_regime(curve, labels, ['bull', 'bear'])
    assert result['bull']['undefined_metrics'] == {}
    assert isinstance(result['bull']['annualized_volatility_pct'], float)
    assert result['bear']['annualized_volatility_pct'] is None
    assert result['bear']['undefined_metrics'] == {'annualized_volatility_pct': 'fewer than two daily returns'}
