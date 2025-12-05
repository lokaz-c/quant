# Quick Start Guide

Get the Quant Portfolio Simulator up and running in 3 minutes.

## Prerequisites

- Docker
- Docker Compose

## Setup (One Command)

```bash
make setup
```

Or manually:

```bash
# 1. Build and start services
docker-compose up --build -d

# 2. Generate sample data
docker-compose exec web python backtest_engine/data_loader.py
```

## Access the Application

- **Web UI**: http://localhost:5000
- **API**: http://localhost:5000/api/
- **Health Check**: http://localhost:5000/health

## Run Your First Backtest

### Option 1: Using the Web UI

1. Open http://localhost:5000
2. Select a strategy (e.g., "Moving Average Crossover")
3. Select a risk profile (e.g., "Conservative")
4. Set date range (default: 2022-01-01 to 2023-12-31)
5. Enter initial capital ($100,000)
6. Add symbols (e.g., AAPL, GOOGL, MSFT)
7. Click "Run Backtest"

### Option 2: Using the API

```bash
curl -X POST http://localhost:5000/api/backtest/ \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "Moving Average Crossover",
    "risk_config_name": "Conservative",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": ["AAPL", "GOOGL", "MSFT"]
  }'
```

### Option 3: Run Example Script

```bash
docker-compose exec web python run_example.py
```

This runs a comparison between baseline (no risk management) and risk-managed backtests.

## Understanding the Results

After running a backtest, you'll see metrics like:

- **Total Return**: Overall percentage gain/loss
- **CAGR**: Annualized return rate
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted returns (higher is better)
- **Win Rate**: Percentage of profitable trades
- **Number of Trades**: Total trades executed

## Key Features to Try

### 1. Compare Risk Configurations

Run the same strategy with different risk profiles:
- No Risk Management (baseline)
- Conservative
- Moderate
- Aggressive

Compare the max drawdown improvement (~3% with risk management).

### 2. Test Multiple Strategies

Try all three built-in strategies:
- Moving Average Crossover
- RSI Mean Reversion
- Trend Following

### 3. Analyze Market Regimes

Run backtests across different market conditions:

```bash
curl -X POST http://localhost:5000/api/backtest/regime-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "RSI Mean Reversion",
    "risk_config_name": "Moderate",
    "initial_capital": 100000,
    "symbols": ["AAPL", "GOOGL"]
  }'
```

## Useful Commands

```bash
# View logs
docker-compose logs -f web

# Run tests
docker-compose exec web pytest

# Access database
docker-compose exec db psql -U quant_user -d quant_db

# Restart services
docker-compose restart

# Stop everything
docker-compose down
```

## Common Issues

### "No data available for backtesting"

Generate sample data:
```bash
docker-compose exec web python backtest_engine/data_loader.py
```

### Database connection failed

Restart services:
```bash
docker-compose restart
```

### Port 5000 already in use

Change the port in `docker-compose.yml`:
```yaml
ports:
  - "8080:5000"  # Use port 8080 instead
```

## Next Steps

1. Read the full [README.md](README.md) for detailed documentation
2. Explore the API endpoints
3. Try creating your own custom strategy
4. Experiment with different risk configurations

## Getting Help

- Check the [README.md](README.md) for full documentation
- Run `make help` to see all available commands
- Review test files in `tests/` for usage examples

---

**You're all set! Happy backtesting!**
