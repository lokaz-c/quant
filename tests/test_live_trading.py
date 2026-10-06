"""
Tests for the Alpaca paper-trading adapter and LiveTrader. No network calls:
the SDK clients and the broker are replaced with fakes. Tests that build real
alpaca-py request objects are skipped when the SDK is not installed
(pip install -r requirements-live.txt; CI installs it).
"""
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest_engine.portfolio import Order
from backtest_engine.risk import RiskConfig
from backtest_engine.strategy_base import StrategyBase
from live_trading.alpaca_broker import (
    LIVE_TRADING_ENV_VAR, AccountSnapshot, AlpacaBroker, LivePosition, LiveTradingNotAllowed,
)
from live_trading.live_trader import LiveTrader


class FakeTradingClient:
    def __init__(self, positions=()):
        self.orders = []
        self.closed = []
        self._positions = list(positions)

    def get_account(self):
        return SimpleNamespace(equity='100000.5', cash='60000', buying_power='120000')

    def get_all_positions(self):
        return self._positions

    def submit_order(self, order_data):
        self.orders.append(order_data)
        return SimpleNamespace(id='order-1')

    def close_position(self, symbol):
        self.closed.append(symbol)

    def get_clock(self):
        return SimpleNamespace(is_open=True)


class FakeDataClient:
    def __init__(self, frame):
        self.frame = frame
        self.requests = []

    def get_stock_bars(self, request):
        self.requests.append(request)
        return SimpleNamespace(df=self.frame)


@pytest.fixture(autouse=True)
def no_live_opt_in(monkeypatch):
    monkeypatch.delenv(LIVE_TRADING_ENV_VAR, raising=False)


# --- paper-only guard -------------------------------------------------------

def test_live_mode_without_opt_in_raises_before_any_client_is_built():
    # No keys and no clients: if the guard did not run first this would be a ValueError
    with pytest.raises(LiveTradingNotAllowed):
        AlpacaBroker(paper=False)


@pytest.mark.parametrize('value', ['', '1', 'true', 'YES please', 'no'])
def test_only_the_exact_confirmation_enables_live_mode(monkeypatch, value):
    monkeypatch.setenv(LIVE_TRADING_ENV_VAR, value)
    with pytest.raises(LiveTradingNotAllowed):
        AlpacaBroker(paper=False, trading_client=FakeTradingClient(), data_client=FakeDataClient(None))


def test_live_mode_with_flag_and_env_var(monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV_VAR, 'yes')
    broker = AlpacaBroker(paper=False, trading_client=FakeTradingClient(), data_client=FakeDataClient(None))
    assert broker.paper is False


def test_paper_is_the_default_endpoint():
    pytest.importorskip('alpaca')
    from alpaca.common.enums import BaseURL

    broker = AlpacaBroker(api_key='test-key', secret_key='test-secret')  # no request is made
    assert broker.paper is True
    assert broker.trading._base_url == BaseURL.TRADING_PAPER


def test_missing_credentials_are_reported(monkeypatch):
    monkeypatch.delenv('ALPACA_API_KEY', raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY', raising=False)
    with pytest.raises(ValueError, match='ALPACA_API_KEY'):
        AlpacaBroker()


# --- adapter mapping --------------------------------------------------------

def test_account_and_positions_are_parsed_from_sdk_strings():
    position = SimpleNamespace(symbol='AAPL', qty='10', avg_entry_price='150.5', current_price='155',
                               market_value='1550', unrealized_pl='45')
    broker = AlpacaBroker(trading_client=FakeTradingClient([position]), data_client=FakeDataClient(None))
    assert broker.get_account() == AccountSnapshot(equity=100000.5, cash=60000.0, buying_power=120000.0)
    assert broker.get_positions() == [LivePosition('AAPL', 10.0, 150.5, 155.0, 1550.0, 45.0)]


def test_market_order_is_a_valid_alpaca_request():
    pytest.importorskip('alpaca')
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    trading = FakeTradingClient()
    broker = AlpacaBroker(trading_client=trading, data_client=FakeDataClient(None))
    assert broker.submit_market_order('MSFT', 3, 'buy') == 'order-1'

    (request,) = trading.orders
    assert isinstance(request, MarketOrderRequest)
    assert (request.symbol, request.qty, request.side, request.time_in_force) == \
        ('MSFT', 3, OrderSide.BUY, TimeInForce.DAY)


def test_daily_bars_are_returned_in_the_backtester_layout():
    pytest.importorskip('alpaca')
    from alpaca.data.enums import DataFeed

    index = pd.MultiIndex.from_tuples(
        [('MSFT', pd.Timestamp('2024-01-03', tz='UTC')), ('AAPL', pd.Timestamp('2024-01-03', tz='UTC')),
         ('AAPL', pd.Timestamp('2024-01-02', tz='UTC'))],
        names=['symbol', 'timestamp'])
    sdk_frame = pd.DataFrame({'open': [1.0, 2.0, 3.0], 'high': [1.0, 2.0, 3.0], 'low': [1.0, 2.0, 3.0],
                              'close': [1.0, 2.0, 3.0], 'volume': [10, 20, 30],
                              'trade_count': [1, 1, 1], 'vwap': [1.0, 2.0, 3.0]}, index=index)
    data = FakeDataClient(sdk_frame)
    broker = AlpacaBroker(trading_client=FakeTradingClient(), data_client=data)

    bars = broker.get_daily_bars(['AAPL', 'MSFT'])

    assert list(bars.columns) == ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
    assert list(zip(bars['symbol'], bars['close'])) == [('AAPL', 3.0), ('AAPL', 2.0), ('MSFT', 1.0)]
    assert data.requests[0].feed == DataFeed.IEX


# --- LiveTrader -------------------------------------------------------------

class FakeBroker:
    def __init__(self, market_open=True, positions=(), equity=100_000.0, closes=None):
        self.market_open = market_open
        self.positions = list(positions)
        self.equity = equity
        self.closes = closes or {'AAPL': 100.0, 'MSFT': 50.0, 'TSLA': 200.0}
        self.submitted = []
        self.closed = []

    def is_market_open(self):
        return self.market_open

    def get_account(self):
        invested = sum(p.market_value for p in self.positions)
        return AccountSnapshot(equity=self.equity, cash=self.equity - invested, buying_power=self.equity)

    def get_positions(self):
        return self.positions

    def get_daily_bars(self, symbols):
        rows = [{'timestamp': pd.Timestamp('2024-01-02', tz='UTC'), 'symbol': s, 'open': c, 'high': c,
                 'low': c, 'close': c, 'volume': 1} for s, c in self.closes.items() if s in symbols]
        return pd.DataFrame(rows)

    def submit_market_order(self, symbol, qty, side):
        self.submitted.append((symbol, qty, side))
        return 'id'

    def close_position(self, symbol):
        self.closed.append(symbol)


class ScriptedStrategy(StrategyBase):
    """Returns fixed orders, to check that LiveTrader routes what the strategy says."""

    def __init__(self, orders):
        super().__init__('Scripted')
        self.orders = orders
        self.calls = 0

    def generate_signals(self, data, portfolio):
        self.calls += 1
        return [Order(o.symbol, o.quantity, o.side) for o in self.orders]

    def signal(self, symbol, bar, portfolio):
        return None   # unused: generate_signals is overridden


def held(symbol, qty, entry, current):
    return LivePosition(symbol, qty, entry, current, qty * current, qty * (current - entry))


def test_nothing_happens_while_the_market_is_closed():
    strategy = ScriptedStrategy([Order('AAPL', 10, 'buy')])
    broker = FakeBroker(market_open=False)
    assert LiveTrader(broker, strategy, ['AAPL']).run_once() == []
    assert strategy.calls == 0 and broker.submitted == []


def test_strategy_buys_become_whole_share_orders_capped_per_position():
    # Strategy asks for 500 shares of AAPL at $100; the 10% cap allows $10,000 -> 100 shares
    broker = FakeBroker()
    LiveTrader(broker, ScriptedStrategy([Order('AAPL', 500, 'buy')]), ['AAPL']).run_once()
    assert broker.submitted == [('AAPL', 100, 'buy')]


def test_fractional_quantities_round_down_and_tiny_orders_are_skipped():
    broker = FakeBroker()
    strategy = ScriptedStrategy([Order('MSFT', 7.9, 'buy'), Order('TSLA', 0.5, 'buy')])
    LiveTrader(broker, strategy, ['MSFT', 'TSLA']).run_once()
    assert broker.submitted == [('MSFT', 7, 'buy')]


def test_strategy_sells_close_held_positions_only():
    broker = FakeBroker(positions=[held('AAPL', 10, 90.0, 100.0)])
    strategy = ScriptedStrategy([Order('AAPL', 10, 'sell'), Order('MSFT', 5, 'sell')])
    LiveTrader(broker, strategy, ['AAPL', 'MSFT']).run_once()
    assert broker.closed == ['AAPL']


def test_max_positions_is_respected():
    broker = FakeBroker(positions=[held('AAPL', 10, 100.0, 100.0)])
    strategy = ScriptedStrategy([Order('MSFT', 10, 'buy'), Order('TSLA', 10, 'buy')])
    LiveTrader(broker, strategy, ['AAPL', 'MSFT', 'TSLA'], max_positions=2).run_once()
    assert broker.submitted == [('MSFT', 10, 'buy')]


def test_risk_config_stop_loss_closes_a_losing_position():
    # Bought at 125, now 100: a 20% loss against an 8% stop
    broker = FakeBroker(positions=[held('AAPL', 10, 125.0, 100.0)])
    trader = LiveTrader(broker, ScriptedStrategy([]), ['AAPL'],
                        risk_config=RiskConfig(name='Moderate', stop_loss_pct=0.08))
    trader.run_once()
    assert broker.closed == ['AAPL']


def test_run_stops_after_max_cycles_without_sleeping_at_the_end():
    sleeps = []
    trader = LiveTrader(FakeBroker(market_open=False), ScriptedStrategy([]), ['AAPL'],
                        check_interval=60, sleep=sleeps.append)
    trader.run(max_cycles=3)
    assert sleeps == [60, 60]
