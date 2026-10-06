"""
The engine computes each strategy's indicators once per symbol, before the bar
loop (StrategyBase.prepare), instead of recomputing them over the whole
history on every bar. These tests check that this changes no result and peeks
at no future bar:

- the precomputed indicators equal the old per-bar computation (the formulas
  the strategies used before, recomputed over the history up to each bar)
  exactly, on seeded data;
- a backtest gives exactly the same equity curve and trades as the old
  per-bar loop, which filtered the history and called generate_signals on
  every bar: with and without the risk layer, with a symbol that starts late
  and with missing bars;
- changing every bar after a date changes no indicator, trade or equity value
  up to that date, and that check catches a strategy that does look ahead.
"""
import contextlib
import io
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import pytest

from backtest_engine.backtester import Backtester
from backtest_engine.data_loader import generate_sample_data
from backtest_engine.portfolio import Order, Portfolio
from backtest_engine.risk import RiskConfig, RiskManager
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.strategies.trend_following import TrendFollowing
from backtest_engine.strategy_base import BARS_SEEN, StrategyBase, SymbolBars
from data_sources.sources import InMemoryLoader

SYMBOLS = ['AAPL', 'JPM', 'TSLA']

STRATEGIES = [
    pytest.param(lambda: MovingAverageCrossover(), id='ma-20-50'),
    pytest.param(lambda: MovingAverageCrossover({'fast_period': 5, 'slow_period': 12}), id='ma-5-12'),
    pytest.param(lambda: RSIMeanReversion(), id='rsi-14'),
    pytest.param(lambda: RSIMeanReversion({'rsi_period': 3, 'oversold': 20, 'overbought': 80}), id='rsi-3'),
    pytest.param(lambda: TrendFollowing(), id='trend-20-14'),
    pytest.param(lambda: TrendFollowing({'lookback_period': 5, 'atr_period': 3, 'atr_multiplier': 1.0}),
                 id='trend-5-3'),
]

TIGHT_RISK = RiskConfig(name='Tight', max_position_size=0.1, max_portfolio_exposure=0.4,
                        stop_loss_pct=0.03, take_profit_pct=0.06, max_drawdown_pct=0.08)
NO_RISK = RiskConfig(name='No Risk Management', enabled=False)


def sorted_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """In the order DataFrame loaders return bars: by symbol, then time"""
    return frame.sort_values(['symbol', 'timestamp']).reset_index(drop=True)


@pytest.fixture(scope='module')
def seeded_bars() -> pd.DataFrame:
    return sorted_bars(generate_sample_data(SYMBOLS, '2023-01-01', '2023-12-31', seed=7))


@pytest.fixture(scope='module')
def gappy_bars(seeded_bars) -> pd.DataFrame:
    """JPM starts in April, and about 3% of the other bars are missing (seeded)"""
    keep = np.random.default_rng(3).random(len(seeded_bars)) > 0.03
    keep &= ~((seeded_bars['symbol'] == 'JPM') & (seeded_bars['timestamp'] < '2023-04-01'))
    return seeded_bars[keep].reset_index(drop=True)


def per_bar_indicators(strategy: StrategyBase, bars: pd.DataFrame) -> pd.DataFrame:
    """
    The indicator values the strategies used before precomputation: on every
    bar, from scratch, over the symbol's history up to that bar, with the
    formulas from the old generate_signals.
    """
    rows = []
    for k in range(len(bars)):
        history = bars.iloc[:k + 1].copy()
        close = history['close']
        if isinstance(strategy, MovingAverageCrossover):
            fast = close.rolling(window=strategy.fast_period).mean()
            slow = close.rolling(window=strategy.slow_period).mean()
            rows.append({'fast_ma': fast.iloc[-1], 'slow_ma': slow.iloc[-1],
                         'prev_fast_ma': fast.iloc[-2] if k else np.nan,
                         'prev_slow_ma': slow.iloc[-2] if k else np.nan})
        elif isinstance(strategy, RSIMeanReversion):
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=strategy.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=strategy.rsi_period).mean()
            rows.append({'rsi': (100 - (100 / (1 + gain / loss))).iloc[-1]})
        else:
            high, low = history['high'], history['low']
            true_range = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())],
                                   axis=1).max(axis=1)
            rows.append({'highest': high.rolling(window=strategy.lookback_period).max().shift(1).iloc[-1],
                         'lowest': low.rolling(window=strategy.lookback_period).min().shift(1).iloc[-1],
                         'atr': true_range.rolling(window=strategy.atr_period).mean().iloc[-1]})
    return pd.DataFrame(rows, index=bars.index)


def prepared_frame(prepared: SymbolBars, index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame([prepared.bar(k) for k in range(len(prepared))], index=index)


@pytest.mark.parametrize('make_strategy', STRATEGIES)
def test_precomputed_indicators_equal_the_per_bar_computation(make_strategy, seeded_bars):
    strategy = make_strategy()
    prepared = strategy.prepare(seeded_bars)
    assert sorted(prepared) == SYMBOLS

    for symbol, bars in seeded_bars.groupby('symbol'):
        expected = per_bar_indicators(strategy, bars)
        got = prepared_frame(prepared[symbol], bars.index)
        for column in expected.columns:
            # Bit for bit, with NaN in the same places (the warm-up)
            np.testing.assert_array_equal(got[column].to_numpy(dtype=float),
                                          expected[column].to_numpy(dtype=float), err_msg=column)
            assert expected[column].notna().sum() > len(bars) // 2   # mostly real values, not warm-up
        assert got[BARS_SEEN].tolist() == list(range(1, len(bars) + 1))


def per_bar_backtest(strategy: StrategyBase, data: pd.DataFrame, risk_config: RiskConfig) -> Portfolio:
    """
    The engine's bar loop before precomputation: on every bar, filter the
    history up to that bar and call generate_signals on it.
    """
    portfolio, risk = Portfolio(100_000), RiskManager(risk_config)
    for timestamp, bar_data in data.groupby('timestamp'):
        prices = dict(zip(bar_data['symbol'], bar_data['close']))
        portfolio.update_prices(prices)
        if risk.config.enabled:
            for order in risk.check_stop_loss_take_profit(portfolio, prices):
                if prices.get(order.symbol):
                    portfolio.execute_order(order, prices[order.symbol], timestamp)
            risk.check_drawdown(portfolio)
        orders = strategy.generate_signals(data[data['timestamp'] <= timestamp], portfolio)
        if risk.config.enabled:
            orders = risk.apply_risk_adjustments(orders, portfolio, prices)
        for order in orders:
            if prices.get(order.symbol):
                portfolio.execute_order(order, prices[order.symbol], timestamp)
        portfolio.record_equity(timestamp)
    last = data['timestamp'].max()
    final = data[data['timestamp'] == last]
    portfolio.close_all_positions(dict(zip(final['symbol'], final['close'])), last)
    return portfolio


def run_engine(strategy: StrategyBase, data: pd.DataFrame, risk_config: RiskConfig = NO_RISK) -> Backtester:
    backtester = Backtester(strategy, InMemoryLoader(data), 100_000, risk_config=risk_config)
    with contextlib.redirect_stdout(io.StringIO()):   # the engine prints progress
        backtester.run()
    return backtester


@pytest.mark.parametrize('risk_config', [NO_RISK, TIGHT_RISK], ids=['no-risk', 'tight-risk'])
@pytest.mark.parametrize('make_strategy', STRATEGIES)
def test_backtest_matches_the_per_bar_loop_exactly(make_strategy, risk_config, gappy_bars):
    engine = run_engine(make_strategy(), gappy_bars, risk_config)
    reference = per_bar_backtest(make_strategy(), engine.data, risk_config)

    assert len(engine.portfolio.trades) > 0
    # == on floats: identical values, not approximately equal ones
    assert engine.portfolio.trades == reference.trades
    assert engine.portfolio.equity_history == reference.equity_history
    assert engine.portfolio.cash == reference.cash


def with_changed_future(data: pd.DataFrame, cut: pd.Timestamp) -> pd.DataFrame:
    """The same bars up to `cut`; every later bar's prices scaled by a random factor of 0.5 to 1.5"""
    changed = data.copy()
    later = changed['timestamp'] > cut
    factor = np.random.default_rng(99).uniform(0.5, 1.5, int(later.sum()))
    for column in ('open', 'high', 'low', 'close'):
        changed.loc[later, column] = changed.loc[later, column] * factor
    return changed


def recorded_at(trade) -> pd.Timestamp:
    return trade.exit_date if trade.exit_date is not None else trade.entry_date


def assert_no_lookahead(make_strategy, data: pd.DataFrame) -> None:
    """Change every bar after the middle date; nothing up to that date may change"""
    timestamps = np.sort(data['timestamp'].unique())
    cut = pd.Timestamp(timestamps[len(timestamps) // 2])
    changed = with_changed_future(data, cut)

    # Indicators: identical up to the cut (and the change does reach later rows)
    original, altered = make_strategy().prepare(data), make_strategy().prepare(changed)
    for symbol, bars in data.groupby('symbol'):
        before, after = prepared_frame(original[symbol], bars.index), prepared_frame(altered[symbol], bars.index)
        past = (bars['timestamp'] <= cut).to_numpy()
        columns = [c for c in before.columns if pd.api.types.is_float_dtype(before[c])]
        for column in columns:
            np.testing.assert_array_equal(after[column].to_numpy()[past], before[column].to_numpy()[past],
                                          err_msg=f'{symbol} {column} changed before {cut:%Y-%m-%d}')
        assert not after.loc[~past, columns].equals(before.loc[~past, columns])

    # Signals, trades and equity: identical up to the cut
    a, b = run_engine(make_strategy(), data).portfolio, run_engine(make_strategy(), changed).portfolio
    assert ([t for t in a.trades if recorded_at(t) <= cut] == [t for t in b.trades if recorded_at(t) <= cut]), \
        f'trades up to {cut:%Y-%m-%d} changed'
    assert ([e for e in a.equity_history if e['timestamp'] <= cut]
            == [e for e in b.equity_history if e['timestamp'] <= cut]), f'equity up to {cut:%Y-%m-%d} changed'
    assert any(recorded_at(t) <= cut for t in a.trades)


@pytest.mark.parametrize('make_strategy', STRATEGIES)
def test_changing_future_bars_changes_nothing_before_them(make_strategy, seeded_bars):
    assert_no_lookahead(make_strategy, seeded_bars)


class PeekingStrategy(StrategyBase):
    """Buys when tomorrow's close is higher: an indicator that looks ahead"""

    def __init__(self):
        super().__init__('Peeking')

    def indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({'next_close': bars['close'].shift(-1)}, index=bars.index)

    def signal(self, symbol: str, bar: Dict[str, Any], portfolio: Portfolio) -> Optional[Order]:
        if symbol in portfolio.positions:
            return Order(symbol, portfolio.positions[symbol].quantity, 'sell')
        if bar['next_close'] > bar['close']:
            return Order(symbol, self.calculate_position_size(symbol, bar['close'], portfolio), 'buy')
        return None


def test_the_lookahead_check_catches_a_strategy_that_peeks(seeded_bars):
    with pytest.raises(AssertionError, match='changed before'):
        assert_no_lookahead(PeekingStrategy, seeded_bars)


def test_a_prepared_bar_has_the_values_and_types_of_the_dataframe_row(seeded_bars):
    bars = seeded_bars[seeded_bars['symbol'] == 'AAPL']
    strategy = MovingAverageCrossover()
    frame = bars.assign(**strategy.indicators(bars))
    prepared = SymbolBars(bars, strategy.indicators(bars))
    for k in (0, 60, len(bars) - 1):
        row, bar = frame.iloc[k], prepared.bar(k)
        assert bar[BARS_SEEN] == k + 1
        for name in frame.columns:
            assert type(bar[name]) is type(row[name]), name
            assert bar[name] == row[name] or (pd.isna(bar[name]) and pd.isna(row[name])), name


def test_indicators_must_line_up_with_the_bars(seeded_bars):
    bars = seeded_bars[seeded_bars['symbol'] == 'AAPL']
    with pytest.raises(ValueError, match='one row per bar'):
        SymbolBars(bars, pd.DataFrame({'x': range(len(bars) - 1)}))
