# Getting Started Guide

Your complete guide to deploying and using the Quant Portfolio Simulator.

## Table of Contents

1. [Local Development](#local-development)
2. [Deploy to Cloud](#deploy-to-cloud)
3. [Add Live Trading](#add-live-trading)
4. [Next Steps](#next-steps)

---

## Local Development

### Run Locally (Docker - Recommended)

```bash
# Start everything
docker-compose up --build

# Access the app
open http://localhost:5000

# Run tests
docker-compose exec web pytest

# View logs
docker-compose logs -f web
```

### Run Locally (Without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Setup PostgreSQL
createdb quant_db
psql quant_db < db/init.sql

# Set environment
export DATABASE_URL=postgresql://user:pass@localhost:5432/quant_db

# Generate sample data
python backtest_engine/data_loader.py

# Run app
python app/main.py
```

---

## Deploy to Cloud

### Option 1: Render.com (Easiest - FREE)

**Step-by-step:**

1. **Sign up** at [render.com](https://render.com)

2. **Create Database**:
   - Click "New +" → "PostgreSQL"
   - Name: `quant-db`
   - Click "Create Database"
   - Copy the **Internal Database URL**

3. **Create Web Service**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repository: `lokaz-c/quant`
   - Name: `quant-portfolio-simulator`
   - Environment: **Docker**
   - Add Environment Variable:
     - `DATABASE_URL` = [paste the URL from step 2]
   - Click "Create Web Service"

4. **Wait for deployment** (5-10 minutes)

5. **Your app is live!**
   - URL: `https://quant-portfolio-simulator.onrender.com`
   - Add to your resume and LinkedIn

**Post-deployment:**

```bash
# Generate sample data (via Render shell)
# In Render dashboard: Shell tab
python backtest_engine/data_loader.py
```

### Option 2: Railway.app (Easy - FREE Trial)

1. Sign up at [railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select `lokaz-c/quant`
4. Click "+ New" → "Database" → "Add PostgreSQL"
5. In web service settings, add environment variable:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
6. Generate domain in Settings → Networking

### Option 3: Heroku (Paid - $7/month)

```bash
# Install Heroku CLI
brew install heroku

# Login and create app
heroku login
heroku create quant-portfolio-sim

# Add PostgreSQL
heroku addons:create heroku-postgresql:mini

# Deploy
git push heroku main

# Initialize
heroku run python backtest_engine/data_loader.py
heroku open
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for more options (AWS, Google Cloud, DigitalOcean).

---

## Add Live Trading

### ⚠️ Start with Paper Trading ONLY

**Never risk real money until you've tested thoroughly!**

### Setup Alpaca (Recommended)

1. **Create FREE account** at [alpaca.markets](https://alpaca.markets)

2. **Get API Keys**:
   - Dashboard → API Keys
   - Create **Paper Trading** keys (not live!)
   - Copy both keys

3. **Install dependencies**:

```bash
pip install alpaca-trade-api websocket-client
```

4. **Create `.env` file**:

```bash
ALPACA_API_KEY=your_paper_key_here
ALPACA_SECRET_KEY=your_paper_secret_here
ALPACA_PAPER=true
```

5. **Test connection**:

```python
from live_trading.alpaca_broker import AlpacaBroker

broker = AlpacaBroker(paper=True)
account = broker.get_account_info()
print(f"Buying Power: ${account['buying_power']:,.2f}")
```

6. **Run paper trading**:

```python
from live_trading.live_trader import LiveTrader
from live_trading.alpaca_broker import AlpacaBroker
from backtest_engine.strategies.moving_average import MovingAverageCrossover

# Setup
broker = AlpacaBroker(paper=True)  # PAPER mode!
strategy = MovingAverageCrossover()
trader = LiveTrader(broker, strategy, max_position_size=0.10)

# Run (Ctrl+C to stop)
trader.run(['AAPL', 'GOOGL', 'MSFT'])
```

### Paper Trading Timeline

**Week 1-2:**
- Run strategies in paper mode
- Monitor daily
- Check if profitable
- Verify no bugs or errors

**Week 3+:**
- If consistently profitable, consider tiny live amounts
- Start with only $100-500
- Use 1-2% position sizes
- Monitor constantly

**IMPORTANT:** Most algorithmic traders lose money. Only trade what you can afford to lose.

See [LIVE_TRADING.md](LIVE_TRADING.md) for complete guide.

---

## Next Steps

### For Portfolio/Resume

1. **Deploy to cloud** (Render is free and easy)
2. **Take screenshots** of the web UI
3. **Add to resume**:
   > "Deployed quantitative trading platform processing 30,000+ data points with risk management. Live at: [your-url]"
4. **Share on LinkedIn** with link and screenshots
5. **Add to GitHub README** badge: ![Live Demo](https://img.shields.io/badge/demo-live-success)

### For Learning

1. **Read the code** to understand architecture
2. **Run backtests** with different strategies
3. **Compare risk configurations** (baseline vs risk-managed)
4. **Try paper trading** with Alpaca
5. **Modify strategies** to create your own
6. **Add new features**:
   - More technical indicators
   - Machine learning strategies
   - Options trading support
   - Sentiment analysis integration

### For Trading (Advanced)

1. **Backtest thoroughly** (weeks of historical data)
2. **Paper trade** for 2+ weeks minimum
3. **Start tiny** ($100-500) if going live
4. **Monitor constantly**
5. **Keep detailed logs**
6. **Understand risks** - most traders lose money
7. **Know regulations** (PDT rule, taxes, etc.)

---

## Common Issues

### "No data available for backtesting"

```bash
# Generate sample data
docker-compose exec web python backtest_engine/data_loader.py

# Or locally:
python backtest_engine/data_loader.py
```

### Database connection failed

```bash
# Check DATABASE_URL is set
echo $DATABASE_URL

# Restart services
docker-compose restart
```

### Port already in use

```bash
# Change port in docker-compose.yml
ports:
  - "8080:5000"  # Use 8080 instead
```

### Alpaca connection failed

```bash
# Verify API keys are correct
# Make sure you're using PAPER trading keys
# Check .env file exists with correct values
```

---

## Resources

### Documentation
- [README.md](README.md) - Complete project documentation
- [QUICKSTART.md](QUICKSTART.md) - Local setup guide
- [DEPLOYMENT.md](DEPLOYMENT.md) - Cloud deployment guide
- [LIVE_TRADING.md](LIVE_TRADING.md) - Trading integration guide
- [API_EXAMPLES.md](API_EXAMPLES.md) - API usage examples
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Technical overview

### External Resources
- [Alpaca Docs](https://alpaca.markets/docs/) - Trading API documentation
- [Flask Docs](https://flask.palletsprojects.com/) - Web framework
- [Docker Docs](https://docs.docker.com/) - Containerization
- [PostgreSQL Docs](https://www.postgresql.org/docs/) - Database

### Communities
- [r/algotrading](https://reddit.com/r/algotrading) - Algorithmic trading
- [QuantConnect Forum](https://www.quantconnect.com/forum/) - Quant community
- [Alpaca Community](https://forum.alpaca.markets/) - Alpaca users

---

## Project Structure

```
Quant/
├── GETTING_STARTED.md        ← You are here
├── README.md                 Full documentation
├── DEPLOYMENT.md             Cloud deployment guide
├── LIVE_TRADING.md           Trading integration
│
├── app/                      Flask application
│   ├── main.py              API entry point
│   ├── models/              Database models
│   ├── routes/              API endpoints
│   └── services/            Business logic
│
├── backtest_engine/          Core backtesting
│   ├── backtester.py        Main engine
│   ├── strategies/          Trading strategies
│   ├── risk.py              Risk management
│   └── metrics.py           Performance analysis
│
├── live_trading/             Live trading (NEW!)
│   ├── alpaca_broker.py     Alpaca integration
│   └── live_trader.py       Real-time engine
│
├── templates/                Web UI
├── tests/                    Unit tests
└── data/                     Market data (32k+ points)
```

---

## Quick Commands

```bash
# Local development
docker-compose up --build           # Start app
docker-compose exec web pytest      # Run tests
python run_example.py               # Example backtest

# Deployment
# See DEPLOYMENT.md for platform-specific commands

# Live trading (paper mode)
python live_trading/alpaca_broker.py    # Test connection
python live_trading/live_trader.py      # Run trader

# Documentation
cat README.md              # Full docs
cat DEPLOYMENT.md          # Deploy guide
cat LIVE_TRADING.md        # Trading guide
```

---

## Support

- **Issues**: Open an issue on [GitHub](https://github.com/lokaz-c/quant/issues)
- **Questions**: Check documentation first
- **Bugs**: Include error messages and steps to reproduce

---

## License & Disclaimer

This is educational software for portfolio demonstration.

**Trading Disclaimer:**
- Trading involves substantial risk
- Past performance ≠ future results
- Only trade what you can afford to lose
- Author is not responsible for trading losses
- This is not financial advice

---

**Ready to get started? Pick your path:**

- 🚀 [Deploy to cloud](#deploy-to-cloud) (5 minutes)
- 💻 [Run locally](#local-development) (instant)
- 📈 [Try paper trading](#add-live-trading) (educational)

---

Built with Python, Flask, PostgreSQL, Docker
