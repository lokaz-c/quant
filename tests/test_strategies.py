"""
Unit tests for the strategies' entry and exit signals, plus an engine-level
check that every strategy trades on generated data.
"""
import contextlib
import io
from datetime import datetime

import pandas as pd
import pytest

from backtest_engine.backtester import Backtester
from backtest_engine.data_loader import DataLoader, generate_sample_data
from backtest_engine.portfolio import Order, Portfolio
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.strategies.trend_following import TrendFollowing


def bars(closes, symbol='TEST'):
    """Daily bars with a +/-1% intraday range around each close."""
    dates = pd.date_range('2023-01-02', periods=len(closes), freq='B')
    return pd.DataFrame({
        'timestamp': dates,
        'symbol': symbol,
        'open': closes,
        'high': [c * 1.01 for c in closes],
        'low': [c * 0.99 for c in closes],
        'close': closes,
        'volume': 1_000_000,
    })


def holding(symbol='TEST', price=100.0):
    portfolio = Portfolio(100_000)
    portfolio.execute_order(Order(symbol=symbol, quantity=100, side='buy'), price, datetime(2023, 1, 2))
    return portfolio


class TestTrendFollowing:
    def test_buys_when_close_breaks_the_previous_20_day_high(self):
        data = bars([100.0] * 30 + [105.0])  # previous 20-day high is 101
        orders = TrendFollowing().generate_signals(data, Portfolio(100_000))
        assert [(o.symbol, o.side) for o in orders] == [('TEST', 'buy')]

    def test_no_entry_inside_the_channel(self):
        data = bars([100.0] * 30 + [100.5])
        assert TrendFollowing().generate_signals(data, Portfolio(100_000)) == []

    def test_sells_when_close_breaks_the_previous_20_day_low(self):
        data = bars([100.0] * 30 + [95.0])  # previous 20-day low is 99
        orders = TrendFollowing().generate_signals(data, holding())
        assert [(o.side, o.quantity) for o in orders] == [('sell', 100)]

    def test_holds_inside_the_channel(self):
        data = bars([100.0] * 30 + [100.2])
        assert TrendFollowing().generate_signals(data, holding()) == []


class TestMovingAverageCrossover:
    def test_buys_on_fast_ma_crossing_above_slow_ma(self):
        data = bars([100.0] * 59 + [110.0])
        orders = MovingAverageCrossover().generate_signals(data, Portfolio(100_000))
        assert [o.side for o in orders] == ['buy']

    def test_sells_on_fast_ma_crossing_below_slow_ma(self):
        data = bars([100.0] * 59 + [90.0])
        orders = MovingAverageCrossover().generate_signals(data, holding())
        assert [o.side for o in orders] == ['sell']

    def test_needs_slow_period_of_history(self):
        data = bars([100.0] * 40 + [110.0])
        assert MovingAverageCrossover().generate_signals(data, Portfolio(100_000)) == []


class TestRSIMeanReversion:
    def test_buys_when_oversold(self):
        data = bars([100.0 - i for i in range(20)])  # only losses -> RSI 0
        orders = RSIMeanReversion().generate_signals(data, Portfolio(100_000))
        assert [o.side for o in orders] == ['buy']

    def test_sells_when_overbought(self):
        data = bars([100.0 + i for i in range(20)])  # only gains -> RSI 100
        orders = RSIMeanReversion().generate_signals(data, holding())
        assert [o.side for o in orders] == ['sell']


@pytest.mark.parametrize('strategy_cls', [MovingAverageCrossover, RSIMeanReversion, TrendFollowing])
def test_every_strategy_trades_on_generated_data(strategy_cls, tmp_path):
    path = tmp_path / 'bars.csv'
    generate_sample_data(['AAPL', 'MSFT'], '2021-01-01', '2022-12-31', output_path=path, seed=11)
    with contextlib.redirect_stdout(io.StringIO()):
        results = Backtester(strategy_cls(), DataLoader(str(path)), 100_000).run()

    assert results['metrics']['num_trades'] > 0
    # Everything is closed on the last bar, so equity is all cash
    assert results['final_portfolio']['positions'] == 0
    assert results['final_portfolio']['equity'] == pytest.approx(results['final_portfolio']['cash'])
