# Live Trading Integration Guide

Transform your backtesting platform into a live trading system.

## ⚠️ IMPORTANT DISCLAIMERS

**Before you start:**
- ✋ **Paper trading first**: Always test with paper/sandbox accounts
- 💰 **Risk management**: Start with small amounts you can afford to lose
- 📚 **Understand regulations**: Know trading rules and tax implications
- 🔒 **API security**: Never commit API keys to Git
- ⚖️ **Legal**: This is for educational purposes. Trading involves risk.

---

## Trading Platform Options

### Recommended Platforms for Algo Trading

| Platform | Best For | Commission | Paper Trading | API Quality |
|----------|----------|------------|---------------|-------------|
| **Alpaca** | US stocks, crypto | Free | ✅ Yes | ⭐⭐⭐⭐⭐ |
| **Interactive Brokers** | Professional | Low | ✅ Yes | ⭐⭐⭐⭐ |
| **TD Ameritrade** | US stocks | Free | ✅ Yes | ⭐⭐⭐⭐ |
| **Robinhood** | Casual trading | Free | ❌ No official | ⭐⭐ |
| **Coinbase** | Crypto only | Medium | ✅ Sandbox | ⭐⭐⭐⭐ |
| **Binance** | Crypto | Low | ✅ Testnet | ⭐⭐⭐⭐ |
| **Polygon.io** | Market data | Paid | Data only | ⭐⭐⭐⭐⭐ |

---

## Option 1: Alpaca (RECOMMENDED)

**Why Alpaca?**
- ✅ Free commission-free trading
- ✅ Excellent API documentation
- ✅ Paper trading built-in
- ✅ Real-time market data
- ✅ No minimum deposit
- ✅ Python SDK available

### Setup Alpaca Integration

1. **Create account** at [alpaca.markets](https://alpaca.markets)

2. **Get API credentials**:
   - Dashboard → API Keys
   - Create keys for **Paper Trading** first
   - Copy: API Key ID & Secret Key

3. **Install Alpaca SDK**:

Add to `requirements.txt`:
```
alpaca-trade-api==3.0.2
websocket-client==1.6.4
```

4. **Create Live Trading Module**:

I'll create the integration files for you:


---

## Quick Start: Alpaca Paper Trading

### 1. Install Dependencies

```bash
pip install alpaca-trade-api websocket-client
```

### 2. Set Environment Variables

Create `.env` file:
```bash
ALPACA_API_KEY=your_paper_key_here
ALPACA_SECRET_KEY=your_paper_secret_here
ALPACA_PAPER=true
```

### 3. Test Connection

```python
from live_trading.alpaca_broker import AlpacaBroker

# Connect to paper trading
broker = AlpacaBroker(paper=True)

# Get account info
account = broker.get_account_info()
print(f"Buying Power: ${account['buying_power']:,.2f}")
```

### 4. Run Live Trader

```python
from live_trading.live_trader import LiveTrader
from live_trading.alpaca_broker import AlpacaBroker
from backtest_engine.strategies.moving_average import MovingAverageCrossover

# Setup
broker = AlpacaBroker(paper=True)
strategy = MovingAverageCrossover()
trader = LiveTrader(broker, strategy)

# Run (paper trading)
trader.run(['AAPL', 'GOOGL', 'MSFT'])
```

---

## Option 2: TD Ameritrade

**Setup:**

1. Create account at [tdameritrade.com](https://developer.tdameritrade.com)
2. Register app to get API key
3. Install SDK:

```bash
pip install tda-api
```

4. Authentication (more complex - uses OAuth):

```python
from tda import auth, client

token_path = 'token.json'
api_key = 'YOUR_API_KEY@AMER.OAUTHAP'
redirect_uri = 'https://localhost'

try:
    c = auth.client_from_token_file(token_path, api_key)
except FileNotFoundError:
    from selenium import webdriver
    with webdriver.Chrome() as driver:
        c = auth.client_from_login_flow(
            driver, api_key, redirect_uri, token_path)
```

---

## Option 3: Interactive Brokers

**Best for**: Professional trading, global markets

```bash
pip install ib_insync
```

**Setup:**
1. Download TWS (Trader Workstation) or IB Gateway
2. Enable API in settings (port 7497 for paper, 7496 for live)
3. Connect:

```python
from ib_insync import IB, Stock

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)  # Paper trading

# Place order
contract = Stock('AAPL', 'SMART', 'USD')
order = MarketOrder('BUY', 100)
trade = ib.placeOrder(contract, order)
```

---

## Option 4: Coinbase Pro (Crypto)

**For cryptocurrency trading:**

```bash
pip install cbpro
```

```python
import cbpro

public_client = cbpro.PublicClient()

# Get BTC price
ticker = public_client.get_product_ticker(product_id='BTC-USD')
print(f"Bitcoin: ${ticker['price']}")

# Authenticated (for trading)
auth_client = cbpro.AuthenticatedClient(
    key='YOUR_KEY',
    b64secret='YOUR_SECRET',
    passphrase='YOUR_PASSPHRASE'
)

# Place order
order = auth_client.place_limit_order(
    product_id='BTC-USD',
    side='buy',
    price='30000.00',
    size='0.01'
)
```

---

## Robinhood (Unofficial API)

⚠️ **Warning**: Robinhood has no official API

**Not recommended** but if you must:

```bash
pip install robin-stocks
```

```python
import robin_stocks.robinhood as rh

# Login
rh.login(username='your_email', password='your_password')

# Get positions
positions = rh.build_holdings()

# Buy stock
rh.order_buy_market('AAPL', 1)

# IMPORTANT: Violates ToS, account may be banned
```

**Better alternatives**: Use Alpaca or TD Ameritrade instead.

---

## Adding Live Trading to Your Platform

### 1. Create API Endpoints

Add to `app/routes/live_trading_routes.py`:

```python
from flask import Blueprint, request, jsonify
from live_trading.alpaca_broker import AlpacaBroker
from live_trading.live_trader import LiveTrader

bp = Blueprint('live_trading', __name__, url_prefix='/api/live')

@bp.route('/account', methods=['GET'])
def get_account():
    """Get account information"""
    broker = AlpacaBroker(paper=True)
    account = broker.get_account_info()
    return jsonify(account), 200

@bp.route('/positions', methods=['GET'])
def get_positions():
    """Get current positions"""
    broker = AlpacaBroker(paper=True)
    positions = broker.get_positions()
    return jsonify([p.__dict__ for p in positions]), 200

@bp.route('/order', methods=['POST'])
def place_order():
    """Place an order"""
    data = request.get_json()
    
    broker = AlpacaBroker(paper=True)
    order = broker.place_order(
        symbol=data['symbol'],
        qty=data['quantity'],
        side=data['side']
    )
    return jsonify(order.__dict__), 200
```

### 2. Update main.py

```python
from app.routes import live_trading_routes

app.register_blueprint(live_trading_routes.bp)
```

### 3. Add UI Controls

Update `templates/index.html` to add live trading section.

---

## Risk Management for Live Trading

### Essential Safety Features

```python
class LiveRiskManager:
    """Risk management for live trading"""
    
    def __init__(
        self,
        max_daily_loss: float = 1000,  # Max $1000 loss per day
        max_position_pct: float = 0.10,  # 10% per position
        max_total_exposure: float = 0.50  # 50% total exposure
    ):
        self.max_daily_loss = max_daily_loss
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.daily_pnl = 0
        
    def can_trade(self, broker) -> bool:
        """Check if we can continue trading"""
        # Check daily loss limit
        positions = broker.get_positions()
        total_pnl = sum(p.unrealized_pl for p in positions)
        
        if total_pnl < -self.max_daily_loss:
            print(f"❌ Daily loss limit reached: ${total_pnl:.2f}")
            return False
            
        return True
        
    def validate_order(self, broker, symbol, qty, price):
        """Validate order before placing"""
        account = broker.get_account_info()
        
        # Check position size
        order_value = qty * price
        max_value = account['portfolio_value'] * self.max_position_pct
        
        if order_value > max_value:
            raise ValueError(f"Order too large: ${order_value:.2f} > ${max_value:.2f}")
            
        # Check total exposure
        positions = broker.get_positions()
        total_exposure = sum(p.market_value for p in positions) + order_value
        max_exposure = account['portfolio_value'] * self.max_total_exposure
        
        if total_exposure > max_exposure:
            raise ValueError(f"Total exposure too high")
            
        return True
```

---

## Production Checklist

Before going live with real money:

### Testing Phase (1-2 weeks minimum)

- [ ] Run paper trading for at least 1 week
- [ ] Test all order types (market, limit, stop)
- [ ] Test position entry and exit
- [ ] Monitor during market hours
- [ ] Test error handling (network issues, rejected orders)
- [ ] Verify risk management triggers
- [ ] Test with small positions first

### Security

- [ ] Store API keys in environment variables
- [ ] Never commit keys to Git
- [ ] Use read-only keys for data fetching
- [ ] Enable 2FA on broker account
- [ ] Use secure server for hosting
- [ ] Implement rate limiting
- [ ] Log all trades for audit

### Monitoring

- [ ] Set up alerts for:
  - Large losses
  - Failed orders
  - API connection issues
  - Unusual activity
- [ ] Monitor daily P&L
- [ ] Track strategy performance
- [ ] Review trades regularly

### Legal & Compliance

- [ ] Understand pattern day trader rules (US)
- [ ] Know tax implications
- [ ] Follow broker's terms of service
- [ ] Keep trade records
- [ ] Understand wash sale rules

---

## Going from Paper to Live

### When you're ready (after 2+ weeks of successful paper trading):

1. **Start Small**:
   ```python
   # Use tiny position sizes first
   trader = LiveTrader(
       broker=AlpacaBroker(paper=False),  # LIVE!
       strategy=strategy,
       max_position_size=0.01,  # Only 1% per position
       max_positions=2  # Max 2 positions
   )
   ```

2. **Monitor Closely**:
   - Watch every trade
   - Check multiple times per day
   - Have stop-loss ready

3. **Scale Gradually**:
   - Week 1: 1% position size, 2 positions max
   - Week 2: 2% position size, 3 positions max
   - Week 3+: Increase slowly if profitable

4. **Emergency Stop**:
   ```python
   # Always have a kill switch
   if daily_loss > max_loss:
       broker.close_all_positions()
       trader.stop()
   ```

---

## Common Pitfalls to Avoid

1. ❌ **Over-trading**: Too many trades = high fees
2. ❌ **No stop-loss**: Always have exit plan
3. ❌ **Revenge trading**: Don't chase losses
4. ❌ **Ignoring fees**: They add up quickly
5. ❌ **No testing**: Paper trade first, always
6. ❌ **Too much leverage**: Start conservative
7. ❌ **Poor error handling**: Handle all edge cases
8. ❌ **No logging**: Track everything
9. ❌ **Unrealistic expectations**: Most traders lose money
10. ❌ **Emotional decisions**: Stick to strategy

---

## Cost Analysis

### Trading Costs (annual, assuming $10k account)

| Platform | Commission | Data Fees | Total Est. |
|----------|-----------|-----------|------------|
| Alpaca | $0 | $0 | $0 |
| Robinhood | $0 | $0 | $0 |
| TD Ameritrade | $0 | $0-20/mo | $0-240 |
| Interactive Brokers | $0-1/trade | $10-100/mo | $120-1200 |

**Other costs**:
- Server hosting: $5-50/month
- Market data: $0-100/month (depends on needs)
- Slippage: ~0.1-0.5% per trade
- Spread: Varies by symbol and volume

---

## Resources

### Learning
- [Alpaca Docs](https://alpaca.markets/docs/)
- [QuantConnect Learn](https://www.quantconnect.com/learning/)
- [Investopedia Algo Trading](https://www.investopedia.com/articles/active-trading/101014/basics-algorithmic-trading-concepts-and-examples.asp)

### Communities
- r/algotrading
- QuantConnect Forum
- Elite Trader Forum

### Books
- "Algorithmic Trading" by Ernest Chan
- "Quantitative Trading" by Ernest Chan
- "Trading and Exchanges" by Larry Harris

---

## Next Steps

1. **Open Alpaca paper account** (5 minutes)
2. **Test connection** with provided code
3. **Run backtest** then compare with paper trading
4. **Monitor for 1-2 weeks** 
5. **Gradually go live** (if profitable and confident)

---

## Disclaimer

⚠️ **IMPORTANT**: 

- Trading involves substantial risk of loss
- Past performance ≠ future results
- This is educational software
- Start with paper trading
- Only risk money you can afford to lose
- Consider consulting a financial advisor
- Author is not responsible for trading losses

**You are responsible for your own trading decisions.**

---

Ready to start? Begin with Alpaca paper trading! 📈
