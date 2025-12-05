"""
Alpaca broker integration for live trading
Paper trading by default - switch to live carefully!
"""
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import alpaca_trade_api as tradeapi
from dataclasses import dataclass


@dataclass
class LivePosition:
    """Represents a live trading position"""
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float


@dataclass
class LiveOrder:
    """Represents a live order"""
    id: str
    symbol: str
    qty: float
    side: str  # 'buy' or 'sell'
    type: str  # 'market', 'limit', etc.
    status: str
    filled_qty: float
    filled_avg_price: Optional[float]


class AlpacaBroker:
    """
    Alpaca broker interface for live trading

    IMPORTANT: Uses paper trading by default!
    Set ALPACA_PAPER=False for live trading (be careful!)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: bool = True
    ):
        """
        Initialize Alpaca connection

        Args:
            api_key: Alpaca API key (or set ALPACA_API_KEY env var)
            api_secret: Alpaca secret key (or set ALPACA_SECRET_KEY env var)
            paper: Use paper trading (True recommended for testing)
        """
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_SECRET_KEY')
        self.paper = paper

        if not self.api_key or not self.api_secret:
            raise ValueError(
                "Alpaca API credentials not found. Set ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY environment variables or pass them directly."
            )

        # Initialize Alpaca API
        base_url = 'https://paper-api.alpaca.markets' if paper else 'https://api.alpaca.markets'

        self.api = tradeapi.REST(
            self.api_key,
            self.api_secret,
            base_url,
            api_version='v2'
        )

        # Verify connection
        try:
            account = self.api.get_account()
            mode = "PAPER" if paper else "LIVE"
            print(f"✅ Connected to Alpaca ({mode} trading)")
            print(f"   Account: {account.account_number}")
            print(f"   Buying Power: ${float(account.buying_power):,.2f}")
            print(f"   Cash: ${float(account.cash):,.2f}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Alpaca: {str(e)}")

    def get_account_info(self) -> Dict:
        """Get account information"""
        account = self.api.get_account()

        return {
            'account_number': account.account_number,
            'status': account.status,
            'cash': float(account.cash),
            'buying_power': float(account.buying_power),
            'portfolio_value': float(account.portfolio_value),
            'equity': float(account.equity),
            'pattern_day_trader': account.pattern_day_trader,
            'trading_blocked': account.trading_blocked,
            'transfers_blocked': account.transfers_blocked,
            'account_blocked': account.account_blocked,
            'created_at': account.created_at
        }

    def get_positions(self) -> List[LivePosition]:
        """Get all current positions"""
        positions = self.api.list_positions()

        return [
            LivePosition(
                symbol=pos.symbol,
                quantity=float(pos.qty),
                avg_entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                market_value=float(pos.market_value),
                unrealized_pl=float(pos.unrealized_pl),
                unrealized_plpc=float(pos.unrealized_plpc)
            )
            for pos in positions
        ]

    def get_position(self, symbol: str) -> Optional[LivePosition]:
        """Get position for specific symbol"""
        try:
            pos = self.api.get_position(symbol)
            return LivePosition(
                symbol=pos.symbol,
                quantity=float(pos.qty),
                avg_entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                market_value=float(pos.market_value),
                unrealized_pl=float(pos.unrealized_pl),
                unrealized_plpc=float(pos.unrealized_plpc)
            )
        except Exception:
            return None

    def place_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> LiveOrder:
        """
        Place an order

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            qty: Quantity to trade
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', 'stop', 'stop_limit'
            time_in_force: 'day', 'gtc', 'ioc', 'fok'
            limit_price: Limit price for limit orders
            stop_price: Stop price for stop orders
        """
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price,
                stop_price=stop_price
            )

            return LiveOrder(
                id=order.id,
                symbol=order.symbol,
                qty=float(order.qty),
                side=order.side,
                type=order.type,
                status=order.status,
                filled_qty=float(order.filled_qty) if order.filled_qty else 0,
                filled_avg_price=float(order.filled_avg_price) if order.filled_avg_price else None
            )
        except Exception as e:
            raise Exception(f"Order failed: {str(e)}")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        try:
            self.api.cancel_order(order_id)
            return True
        except Exception as e:
            print(f"Failed to cancel order {order_id}: {str(e)}")
            return False

    def get_orders(self, status: str = 'open') -> List[LiveOrder]:
        """
        Get orders

        Args:
            status: 'open', 'closed', 'all'
        """
        orders = self.api.list_orders(status=status)

        return [
            LiveOrder(
                id=order.id,
                symbol=order.symbol,
                qty=float(order.qty),
                side=order.side,
                type=order.type,
                status=order.status,
                filled_qty=float(order.filled_qty) if order.filled_qty else 0,
                filled_avg_price=float(order.filled_avg_price) if order.filled_avg_price else None
            )
            for order in orders
        ]

    def close_position(self, symbol: str) -> bool:
        """Close entire position for a symbol"""
        try:
            self.api.close_position(symbol)
            return True
        except Exception as e:
            print(f"Failed to close position for {symbol}: {str(e)}")
            return False

    def close_all_positions(self) -> bool:
        """Close all positions"""
        try:
            self.api.close_all_positions()
            return True
        except Exception as e:
            print(f"Failed to close all positions: {str(e)}")
            return False

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = '1Day',
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get historical market data

        Args:
            symbol: Stock symbol
            timeframe: '1Min', '5Min', '15Min', '1Hour', '1Day'
            start: Start date
            end: End date
            limit: Number of bars to fetch
        """
        if not start:
            start = datetime.now() - timedelta(days=30)
        if not end:
            end = datetime.now()

        bars = self.api.get_bars(
            symbol,
            timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
            limit=limit
        ).df

        return [
            {
                'timestamp': index,
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume']
            }
            for index, row in bars.iterrows()
        ]

    def get_latest_quote(self, symbol: str) -> Dict:
        """Get latest quote for symbol"""
        quote = self.api.get_latest_quote(symbol)

        return {
            'symbol': symbol,
            'bid_price': float(quote.bp),
            'bid_size': float(quote.bs),
            'ask_price': float(quote.ap),
            'ask_size': float(quote.as_),
            'timestamp': quote.t
        }

    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        clock = self.api.get_clock()
        return clock.is_open


# Example usage
if __name__ == '__main__':
    # ALWAYS USE PAPER TRADING FOR TESTING
    broker = AlpacaBroker(paper=True)

    # Get account info
    account = broker.get_account_info()
    print(f"\nAccount Info:")
    print(f"Portfolio Value: ${account['portfolio_value']:,.2f}")
    print(f"Buying Power: ${account['buying_power']:,.2f}")

    # Check if market is open
    print(f"\nMarket Open: {broker.is_market_open()}")

    # Get current positions
    positions = broker.get_positions()
    print(f"\nCurrent Positions: {len(positions)}")
    for pos in positions:
        print(f"  {pos.symbol}: {pos.quantity} shares @ ${pos.avg_entry_price:.2f}")
        print(f"    Current: ${pos.current_price:.2f} | P&L: ${pos.unrealized_pl:.2f}")

    # Get latest quote
    try:
        quote = broker.get_latest_quote('AAPL')
        print(f"\nAAPL Quote:")
        print(f"  Bid: ${quote['bid_price']:.2f} x {quote['bid_size']}")
        print(f"  Ask: ${quote['ask_price']:.2f} x {quote['ask_size']}")
    except Exception as e:
        print(f"Could not get quote: {e}")
