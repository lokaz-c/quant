-- PostgreSQL schema, run by the postgres container on first start.
-- Must match app/models/database.py. Seed rows come from config/*.json via init_db.py.

CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    parameters JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS risk_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    max_position_size FLOAT,
    max_portfolio_exposure FLOAT,
    stop_loss_pct FLOAT,
    take_profit_pct FLOAT,
    max_drawdown_pct FLOAT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id),
    risk_config_id INTEGER REFERENCES risk_configs(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital FLOAT NOT NULL,
    symbols JSONB,
    market_regime VARCHAR(50),
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_metrics (
    id SERIAL PRIMARY KEY,
    backtest_run_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
    total_return FLOAT,
    cagr FLOAT,
    max_drawdown FLOAT,
    volatility FLOAT,
    sharpe_ratio FLOAT,
    win_rate FLOAT,
    avg_win FLOAT,
    avg_loss FLOAT,
    num_trades INTEGER,
    final_equity FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_curve (
    id SERIAL PRIMARY KEY,
    backtest_run_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    equity FLOAT NOT NULL,
    cash FLOAT,
    positions_value FLOAT
);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    backtest_run_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    entry_date TIMESTAMP NOT NULL,
    exit_date TIMESTAMP,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    quantity FLOAT NOT NULL,
    side VARCHAR(10) NOT NULL,
    pnl FLOAT,
    pnl_pct FLOAT,
    status VARCHAR(20) DEFAULT 'open'
);

-- Create indexes for performance
CREATE INDEX idx_backtest_runs_strategy ON backtest_runs(strategy_id);
CREATE INDEX idx_backtest_runs_dates ON backtest_runs(start_date, end_date);
CREATE INDEX idx_equity_curve_run ON equity_curve(backtest_run_id);
CREATE INDEX idx_trades_run ON trades(backtest_run_id);
