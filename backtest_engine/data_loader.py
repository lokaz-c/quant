"""
OHLCV data: a CSV loader, and the generator for the synthetic sample dataset.

The bundled data/sample_data.csv is synthetic. It is written by
generate_sample_data(): a seeded Markov chain switches between bull, bear and
sideways regimes (config/data_generator.json), and each symbol's closes follow
a geometric Brownian motion with that regime's drift and volatility. Ticker
names are labels only. Regenerate it with:

    python -m backtest_engine.data_loader
"""
import argparse
import os
import zlib
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .regimes import DEFAULT_CONFIG_PATH, RegimeModel

DEFAULT_SEED = 42
DEFAULT_START = '2020-01-01'
DEFAULT_END = '2024-12-31'
DEFAULT_OUTPUT = 'data/sample_data.csv'
DEFAULT_SYMBOLS = [
    'AAPL', 'ABNB', 'ADBE', 'AMD', 'AMZN', 'BABA', 'COIN', 'CRM', 'CSCO', 'DIS',
    'GOOGL', 'INTC', 'JPM', 'MA', 'META', 'MSFT', 'NFLX', 'NVDA', 'ORCL', 'PYPL',
    'SHOP', 'SQ', 'TSLA', 'UBER', 'V',
]

# Separate random streams for the shared regime path and for each symbol
_REGIME_STREAM = 0
_SYMBOL_STREAM = 1


def _read_bars(path) -> pd.DataFrame:
    """
    The CSV with parsed timestamps. A file on disk is parsed once per version
    (path, modification time, size) and kept: the API reads the same sample
    file for every run, and parsing it was about half of a 5-symbol, 1-year
    run (`python -m scripts.profile_bench --case 0`). Callers get filtered or
    sorted copies, never this frame.
    """
    if isinstance(path, (str, os.PathLike)) and os.path.isfile(path):
        stat = os.stat(path)
        return _read_bars_cached(os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
    return _parse_bars(path)


def _parse_bars(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


@lru_cache(maxsize=4)
def _read_bars_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    return _parse_bars(path)


def clear_csv_cache() -> None:
    """Forget every parsed file (make bench times each run's CSV read, as it always has)"""
    _read_bars_cached.cache_clear()


class DataLoader:
    """Loads OHLCV bars from a CSV file (columns: timestamp, symbol, open, high, low, close, volume)"""

    def __init__(self, data_path: str):
        self.data_path = data_path
        self.data = None

    def load_csv(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Load bars from the CSV file, optionally only for some symbols

        Expected CSV columns: timestamp, symbol, open, high, low, close, volume.
        Extra columns (the sample data has a `regime` column) are kept.
        """
        df = _read_bars(self.data_path)

        # Filter by symbols if provided (a new frame; the cached one is never returned)
        if symbols:
            df = df[df['symbol'].isin(symbols)]

        # Sort by timestamp
        df = df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)

        self.data = df
        return df

    def filter_by_date(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Filter data by date range"""
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        filtered = self.data[(self.data['timestamp'] >= start) & (self.data['timestamp'] <= end)]
        return filtered.reset_index(drop=True)

    def get_symbols(self) -> List[str]:
        """Get list of unique symbols in the dataset"""
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        return self.data['symbol'].unique().tolist()

    def validate_data(self) -> bool:
        """Validate that data has required columns and proper format"""
        if self.data is None:
            return False

        required_cols = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in self.data.columns for col in required_cols):
            return False

        # Check for missing values
        if self.data[required_cols].isnull().any().any():
            return False

        return True


def symbol_rng(symbol: str, seed: int = DEFAULT_SEED) -> np.random.Generator:
    """Random generator for one symbol, stable across processes and platforms.

    The built-in hash() of a str is salted per process (PYTHONHASHSEED), so it
    cannot be used as a seed; crc32 of the UTF-8 bytes is fixed.
    """
    return np.random.default_rng([seed, _SYMBOL_STREAM, zlib.crc32(symbol.encode('utf-8'))])


def regime_rng(seed: int = DEFAULT_SEED) -> np.random.Generator:
    """Random generator for the market-wide regime path."""
    return np.random.default_rng([seed, _REGIME_STREAM])


def generate_sample_data(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    output_path: Optional[Union[str, Path]] = None,
    regime: str = 'markov',
    seed: int = DEFAULT_SEED,
    model: Optional[RegimeModel] = None,
) -> pd.DataFrame:
    """
    Generate synthetic daily OHLCV bars. Same arguments and seed -> identical output.

    One regime path is simulated for the whole market and shared by every
    symbol; each symbol then draws its own GBM shocks, start price, intraday
    range and volume from its own generator.

    Args:
        symbols: Ticker symbols (labels only; prices are simulated)
        start_date: First date (YYYY-MM-DD); bars are on business days
        end_date: Last date (YYYY-MM-DD)
        output_path: Optional path to write the CSV to
        regime: 'markov' to switch regimes with the Markov chain, or a regime
            name from the config (e.g. 'bull') to stay in that regime
        seed: Base seed for the regime path and every symbol
        model: Regime model; defaults to config/data_generator.json

    Returns:
        DataFrame sorted by timestamp then symbol, with columns
        timestamp, symbol, open, high, low, close, volume, regime
    """
    if not symbols:
        raise ValueError('At least one symbol is required')
    model = model or RegimeModel.from_json(DEFAULT_CONFIG_PATH)

    dates = pd.date_range(pd.to_datetime(start_date), pd.to_datetime(end_date), freq='B')
    n = len(dates)
    if n == 0:
        raise ValueError(f'No business days between {start_date} and {end_date}')

    if regime == 'markov':
        path = model.simulate(n, regime_rng(seed))
    else:
        path = np.full(n, model.index_of(regime), dtype=np.int64)
    regime_labels = np.asarray(model.names, dtype=object)[path]

    frames = []
    for symbol in symbols:
        rng = symbol_rng(symbol, seed)
        start_price = rng.uniform(*model.initial_price_range)
        log_returns = model.daily_log_returns(path, rng)
        log_returns[0] = 0.0  # the first close is the start price
        close = start_price * np.exp(np.cumsum(log_returns))

        # Intraday range of 1-3% of the close; high and low inside it, open between them
        daily_range = close * rng.uniform(0.01, 0.03, n)
        high = close + rng.uniform(0.0, 1.0, n) * daily_range
        low = close - rng.uniform(0.0, 1.0, n) * daily_range
        open_price = low + rng.uniform(0.0, 1.0, n) * (high - low)
        volume = rng.integers(100_000, 10_000_000, n)

        frames.append(pd.DataFrame({
            'timestamp': dates,
            'symbol': symbol,
            'open': np.round(open_price, 2),
            'high': np.round(high, 2),
            'low': np.round(low, 2),
            'close': np.round(close, 2),
            'volume': volume,
            'regime': regime_labels,
        }))

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(['timestamp', 'symbol'], kind='mergesort').reset_index(drop=True)

    if output_path:
        df.to_csv(output_path, index=False)

    return df


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description='Write the synthetic sample dataset (Markov regime-switching GBM).')
    parser.add_argument('--symbols', default=','.join(DEFAULT_SYMBOLS),
                        help='comma-separated tickers (labels only)')
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--end', default=DEFAULT_END)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--regime', default='markov',
                        help="'markov' or a regime name from the config to hold fixed")
    parser.add_argument('--config', default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
    df = generate_sample_data(symbols, args.start, args.end, output_path=args.output,
                              regime=args.regime, seed=args.seed,
                              model=RegimeModel.from_json(args.config))
    print(f'Wrote {len(df)} rows ({len(symbols)} symbols, {args.start} to {args.end}, '
          f'seed {args.seed}) to {args.output}')


if __name__ == '__main__':
    main()
