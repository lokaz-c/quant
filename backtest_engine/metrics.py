"""
Performance metrics calculator
Computes various trading performance metrics

A metric whose formula has no value for a run (a division by zero, or a mean
or standard deviation over too few values) is None, never a stand-in number
such as 0.0 or infinity, and `PerformanceMetrics.undefined` says why. The API
returns None as JSON null, with the reason in `undefined_metrics`
(docs/api.md#undefined-metrics).
"""
import math
import numpy as np
import pandas as pd
from typing import Dict, List, Mapping, Optional, Sequence
from datetime import datetime

# Conventions shared with sql/metrics.sql (the SQL cross-check binds these):
# daily returns, annualised with 252 trading days, Sharpe net of a 2% annual
# risk-free rate, sample standard deviation (ddof=1, pandas' default).
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.02
ROLLING_SHARPE_WINDOW = 63  # trading days, about one quarter

# Why a metric is undefined (None). These strings are part of the API.
FEWER_THAN_TWO_RETURNS = 'fewer than two daily returns'
ZERO_VOLATILITY = 'zero volatility'
ZERO_LENGTH_PERIOD = 'the run starts and ends on the same day'
NO_CLOSED_TRADES = 'no closed trades'
NO_WINNING_TRADES = 'no winning trades'
NO_LOSING_TRADES = 'no losing trades'
NOT_FINITE = 'the result is not a finite number'


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

        # metric name -> why it is None; filled in as the metrics are computed
        self.undefined: Dict[str, str] = {}

    def _undefined(self, metric: str, reason: str) -> None:
        self.undefined[metric] = reason
        return None

    def calculate_all(self) -> Dict:
        """
        Calculate all performance metrics. Undefined ones are None, with the
        reason in self.undefined. Any other non-finite result (e.g. a CAGR
        that overflows over a very short run) is also None, so nothing
        returned here is NaN or infinite.
        """
        self.undefined = {}
        metrics = {
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
        for name, value in metrics.items():
            if isinstance(value, float) and not math.isfinite(value):
                metrics[name] = self._undefined(name, NOT_FINITE)
        return metrics

    def _daily_returns(self) -> pd.Series:
        if len(self.equity_df) < 2:
            return pd.Series(dtype=float)
        return self.equity_df['equity'].pct_change().dropna()

    def total_return(self) -> float:
        """Total return percentage"""
        if self.initial_capital == 0 or len(self.equity_df) == 0:
            return 0.0

        final = self.equity_df['equity'].iloc[-1]
        return ((final - self.initial_capital) / self.initial_capital) * 100

    def cagr(self) -> Optional[float]:
        """Compound Annual Growth Rate; None for a run that covers no time"""
        if self.initial_capital == 0:
            return 0.0
        if len(self.equity_df) < 2:
            return self._undefined('cagr', ZERO_LENGTH_PERIOD)

        start_date = self.equity_df['timestamp'].iloc[0]
        end_date = self.equity_df['timestamp'].iloc[-1]
        years = (end_date - start_date).days / 365.25

        if years == 0:
            return self._undefined('cagr', ZERO_LENGTH_PERIOD)

        final = self.equity_df['equity'].iloc[-1]
        cagr = (((final / self.initial_capital) ** (1 / years)) - 1) * 100

        return cagr

    def drawdown_series(self) -> pd.Series:
        """Drawdown from the running peak at each point, in percent"""
        equity = self.equity_df.set_index('timestamp')['equity']
        peak = equity.cummax()
        return (peak - equity) / peak * 100

    def max_drawdown(self) -> float:
        """Maximum drawdown percentage"""
        if len(self.equity_df) == 0:
            return 0.0

        return float(self.drawdown_series().max())

    def volatility(self) -> Optional[float]:
        """
        Annualized volatility; None with fewer than two daily returns (the
        sample standard deviation needs two)
        """
        returns = self._daily_returns()

        if len(returns) < 2:
            return self._undefined('volatility', FEWER_THAN_TWO_RETURNS)

        # Annualize (assuming 252 trading days)
        daily_vol = returns.std()
        annual_vol = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)

        return float(annual_vol * 100)

    def sharpe_ratio(self, risk_free_rate: float = RISK_FREE_RATE) -> Optional[float]:
        """
        Sharpe ratio (annualized). None with fewer than two daily returns or
        zero volatility, where it is undefined; sql/metrics.sql returns NULL
        in the same cases.
        """
        returns = self._daily_returns()

        if len(returns) < 2:
            return self._undefined('sharpe_ratio', FEWER_THAN_TWO_RETURNS)

        # Annualize
        annual_return = returns.mean() * TRADING_DAYS_PER_YEAR
        annual_vol = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        if annual_vol == 0:
            return self._undefined('sharpe_ratio', ZERO_VOLATILITY)

        sharpe = (annual_return - risk_free_rate) / annual_vol

        return float(sharpe)

    def rolling_sharpe(self, window: int = ROLLING_SHARPE_WINDOW,
                       risk_free_rate: float = RISK_FREE_RATE) -> pd.Series:
        """
        Sharpe ratio over each trailing `window` daily returns, indexed by the
        timestamp of the window's last return. Same conventions as
        sharpe_ratio(). The first equity point has no return, so the first
        value is at point `window` (0-based). Windows with zero volatility,
        where Sharpe is undefined, are NaN (where sharpe_ratio() gives None).
        This series is internal (the SQL cross-check); no API returns it.
        """
        if len(self.equity_df) < 2:
            return pd.Series(dtype=float)

        returns = self.equity_df.set_index('timestamp')['equity'].pct_change().dropna()
        rolling = returns.rolling(window)
        mean, std = rolling.mean(), rolling.std()  # std: ddof=1
        sharpe = (mean * TRADING_DAYS_PER_YEAR - risk_free_rate) / (std * np.sqrt(TRADING_DAYS_PER_YEAR))
        return sharpe.where(std > 0).iloc[window - 1:]

    def _closed_trades(self) -> pd.DataFrame:
        if len(self.trades_df) == 0:
            return self.trades_df
        return self.trades_df[self.trades_df['status'] == 'closed']

    def win_rate(self) -> Optional[float]:
        """Percentage of winning trades; None with no closed trades"""
        closed_trades = self._closed_trades()

        if len(closed_trades) == 0:
            return self._undefined('win_rate', NO_CLOSED_TRADES)

        wins = len(closed_trades[closed_trades['pnl'] > 0])
        return (wins / len(closed_trades)) * 100

    def avg_win(self) -> Optional[float]:
        """Average winning trade P&L; None without a winning trade"""
        closed_trades = self._closed_trades()
        if len(closed_trades) == 0:
            return self._undefined('avg_win', NO_CLOSED_TRADES)

        winning_trades = closed_trades[closed_trades['pnl'] > 0]

        if len(winning_trades) == 0:
            return self._undefined('avg_win', NO_WINNING_TRADES)

        return float(winning_trades['pnl'].mean())

    def avg_loss(self) -> Optional[float]:
        """Average losing trade P&L (negative value); None without a losing trade"""
        closed_trades = self._closed_trades()
        if len(closed_trades) == 0:
            return self._undefined('avg_loss', NO_CLOSED_TRADES)

        losing_trades = closed_trades[closed_trades['pnl'] < 0]

        if len(losing_trades) == 0:
            return self._undefined('avg_loss', NO_LOSING_TRADES)

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

    def profit_factor(self) -> Optional[float]:
        """
        Gross profit / gross loss. None with no closed trades or no losing
        trade: the ratio would be infinite (or 0/0), which JSON can't carry.
        """
        closed_trades = self._closed_trades()

        if len(closed_trades) == 0:
            return self._undefined('profit_factor', NO_CLOSED_TRADES)

        gross_profit = closed_trades[closed_trades['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(closed_trades[closed_trades['pnl'] < 0]['pnl'].sum())

        if gross_loss == 0:
            return self._undefined('profit_factor', NO_LOSING_TRADES)

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
                  'annualized_volatility_pct', 'undefined_metrics'}}
        Volatility is None for a regime with a single day (the sample
        standard deviation needs two returns); 'undefined_metrics' then says so.
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
        defined = len(returns) > 1
        volatility = returns.std(ddof=1) * np.sqrt(trading_days_per_year) * 100 if defined else None
        result[name] = {
            'days': int(len(returns)),
            'compounded_return_pct': float(((1 + returns).prod() - 1) * 100),
            'annualized_mean_return_pct': float(returns.mean() * trading_days_per_year * 100),
            'annualized_volatility_pct': None if volatility is None else float(volatility),
            'undefined_metrics': {} if defined else {'annualized_volatility_pct': FEWER_THAN_TWO_RETURNS},
        }
    return result
