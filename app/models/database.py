"""
Database models and ORM setup using SQLAlchemy.

The schema is owned by the Alembic migrations in migrations/; these models
must match the head revision (tests/test_migrations.py checks this). Create or
upgrade a database with `alembic upgrade head`, or `python init_db.py`, which
also seeds it.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index,
    Integer, Numeric, String, Text, create_engine, text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

# Use SQLite for local development, PostgreSQL for production
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///quant.db')


def make_engine(url: str):
    if url.startswith('sqlite'):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Column types. The reasoning is in docs/database.md.
MONEY = Numeric(18, 4)       # dollars: capital, equity, cash, P&L
PRICE = Numeric(18, 4)       # per-share prices
QUANTITY = Numeric(18, 9)    # shares; fractional, Alpaca accepts up to 9 decimals
JSONB = JSON().with_variant(postgresql.JSONB(), 'postgresql')
NOW = text('CURRENT_TIMESTAMP')


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """
    TIMESTAMPTZ on PostgreSQL; always gives back an aware UTC datetime.

    Naive datetimes (the engine's bar timestamps) are taken to be UTC when
    written. SQLite has no time zone type and returns naive values, which are
    UTC because that is all this type writes.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if hasattr(value, 'to_pydatetime'):  # pandas.Timestamp from the engine
            value = value.to_pydatetime()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# Values the code writes; the CHECK constraints in migration 0002 match these
RUN_STATUSES = ('pending', 'running', 'completed', 'failed')
TRADE_SIDES = ('buy', 'sell')
TRADE_STATUSES = ('open', 'closed')


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Strategy(Base):
    __tablename__ = 'strategies'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    parameters = Column(JSONB)
    created_at = Column(UTCDateTime, default=utcnow, server_default=NOW)
    updated_at = Column(UTCDateTime, default=utcnow, onupdate=utcnow, server_default=NOW)

    backtest_runs = relationship('BacktestRun', back_populates='strategy')


class RiskConfig(Base):
    __tablename__ = 'risk_configs'

    # Fractions of equity (0.15 = 15%): ratios, so double precision
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    max_position_size = Column(Float)
    max_portfolio_exposure = Column(Float)
    stop_loss_pct = Column(Float)
    take_profit_pct = Column(Float)
    max_drawdown_pct = Column(Float)
    enabled = Column(Boolean, default=True, server_default=text('true'))
    created_at = Column(UTCDateTime, default=utcnow, server_default=NOW)

    backtest_runs = relationship('BacktestRun', back_populates='risk_config')


class BacktestRun(Base):
    __tablename__ = 'backtest_runs'
    __table_args__ = (
        CheckConstraint(_in('status', RUN_STATUSES), name='ck_backtest_runs_status'),
        Index('idx_backtest_runs_strategy', 'strategy_id'),
        Index('idx_backtest_runs_dates', 'start_date', 'end_date'),
    )

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('strategies.id'))
    risk_config_id = Column(Integer, ForeignKey('risk_configs.id'))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_capital = Column(MONEY, nullable=False)
    symbols = Column(JSONB)
    market_regime = Column(String(50))
    status = Column(String(50), default='pending', server_default='pending')
    created_at = Column(UTCDateTime, default=utcnow, server_default=NOW)
    completed_at = Column(UTCDateTime)

    strategy = relationship('Strategy', back_populates='backtest_runs')
    risk_config = relationship('RiskConfig', back_populates='backtest_runs')
    metrics = relationship('BacktestMetrics', back_populates='backtest_run', cascade='all, delete-orphan')
    equity_curve = relationship('EquityCurve', back_populates='backtest_run', cascade='all, delete-orphan')
    trades = relationship('Trade', back_populates='backtest_run', cascade='all, delete-orphan')


class BacktestMetrics(Base):
    __tablename__ = 'backtest_metrics'

    # Percentages and ratios stay double precision; dollar amounts are MONEY
    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    total_return = Column(Float)
    cagr = Column(Float)
    max_drawdown = Column(Float)
    volatility = Column(Float)
    sharpe_ratio = Column(Float)
    win_rate = Column(Float)
    avg_win = Column(MONEY)
    avg_loss = Column(MONEY)
    num_trades = Column(Integer)
    final_equity = Column(MONEY)
    created_at = Column(UTCDateTime, default=utcnow, server_default=NOW)

    backtest_run = relationship('BacktestRun', back_populates='metrics')


class EquityCurve(Base):
    __tablename__ = 'equity_curve'
    __table_args__ = (
        # One point per bar per run; also the access path for the SQL metrics
        Index('ix_equity_curve_run_timestamp', 'backtest_run_id', 'timestamp', unique=True),
    )

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    timestamp = Column(UTCDateTime, nullable=False)
    equity = Column(MONEY, nullable=False)
    cash = Column(MONEY)
    positions_value = Column(MONEY)

    backtest_run = relationship('BacktestRun', back_populates='equity_curve')


class Trade(Base):
    __tablename__ = 'trades'
    __table_args__ = (
        CheckConstraint(_in('side', TRADE_SIDES), name='ck_trades_side'),
        CheckConstraint(_in('status', TRADE_STATUSES), name='ck_trades_status'),
        Index('idx_trades_run', 'backtest_run_id'),
    )

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey('backtest_runs.id', ondelete='CASCADE'))
    symbol = Column(String(20), nullable=False)
    entry_date = Column(UTCDateTime, nullable=False)
    exit_date = Column(UTCDateTime)
    entry_price = Column(PRICE, nullable=False)
    exit_price = Column(PRICE)
    quantity = Column(QUANTITY, nullable=False)
    side = Column(String(10), nullable=False)
    pnl = Column(MONEY)
    pnl_pct = Column(Float)
    status = Column(String(20), default='open', server_default='open')

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
