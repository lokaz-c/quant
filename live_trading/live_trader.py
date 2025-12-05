"""
Live trading engine that executes strategies in real-time
PAPER TRADING MODE BY DEFAULT
"""
import time
from datetime import datetime
from typing import Optional
from .alpaca_broker import AlpacaBroker
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.strategy_base import StrategyBase


class LiveTrader:
    """
    Execute trading strategies in real-time

    WARNING: Always test with paper trading first!
    """

    def __init__(
        self,
        broker: AlpacaBroker,
        strategy: StrategyBase,
        check_interval: int = 60,  # seconds
        max_position_size: float = 0.10,  # 10% of portfolio per position
        max_positions: int = 5
    ):
        """
        Initialize live trader

        Args:
            broker: Connected broker instance
            strategy: Trading strategy to execute
            check_interval: Seconds between strategy checks
            max_position_size: Max % of portfolio per position
            max_positions: Maximum number of concurrent positions
        """
        self.broker = broker
        self.strategy = strategy
        self.check_interval = check_interval
        self.max_position_size = max_position_size
        self.max_positions = max_positions
        self.running = False

        print(f"🤖 Live Trader Initialized")
        print(f"   Strategy: {strategy.name}")
        print(f"   Check Interval: {check_interval}s")
        print(f"   Max Position Size: {max_position_size * 100}%")

    def calculate_position_size(self, symbol: str, price: float) -> float:
        """Calculate number of shares to buy"""
        account = self.broker.get_account_info()
        buying_power = account['buying_power']

        # Use max_position_size of available buying power
        max_value = buying_power * self.max_position_size
        shares = int(max_value / price)

        return shares

    def execute_strategy(self, symbols: list):
        """
        Execute strategy for given symbols

        This is a simplified version - in production you'd want:
        - More sophisticated signal generation
        - Better error handling
        - Risk management integration
        - Position sizing based on volatility
        """
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking signals...")

        # Get current positions
        current_positions = self.broker.get_positions()
        position_symbols = {pos.symbol for pos in current_positions}

        print(f"Current Positions: {len(current_positions)}/{self.max_positions}")

        for symbol in symbols:
            try:
                # Get recent market data (last 100 bars)
                data = self.broker.get_market_data(symbol, timeframe='1Day', limit=100)

                if len(data) < 50:  # Need enough history
                    continue

                # Get latest quote
                quote = self.broker.get_latest_quote(symbol)
                current_price = (quote['bid_price'] + quote['ask_price']) / 2

                # Simple signal generation (you'd use your strategy here)
                # For demo, using a basic MA crossover
                closes = [bar['close'] for bar in data]
                if len(closes) >= 50:
                    fast_ma = sum(closes[-20:]) / 20
                    slow_ma = sum(closes[-50:]) / 50

                    # BUY SIGNAL: Fast MA crosses above slow MA
                    if fast_ma > slow_ma and symbol not in position_symbols:
                        if len(current_positions) < self.max_positions:
                            qty = self.calculate_position_size(symbol, current_price)

                            if qty > 0:
                                print(f"🟢 BUY SIGNAL: {symbol}")
                                print(f"   Price: ${current_price:.2f}")
                                print(f"   Quantity: {qty}")

                                order = self.broker.place_order(
                                    symbol=symbol,
                                    qty=qty,
                                    side='buy',
                                    order_type='market'
                                )
                                print(f"   Order ID: {order.id}")

                    # SELL SIGNAL: Fast MA crosses below slow MA
                    elif fast_ma < slow_ma and symbol in position_symbols:
                        position = self.broker.get_position(symbol)
                        if position:
                            print(f"🔴 SELL SIGNAL: {symbol}")
                            print(f"   Price: ${current_price:.2f}")
                            print(f"   Quantity: {position.quantity}")
                            print(f"   P&L: ${position.unrealized_pl:.2f}")

                            self.broker.close_position(symbol)

            except Exception as e:
                print(f"❌ Error processing {symbol}: {str(e)}")

    def run(self, symbols: list):
        """
        Run live trading loop

        Args:
            symbols: List of symbols to trade
        """
        self.running = True

        print(f"\n{'='*60}")
        print(f"🚀 STARTING LIVE TRADER")
        print(f"{'='*60}")
        print(f"Symbols: {', '.join(symbols)}")
        print(f"Strategy: {self.strategy.name}")
        print(f"\n⚠️  Press Ctrl+C to stop\n")

        try:
            while self.running:
                # Only trade when market is open
                if self.broker.is_market_open():
                    self.execute_strategy(symbols)
                else:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Market closed, waiting...")

                # Wait before next check
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            print("\n\n🛑 Stopping trader...")
            self.stop()

    def stop(self):
        """Stop the trader"""
        self.running = False
        print("✅ Trader stopped")

        # Print final summary
        account = self.broker.get_account_info()
        positions = self.broker.get_positions()

        print(f"\n{'='*60}")
        print("FINAL SUMMARY")
        print(f"{'='*60}")
        print(f"Portfolio Value: ${account['portfolio_value']:,.2f}")
        print(f"Cash: ${account['cash']:,.2f}")
        print(f"Open Positions: {len(positions)}")

        for pos in positions:
            print(f"\n  {pos.symbol}:")
            print(f"    Quantity: {pos.quantity}")
            print(f"    Entry: ${pos.avg_entry_price:.2f}")
            print(f"    Current: ${pos.current_price:.2f}")
            print(f"    P&L: ${pos.unrealized_pl:.2f} ({pos.unrealized_plpc:.2f}%)")


# Example usage
if __name__ == '__main__':
    # ALWAYS USE PAPER TRADING FIRST!
    broker = AlpacaBroker(paper=True)

    # Create strategy
    strategy = MovingAverageCrossover(parameters={
        'fast_period': 20,
        'slow_period': 50
    })

    # Create trader
    trader = LiveTrader(
        broker=broker,
        strategy=strategy,
        check_interval=300,  # Check every 5 minutes
        max_position_size=0.10,  # 10% per position
        max_positions=5
    )

    # Run with specific symbols
    symbols = ['AAPL', 'GOOGL', 'MSFT']

    print("\n⚠️  WARNING: This is PAPER TRADING")
    print("Set ALPACA_PAPER=False only after thorough testing\n")

    trader.run(symbols)
