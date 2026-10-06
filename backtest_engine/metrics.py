"""
Performance metrics calculator
Computes various trading performance metrics
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Mapping, Optional, Sequence
from datetime import datetime


class PerformanceMetrics:
    """Calculate and store performance metrics"""

    def __init__(self, equity_curve: List[Dict], trades: List[Dict], initial_capital: float):
        self.equity_curve = equity_curve
        self.trades = trades
        self.initial_capital = initial_capital

        # Convert to DataFrames for easier calculation
        self.equity_df = pd.DataFrame(equity_curve)
        if len(self.equity_df) > 0:
            self.equity_df['timestamp'] = pd.to_datetime(self.equity_df['timestamp'])
            # Values read back from NUMERIC columns are Decimal, and pct_change
            # on Decimals raises TypeError (float NaN - Decimal)
            self.equity_df['equity'] = self.equity_df['equity'].astype(float)

        self.trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
        if 'pnl' in self.trades_df:
            self.trades_df['pnl'] = self.trades_df['pnl'].astype(float)

    def calculate_all(self) -> Dict:
        """Calculate all performance metrics"""
        return {
            'total_return': self.total_return(),
            'cagr': self.cagr(),
            'max_drawdown': self.max_drawdown(),
            'volatility': self.volatility(),
            'sharpe_ratio': self.sharpe_ratio(),
            'win_rate': self.win_rate(),
            'avg_win': self.avg_win(),
            'avg_loss': self.avg_loss(),
            'num_trades': self.num_trades(),
            'final_equity': self.final_equity(),
            'profit_factor': self.profit_factor(),
            'max_consecutive_wins': self.max_consecutive_wins(),
            'max_consecutive_losses': self.max_consecutive_losses()
        }

    def total_return(self) -> float:
        """Total return percentage"""
        if self.initial_capital == 0 or len(self.equity_df) == 0:
            return 0.0

        final = self.equity_df['equity'].iloc[-1]
        return ((final - self.initial_capital) / self.initial_capital) * 100

    def cagr(self) -> float:
        """Compound Annual Growth Rate"""
        if len(self.equity_df) < 2 or self.initial_capital == 0:
            return 0.0

        start_date = self.equity_df['timestamp'].iloc[0]
        end_date = self.equity_df['timestamp'].iloc[-1]
        years = (end_date - start_date).days / 365.25

        if years == 0:
            return 0.0

        final = self.equity_df['equity'].iloc[-1]
        cagr = (((final / self.initial_capital) ** (1 / years)) - 1) * 100

        return cagr

    def max_drawdown(self) -> float:
        """Maximum drawdown percentage"""
        if len(self.equity_df) == 0:
            return 0.0

        equity = self.equity_df['equity'].values
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak

        return float(np.max(drawdown) * 100)

    def volatility(self) -> float:
        """Annualized volatility"""
        if len(self.equity_df) < 2:
            return 0.0

        # Calculate daily returns
        returns = self.equity_df['equity'].pct_change().dropna()

        if len(returns) == 0:
            return 0.0

        # Annualize (assuming 252 trading days)
        daily_vol = returns.std()
        annual_vol = daily_vol * np.sqrt(252)

        return float(annual_vol * 100)

    def sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Sharpe ratio (annualized)"""
        if len(self.equity_df) < 2:
            return 0.0

        # Calculate daily returns
        returns = self.equity_df['equity'].pct_change().dropna()

        if len(returns) == 0:
            return 0.0

        # Annualize
        annual_return = returns.mean() * 252
        annual_vol = returns.std() * np.sqrt(252)

        if annual_vol == 0:
            return 0.0

        sharpe = (annual_return - risk_free_rate) / annual_vol

        return float(sharpe)

    def win_rate(self) -> float:
        """Percentage of winning trades"""
        if len(self.trades_df) == 0:
            return 0.0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']

        if len(closed_trades) == 0:
            return 0.0

        wins = len(closed_trades[closed_trades['pnl'] > 0])
        return (wins / len(closed_trades)) * 100

    def avg_win(self) -> float:
        """Average winning trade P&L"""
        if len(self.trades_df) == 0:
            return 0.0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']
        winning_trades = closed_trades[closed_trades['pnl'] > 0]

        if len(winning_trades) == 0:
            return 0.0

        return float(winning_trades['pnl'].mean())

    def avg_loss(self) -> float:
        """Average losing trade P&L (negative value)"""
        if len(self.trades_df) == 0:
            return 0.0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']
        losing_trades = closed_trades[closed_trades['pnl'] < 0]

        if len(losing_trades) == 0:
            return 0.0

        return float(losing_trades['pnl'].mean())

    def num_trades(self) -> int:
        """Total number of closed trades"""
        if len(self.trades_df) == 0:
            return 0

        return int(len(self.trades_df[self.trades_df['status'] == 'closed']))

    def final_equity(self) -> float:
        """Final portfolio equity"""
        if len(self.equity_df) == 0:
            return self.initial_capital

        return float(self.equity_df['equity'].iloc[-1])

    def profit_factor(self) -> float:
        """Ratio of gross profits to gross losses"""
        if len(self.trades_df) == 0:
            return 0.0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']

        if len(closed_trades) == 0:
            return 0.0

        gross_profit = closed_trades[closed_trades['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(closed_trades[closed_trades['pnl'] < 0]['pnl'].sum())

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return float(gross_profit / gross_loss)

    def max_consecutive_wins(self) -> int:
        """Maximum consecutive winning trades"""
        if len(self.trades_df) == 0:
            return 0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']

        if len(closed_trades) == 0:
            return 0

        wins = (closed_trades['pnl'] > 0).astype(int)
        max_consecutive = 0
        current_consecutive = 0

        for win in wins:
            if win:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0

        return int(max_consecutive)

    def max_consecutive_losses(self) -> int:
        """Maximum consecutive losing trades"""
        if len(self.trades_df) == 0:
            return 0

        closed_trades = self.trades_df[self.trades_df['status'] == 'closed']

        if len(closed_trades) == 0:
            return 0

        losses = (closed_trades['pnl'] < 0).astype(int)
        max_consecutive = 0
        current_consecutive = 0

        for loss in losses:
            if loss:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0

        return int(max_consecutive)

    def get_equity_curve_data(self) -> List[Dict]:
        """Get equity curve data for charting"""
        if len(self.equity_df) == 0:
            return []

        return self.equity_df.to_dict('records')

    def get_monthly_returns(self) -> pd.DataFrame:
        """Calculate monthly returns"""
        if len(self.equity_df) < 2:
            return pd.DataFrame()

        df = self.equity_df.copy()
        df.set_index('timestamp', inplace=True)
        df = df.resample('M').last()
        df['monthly_return'] = df['equity'].pct_change() * 100

        return df[['equity', 'monthly_return']]


def _naive_utc(ts):
    """
    A Timestamp or datetime Series as naive UTC. Stored runs come back with a
    UTC offset (TIMESTAMPTZ) while the data file's dates are naive, and pandas
    never matches an aware key to a naive one.
    """
    if isinstance(ts, pd.Series):
        return ts.dt.tz_convert('UTC').dt.tz_localize(None) if ts.dt.tz is not None else ts
    return ts.tz_convert('UTC').tz_localize(None) if ts.tzinfo is not None else ts


def returns_by_regime(
    equity_curve: List[Dict],
    regime_by_date: Mapping,
    regime_order: Optional[Sequence[str]] = None,
    trading_days_per_year: int = 252,
) -> Dict[str, Dict[str, float]]:
    """
    Split a backtest's daily returns by the market regime of each day.

    The return from close t-1 to close t is attributed to day t's regime,
    which is the regime the generator used for that day's price move.

    Args:
        equity_curve: [{'timestamp': ..., 'equity': ...}, ...] in time order
        regime_by_date: timestamp -> regime name (from the data's regime column)
        regime_order: optional output order (e.g. the config's regime order)

    Returns:
        {regime: {'days', 'compounded_return_pct', 'annualized_mean_return_pct',
                  'annualized_volatility_pct'}}
    """
    if len(equity_curve) < 2:
        return {}

    df = pd.DataFrame(equity_curve)
    df['timestamp'] = _naive_utc(pd.to_datetime(df['timestamp'], utc=True))
    labels = {_naive_utc(pd.Timestamp(k)): v for k, v in regime_by_date.items()}
    df['daily_return'] = df['equity'].astype(float).pct_change()
    df['regime'] = df['timestamp'].map(labels)
    df = df.dropna(subset=['daily_return', 'regime'])

    names = list(regime_order) if regime_order else sorted(df['regime'].unique())
    result = {}
    for name in names:
        returns = df.loc[df['regime'] == name, 'daily_return']
        if returns.empty:
            continue
        volatility = returns.std(ddof=1) * np.sqrt(trading_days_per_year) if len(returns) > 1 else 0.0
        result[name] = {
            'days': int(len(returns)),
            'compounded_return_pct': float(((1 + returns).prod() - 1) * 100),
            'annualized_mean_return_pct': float(returns.mean() * trading_days_per_year * 100),
            'annualized_volatility_pct': float(volatility * 100),
        }
    return result
