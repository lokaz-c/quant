"""
Runs a backtest strategy against an Alpaca paper account on daily bars.

Each cycle builds an engine Portfolio from the account, so the strategy and
the risk rules see the same interface they see in a backtest. Orders go out as
whole-share day market orders.

    python -m live_trading.live_trader --strategy ma --symbols AAPL,MSFT --once

Paper trading only, unless AlpacaBroker's live opt-in is satisfied.
"""
import argparse
import math
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence

from backtest_engine.portfolio import Order, Portfolio, Position
from backtest_engine.risk import RiskConfig, RiskManager
from backtest_engine.strategy_base import StrategyBase


class LiveTrader:
    def __init__(
        self,
        broker,
        strategy: StrategyBase,
        symbols: Sequence[str],
        risk_config: Optional[RiskConfig] = None,
        max_position_size: float = 0.10,
        max_positions: int = 5,
        check_interval: int = 300,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """
        Args:
            broker: AlpacaBroker (or anything with the same methods)
            strategy: any StrategyBase subclass from backtest_engine.strategies
            symbols: tickers to trade
            risk_config: optional engine risk rules (position caps, stop-loss, ...)
            max_position_size: cap per new position as a fraction of equity
            max_positions: cap on concurrent positions
            check_interval: seconds between cycles in run()
        """
        self.broker = broker
        self.strategy = strategy
        self.symbols = list(symbols)
        self.risk_manager = RiskManager(risk_config) if risk_config else None
        self.max_position_size = max_position_size
        self.max_positions = max_positions
        self.check_interval = check_interval
        self._sleep = sleep

    def portfolio_snapshot(self) -> Portfolio:
        """The account's cash and positions as an engine Portfolio."""
        account = self.broker.get_account()
        portfolio = Portfolio(initial_capital=account.equity)
        portfolio.cash = account.cash
        now = datetime.now(timezone.utc)
        for p in self.broker.get_positions():
            portfolio.positions[p.symbol] = Position(
                symbol=p.symbol,
                quantity=p.quantity,
                entry_price=p.avg_entry_price,
                entry_date=now,
                current_price=p.current_price,
            )
        return portfolio

    def run_once(self) -> List[Order]:
        """One cycle. Returns the orders that were sent to the broker."""
        if not self.broker.is_market_open():
            return []

        bars = self.broker.get_daily_bars(self.symbols)
        if bars.empty:
            return []
        prices = bars.groupby('symbol')['close'].last().to_dict()
        portfolio = self.portfolio_snapshot()
        portfolio.update_prices(prices)

        orders = []
        if self.risk_manager:
            self.risk_manager.check_drawdown(portfolio)  # may halt new entries
            orders += self.risk_manager.check_stop_loss_take_profit(portfolio, prices)
        exiting = {o.symbol for o in orders}
        signals = [o for o in self.strategy.generate_signals(bars, portfolio) if o.symbol not in exiting]
        if self.risk_manager:
            signals = self.risk_manager.apply_risk_adjustments(signals, portfolio, prices)
        orders += signals

        sent = []
        open_positions = len(portfolio.positions)
        for order in orders:
            if order.side == 'sell':
                if order.symbol in portfolio.positions:
                    self.broker.close_position(order.symbol)
                    sent.append(order)
                continue

            price = prices.get(order.symbol)
            if not price or order.symbol in portfolio.positions or open_positions >= self.max_positions:
                continue
            cap = portfolio.equity * self.max_position_size / price
            qty = math.floor(min(order.quantity, cap))
            if qty < 1:
                continue
            self.broker.submit_market_order(order.symbol, qty, 'buy')
            sent.append(Order(symbol=order.symbol, quantity=qty, side='buy'))
            open_positions += 1
        return sent

    def run(self, max_cycles: Optional[int] = None) -> None:
        """Repeat run_once every check_interval seconds until Ctrl+C (or max_cycles)."""
        cycles = 0
        try:
            while max_cycles is None or cycles < max_cycles:
                sent = self.run_once()
                stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f'[{stamp}] sent {len(sent)} order(s): '
                      + ', '.join(f'{o.side} {o.quantity:g} {o.symbol}' for o in sent))
                cycles += 1
                if max_cycles is None or cycles < max_cycles:
                    self._sleep(self.check_interval)
        except KeyboardInterrupt:
            print('Stopped.')


def main(argv: Optional[List[str]] = None) -> None:
    from backtest_engine.strategies.moving_average import MovingAverageCrossover
    from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
    from backtest_engine.strategies.trend_following import TrendFollowing
    from live_trading.alpaca_broker import AlpacaBroker

    strategies = {'ma': MovingAverageCrossover, 'rsi': RSIMeanReversion, 'trend': TrendFollowing}
    parser = argparse.ArgumentParser(description='Run a strategy on an Alpaca paper account.')
    parser.add_argument('--strategy', choices=sorted(strategies), default='ma')
    parser.add_argument('--symbols', default='AAPL,MSFT,GOOGL')
    parser.add_argument('--interval', type=int, default=300, help='seconds between cycles')
    parser.add_argument('--once', action='store_true', help='run a single cycle and exit')
    args = parser.parse_args(argv)

    broker = AlpacaBroker(paper=True)
    trader = LiveTrader(broker, strategies[args.strategy](),
                        [s.strip() for s in args.symbols.split(',') if s.strip()],
                        check_interval=args.interval)
    trader.run(max_cycles=1 if args.once else None)


if __name__ == '__main__':
    main()
