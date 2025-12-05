# API Examples

Complete examples for using the Quant Portfolio Simulator API.

## Base URL

```
http://localhost:5000
```

## Authentication

No authentication required (for demo purposes).

---

## Strategy Endpoints

### List All Strategies

```bash
curl http://localhost:5000/api/strategies/
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Moving Average Crossover",
    "description": "Simple moving average crossover strategy",
    "parameters": {
      "fast_period": 20,
      "slow_period": 50
    }
  },
  {
    "id": 2,
    "name": "RSI Mean Reversion",
    "description": "RSI-based mean reversion strategy",
    "parameters": {
      "rsi_period": 14,
      "oversold": 30,
      "overbought": 70
    }
  }
]
```

### Get Strategy Details

```bash
curl http://localhost:5000/api/strategies/1
```

### Create Custom Strategy

```bash
curl -X POST http://localhost:5000/api/strategies/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Custom Strategy",
    "description": "Custom strategy description",
    "parameters": {
      "custom_param": 42
    }
  }'
```

---

## Risk Configuration Endpoints

### List All Risk Configurations

```bash
curl http://localhost:5000/api/risk-configs/
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "No Risk Management",
    "max_position_size": 1.0,
    "max_portfolio_exposure": 1.0,
    "stop_loss_pct": null,
    "take_profit_pct": null,
    "max_drawdown_pct": null,
    "enabled": false
  },
  {
    "id": 2,
    "name": "Conservative",
    "max_position_size": 0.15,
    "max_portfolio_exposure": 0.70,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.15,
    "max_drawdown_pct": 0.15,
    "enabled": true
  }
]
```

### Get Risk Configuration Details

```bash
curl http://localhost:5000/api/risk-configs/2
```

---

## Backtest Endpoints

### Run a Basic Backtest

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

**Response:**
```json
{
  "backtest_id": 1,
  "status": "completed",
  "metrics": {
    "total_return": 15.42,
    "cagr": 14.87,
    "max_drawdown": 12.34,
    "volatility": 18.32,
    "sharpe_ratio": 1.45,
    "win_rate": 58.33,
    "avg_win": 543.21,
    "avg_loss": -287.45,
    "num_trades": 24,
    "final_equity": 115420.00,
    "profit_factor": 2.15,
    "max_consecutive_wins": 5,
    "max_consecutive_losses": 3
  },
  "summary": {
    "equity": 115420.00,
    "cash": 45230.50,
    "positions": 0,
    "total_return": 15.42
  }
}
```

### Run Backtest with All Symbols (No Filter)

```bash
curl -X POST http://localhost:5000/api/backtest/ \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "RSI Mean Reversion",
    "risk_config_name": "Moderate",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": null
  }'
```

### Run Backtest Without Risk Management (Baseline)

```bash
curl -X POST http://localhost:5000/api/backtest/ \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "Trend Following",
    "risk_config_name": "No Risk Management",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": ["AAPL", "TSLA"]
  }'
```

### Get Backtest Results

```bash
curl http://localhost:5000/api/backtest/1
```

**Response:**
```json
{
  "id": 1,
  "strategy": "Moving Average Crossover",
  "risk_config": "Conservative",
  "start_date": "2022-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 100000.0,
  "symbols": ["AAPL", "GOOGL", "MSFT"],
  "market_regime": null,
  "status": "completed",
  "created_at": "2024-12-04T23:00:00",
  "metrics": {
    "total_return": 15.42,
    "cagr": 14.87,
    "max_drawdown": 12.34,
    "volatility": 18.32,
    "sharpe_ratio": 1.45,
    "win_rate": 58.33,
    "avg_win": 543.21,
    "avg_loss": -287.45,
    "num_trades": 24,
    "final_equity": 115420.00
  },
  "equity_curve": [
    {
      "timestamp": "2022-01-03T00:00:00",
      "equity": 100000.0,
      "cash": 100000.0,
      "positions_value": 0.0
    },
    {
      "timestamp": "2022-01-04T00:00:00",
      "equity": 100250.0,
      "cash": 50000.0,
      "positions_value": 50250.0
    }
    // ... more points
  ],
  "trades": [
    {
      "symbol": "AAPL",
      "entry_date": "2022-01-05T00:00:00",
      "exit_date": "2022-02-15T00:00:00",
      "entry_price": 150.0,
      "exit_price": 160.0,
      "quantity": 100.0,
      "side": "sell",
      "pnl": 1000.0,
      "pnl_pct": 6.67,
      "status": "closed"
    }
    // ... more trades
  ]
}
```

### List Recent Backtests

```bash
curl "http://localhost:5000/api/backtest/list?limit=10"
```

### List Backtests for Specific Strategy

```bash
curl "http://localhost:5000/api/backtest/list?strategy_id=1&limit=20"
```

---

## Comparison & Analysis

### Compare Two Backtests

```bash
curl -X POST http://localhost:5000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{
    "baseline_id": 1,
    "comparison_id": 2
  }'
```

**Response:**
```json
{
  "baseline": {
    "id": 1,
    "strategy": "Moving Average Crossover",
    "risk_config": "No Risk Management",
    "metrics": {
      "total_return": 18.50,
      "max_drawdown": 15.20,
      "sharpe_ratio": 1.20
    }
  },
  "comparison": {
    "id": 2,
    "strategy": "Moving Average Crossover",
    "risk_config": "Conservative",
    "metrics": {
      "total_return": 16.30,
      "max_drawdown": 12.10,
      "sharpe_ratio": 1.45
    }
  },
  "differences": {
    "total_return_diff": -2.20,
    "max_drawdown_diff": -3.10,
    "sharpe_ratio_diff": 0.25,
    "drawdown_improvement_pct": 20.39
  }
}
```

### Multi-Regime Analysis

```bash
curl -X POST http://localhost:5000/api/backtest/regime-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "RSI Mean Reversion",
    "risk_config_name": "Moderate",
    "initial_capital": 100000,
    "symbols": ["AAPL", "GOOGL", "MSFT", "AMZN"]
  }'
```

**Response:**
```json
{
  "strategy": "RSI Mean Reversion",
  "risk_config": "Moderate",
  "regimes": [
    {
      "regime": "Bullish",
      "backtest_id": 5,
      "metrics": {
        "total_return": 12.30,
        "max_drawdown": 8.50,
        "sharpe_ratio": 1.65,
        "win_rate": 62.5
      }
    },
    {
      "regime": "Bearish",
      "backtest_id": 6,
      "metrics": {
        "total_return": -3.20,
        "max_drawdown": 11.20,
        "sharpe_ratio": 0.85,
        "win_rate": 45.0
      }
    },
    {
      "regime": "Sideways",
      "backtest_id": 7,
      "metrics": {
        "total_return": 5.60,
        "max_drawdown": 6.30,
        "sharpe_ratio": 1.40,
        "win_rate": 58.3
      }
    }
  ]
}
```

---

## Python Examples

### Using requests library

```python
import requests
import json

# Base URL
base_url = "http://localhost:5000/api"

# Run a backtest
backtest_params = {
    "strategy_name": "Moving Average Crossover",
    "risk_config_name": "Conservative",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": ["AAPL", "GOOGL", "MSFT"]
}

response = requests.post(
    f"{base_url}/backtest/",
    json=backtest_params
)

result = response.json()
print(f"Backtest ID: {result['backtest_id']}")
print(f"Total Return: {result['metrics']['total_return']:.2f}%")
print(f"Max Drawdown: {result['metrics']['max_drawdown']:.2f}%")

# Get full results
backtest_id = result['backtest_id']
full_results = requests.get(f"{base_url}/backtest/{backtest_id}").json()

# Print equity curve
print("\nEquity Curve (first 5 points):")
for point in full_results['equity_curve'][:5]:
    print(f"{point['timestamp']}: ${point['equity']:,.2f}")
```

### Compare strategies

```python
import requests

base_url = "http://localhost:5000/api"

# Run baseline
baseline = requests.post(f"{base_url}/backtest/", json={
    "strategy_name": "RSI Mean Reversion",
    "risk_config_name": "No Risk Management",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": ["AAPL"]
}).json()

# Run with risk management
risk_managed = requests.post(f"{base_url}/backtest/", json={
    "strategy_name": "RSI Mean Reversion",
    "risk_config_name": "Conservative",
    "start_date": "2022-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 100000,
    "symbols": ["AAPL"]
}).json()

# Compare
comparison = requests.post(f"{base_url}/backtest/compare", json={
    "baseline_id": baseline['backtest_id'],
    "comparison_id": risk_managed['backtest_id']
}).json()

print(f"Drawdown Improvement: {comparison['differences']['drawdown_improvement_pct']:.2f}%")
```

---

## Error Responses

### 400 Bad Request

```json
{
  "error": "Missing required field: strategy_name"
}
```

### 404 Not Found

```json
{
  "error": "Backtest not found"
}
```

### 500 Internal Server Error

```json
{
  "error": "Strategy not found: Invalid Strategy Name"
}
```

---

## Health Check

```bash
curl http://localhost:5000/health
```

**Response:**
```json
{
  "status": "healthy"
}
```

---

## Tips

1. **Always check strategy names**: Use `GET /api/strategies/` to see available strategies
2. **Risk config names are case-sensitive**: "Conservative" not "conservative"
3. **Date format**: Use "YYYY-MM-DD" format
4. **Symbols array**: Can be null to use all available symbols
5. **Initial capital**: Must be at least 1000

---

For more examples, see `run_example.py` in the project root.
