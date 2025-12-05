"""
Database models and ORM setup using SQLAlchemy
"""
import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from contextlib import contextmanager

# Use SQLite for local development, PostgreSQL for production
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///quant.db')

# SQLite doesn't support some PostgreSQL features, so we adjust
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Strategy(Base):
    __tablename__ = 'strategies'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    parameters = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    backtest_runs = relationship('BacktestRun', back_populates='strategy')


class RiskConfig(Base):
    __tablename__ = 'risk_configs'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    max_position_size = Column(Float)
    max_portfolio_exposure = Column(Float)
    stop_loss_pct = Column(Float)
    take_profit_pct = Column(Float)
    max_drawdown_pct = Column(Float)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    backtest_runs = relationship('BacktestRun', back_populates='risk_config')


class BacktestRun(Base):
    __tablename__ = 'backtest_runs'

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    risk_config_id = Column(Integer, ForeignKey('risk_configs.id'))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_capital = Column(Float, nullable=False)
    symbols = Column(JSON)  # Store as JSON array for SQLite compatibility
    market_regime = Column(String(50))
    status = Column(String(50), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    strategy = relationship('Strategy', back_populates='backtest_runs')
    risk_config = relationship('RiskConfig', back_populates='backtest_runs')
    metrics = relationship('BacktestMetrics', back_populates='backtest_run', cascade='all, delete-orphan')
    equity_curve = relationship('EquityCurve', back_populates='backtest_run', cascade='all, delete-orphan')
    trades = relationship('Trade', back_populates='backtest_run', cascade='all, delete-orphan')


class BacktestMetrics(Base):
    __tablename__ = 'backtest_metrics'

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    total_return = Column(Float)
    cagr = Column(Float)
    max_drawdown = Column(Float)
    volatility = Column(Float)
    sharpe_ratio = Column(Float)
    win_rate = Column(Float)
    avg_win = Column(Float)
    avg_loss = Column(Float)
    num_trades = Column(Integer)
    final_equity = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    backtest_run = relationship('BacktestRun', back_populates='metrics')


class EquityCurve(Base):
    __tablename__ = 'equity_curve'

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    timestamp = Column(DateTime, nullable=False)
    equity = Column(Float, nullable=False)
    cash = Column(Float)
    positions_value = Column(Float)

    backtest_run = relationship('BacktestRun', back_populates='equity_curve')


class Trade(Base):
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    symbol = Column(String(20), nullable=False)
    entry_date = Column(DateTime, nullable=False)
    exit_date = Column(DateTime)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    quantity = Column(Float, nullable=False)
    side = Column(String(10), nullable=False)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    status = Column(String(20), default='open')

    backtest_run = relationship('BacktestRun', back_populates='trades')


@contextmanager
def get_db():
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully")
