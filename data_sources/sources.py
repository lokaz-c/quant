"""
The data source switch, and the provenance each run records.

Two sources:

- `synthetic`: the seeded generator's file, data/sample_data.csv (or
  DATA_PATH). Always available. `make results` and CI use it.
- `market-data`: daily bars from the market-data service (MARKET_DATA_URL),
  through the local cache. The service labels every symbol `alpaca` or
  `synthetic`; its public endpoints serve only synthetic data unless the
  operator has Alpaca's consent and a key unlocks the rest.

Configuration (environment, see .env.example):

    QUANT_DATA_SOURCE      synthetic | market-data. Default: market-data when
                           MARKET_DATA_URL is set, synthetic otherwise.
    MARKET_DATA_URL        e.g. http://localhost:8080
    MARKET_DATA_API_KEY    optional; sent as X-API-Key
    MARKET_DATA_ADJUSTMENT split (default) | raw
    MARKET_DATA_CACHE_DIR  default data/cache; "off" disables the cache
    MARKET_DATA_TIMEOUT    read timeout in seconds (default 30)

Labelling. A run is "real" only if it came from market-data and the service
reported `alpaca` for every symbol (Provenance.real). Anything else (the
local generator, the service's own synthetic data, a mix) is labelled
synthetic. Unknown source values are rejected by the client's parser instead
of being labelled at all.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from backtest_engine.data_loader import DataLoader

from .cache import BarCache
from .market_data import ADJUSTMENTS, DEFAULT_ADJUSTMENT, SOURCES, MarketDataClient, SymbolSummary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYNTHETIC_PATH = REPO_ROOT / 'data' / 'sample_data.csv'
DEFAULT_CACHE_DIR = REPO_ROOT / 'data' / 'cache'

SYNTHETIC = 'synthetic'
MARKET_DATA = 'market-data'
DATA_SOURCES = (SYNTHETIC, MARKET_DATA)

# What the service may report, plus 'mixed' for a run over symbols of both
REPORTED_SOURCES = ('synthetic', 'alpaca', 'mixed')
REAL_SOURCES = frozenset({'alpaca'})

SYNTHETIC_DESCRIPTION = ('Synthetic daily bars from a seeded Markov regime-switching GBM '
                         '(config/data_generator.json). Ticker names are labels only.')


class DataSourceError(ValueError):
    """A data source that is unknown or not configured"""


class NoBars(ValueError):
    """The source has no bars for the request"""


@dataclass(frozen=True)
class DataConfig:
    default_source: str
    synthetic_path: Path = DEFAULT_SYNTHETIC_PATH
    market_data_url: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    adjustment: str = DEFAULT_ADJUSTMENT
    cache_dir: Optional[Path] = DEFAULT_CACHE_DIR
    timeout: Optional[float] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> 'DataConfig':
        env = os.environ if env is None else env
        url = env.get('MARKET_DATA_URL', '').strip() or None
        source = env.get('QUANT_DATA_SOURCE', '').strip() or (MARKET_DATA if url else SYNTHETIC)
        if source not in DATA_SOURCES:
            raise DataSourceError(f'QUANT_DATA_SOURCE must be one of {", ".join(DATA_SOURCES)}, got {source!r}')
        if source == MARKET_DATA and not url:
            raise DataSourceError('QUANT_DATA_SOURCE=market-data needs MARKET_DATA_URL')
        adjustment = env.get('MARKET_DATA_ADJUSTMENT', '').strip() or DEFAULT_ADJUSTMENT
        if adjustment not in ADJUSTMENTS:
            raise DataSourceError(f'MARKET_DATA_ADJUSTMENT must be split or raw, got {adjustment!r}')
        cache = env.get('MARKET_DATA_CACHE_DIR', '').strip()
        timeout = env.get('MARKET_DATA_TIMEOUT', '').strip()
        return cls(
            default_source=source,
            synthetic_path=Path(env.get('DATA_PATH', '').strip() or DEFAULT_SYNTHETIC_PATH),
            market_data_url=url,
            api_key=env.get('MARKET_DATA_API_KEY', '').strip() or None,
            adjustment=adjustment,
            cache_dir=None if cache.lower() == 'off' else Path(cache) if cache else DEFAULT_CACHE_DIR,
            timeout=float(timeout) if timeout else None,
        )

    @property
    def available(self) -> List[str]:
        return [SYNTHETIC, MARKET_DATA] if self.market_data_url else [SYNTHETIC]

    def resolve(self, requested: Optional[str]) -> str:
        """The source for one request: the requested one, or the default"""
        if requested is None:
            return self.default_source
        if requested not in DATA_SOURCES:
            raise DataSourceError(f'data_source must be one of {", ".join(DATA_SOURCES)}')
        if requested == MARKET_DATA and not self.market_data_url:
            raise DataSourceError('The market-data source is not configured on this server (MARKET_DATA_URL)')
        return requested

    def client(self, **kwargs) -> MarketDataClient:
        if not self.market_data_url:
            raise DataSourceError('MARKET_DATA_URL is not set')
        env = {'MARKET_DATA_URL': self.market_data_url, 'MARKET_DATA_API_KEY': self.api_key or ''}
        if self.timeout:
            env['MARKET_DATA_TIMEOUT'] = str(self.timeout)
        return MarketDataClient.from_env(env, **kwargs)

    def cache(self) -> Optional[BarCache]:
        return BarCache.in_dir(self.cache_dir) if self.cache_dir else None


def summarize_sources(symbol_sources: Mapping[str, str]) -> str:
    """'alpaca' or 'synthetic' when every symbol agrees, 'mixed' otherwise"""
    values = set(symbol_sources.values())
    if not values:
        raise ValueError('no symbols')
    unknown = values - set(SOURCES)
    if unknown:
        raise ValueError(f'unknown source(s): {", ".join(sorted(unknown))}')
    return values.pop() if len(values) == 1 else 'mixed'


@dataclass(frozen=True)
class Provenance:
    """Where a run's bars came from. Stored on backtest_runs (migration 0004)."""
    data_source: str                                  # synthetic | market-data
    reported_source: str                              # synthetic | alpaca | mixed
    symbol_sources: Optional[Dict[str, str]] = None   # market-data: per symbol, as reported
    adjustment: Optional[str] = None                  # market-data: split | raw

    def __post_init__(self):
        if self.data_source not in DATA_SOURCES:
            raise ValueError(f'unknown data source {self.data_source!r}')
        if self.reported_source not in REPORTED_SOURCES:
            raise ValueError(f'unknown reported source {self.reported_source!r}')
        if self.data_source == SYNTHETIC and self.reported_source != 'synthetic':
            raise ValueError('the local generator can only report synthetic data')
        if self.symbol_sources is not None and summarize_sources(self.symbol_sources) != self.reported_source:
            raise ValueError('reported_source does not match symbol_sources')

    @classmethod
    def local_synthetic(cls) -> 'Provenance':
        return cls(data_source=SYNTHETIC, reported_source='synthetic')

    @classmethod
    def from_market_data(cls, symbol_sources: Mapping[str, str], adjustment: str) -> 'Provenance':
        return cls(data_source=MARKET_DATA, reported_source=summarize_sources(symbol_sources),
                   symbol_sources=dict(sorted(symbol_sources.items())), adjustment=adjustment)

    @property
    def real(self) -> bool:
        """True only for market-data bars the service labelled alpaca, every one"""
        return (self.data_source == MARKET_DATA and self.reported_source in REAL_SOURCES
                and bool(self.symbol_sources)
                and all(s in REAL_SOURCES for s in self.symbol_sources.values()))

    def description(self) -> str:
        if self.data_source == SYNTHETIC:
            return SYNTHETIC_DESCRIPTION
        adjusted = 'split-adjusted' if self.adjustment == 'split' else 'not split-adjusted'
        if self.real:
            return (f'Daily bars from Alpaca, served by the market-data service, {adjusted}. The service '
                    "ingests Alpaca's IEX feed by default; IEX is a single exchange, so volumes and prices "
                    'are not the consolidated tape.')
        if self.reported_source == 'synthetic':
            return ('Synthetic daily bars generated by the market-data service (it labels them source=synthetic). '
                    'They are not market prices.')
        synthetic = sorted(t for t, s in (self.symbol_sources or {}).items() if s == 'synthetic')
        return (f'Mixed: the market-data service labelled {", ".join(synthetic)} synthetic and the other '
                f'symbols alpaca. Treat the results as synthetic.')

    def to_api(self) -> Dict:
        body: Dict = {
            'source': self.data_source,
            'reported_source': self.reported_source,
            'synthetic': not self.real,
            'description': self.description(),
        }
        if self.data_source == SYNTHETIC:
            body['file'] = 'data/sample_data.csv'
        else:
            body['symbol_sources'] = self.symbol_sources
            body['adjustment'] = self.adjustment
        return body


class InMemoryLoader(DataLoader):
    """
    A DataLoader over bars that are already in memory (fetched from
    market-data), so the Backtester can use them unchanged.
    """

    def __init__(self, frame: pd.DataFrame, label: str = 'market-data'):
        super().__init__(data_path=f'<{label}>')
        self._frame = frame

    def load_csv(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        df = self._frame
        if symbols:
            df = df[df['symbol'].isin(symbols)]
        self.data = df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)
        return self.data


@dataclass
class LoadedBars:
    loader: DataLoader
    provenance: Provenance
    frame: Optional[pd.DataFrame] = None   # market-data only; the synthetic loader reads its file


@lru_cache(maxsize=4)
def _synthetic_index(path: str, mtime: float) -> Tuple[Tuple[str, ...], Tuple[date, ...]]:
    data = DataLoader(path).load_csv()
    dates = sorted({ts.date() for ts in data['timestamp']})
    return tuple(sorted(data['symbol'].unique().tolist())), tuple(dates)


class SyntheticSource:
    kind = SYNTHETIC

    def __init__(self, path: Path = DEFAULT_SYNTHETIC_PATH):
        self.path = Path(path)

    def index(self) -> Tuple[Tuple[str, ...], Tuple[date, ...]]:
        """Symbols and bar dates of the file (cached per path and mtime)"""
        return _synthetic_index(str(self.path), os.path.getmtime(self.path))

    def info(self) -> Dict:
        symbols, dates = self.index()
        return {**Provenance.local_synthetic().to_api(), 'symbols': list(symbols),
                'start_date': dates[0].isoformat(), 'end_date': dates[-1].isoformat(), 'bars': len(dates)}

    def load(self, symbols: Optional[Sequence[str]], start: date, end: date) -> LoadedBars:
        # The Backtester reads and filters the file itself, exactly as before
        return LoadedBars(loader=DataLoader(str(self.path)), provenance=Provenance.local_synthetic())


# Symbol listings are memoised per process for this long; the service marks
# them cacheable for 5 minutes (Cache-Control: max-age=300)
SYMBOLS_TTL_SECONDS = 300.0
_symbols_memo: Dict[Tuple[str, bool], Tuple[float, List[SymbolSummary]]] = {}


class MarketDataSource:
    kind = MARKET_DATA

    def __init__(self, client: MarketDataClient, cache: Optional[BarCache] = None,
                 adjustment: str = DEFAULT_ADJUSTMENT):
        self.client = client
        self.cache = cache
        self.adjustment = adjustment

    def symbols(self) -> List[SymbolSummary]:
        key = (self.client.base_url, self.client.has_api_key)
        hit = _symbols_memo.get(key)
        if hit and time.monotonic() - hit[0] < SYMBOLS_TTL_SECONDS:
            return hit[1]
        symbols = self.client.symbols()
        _symbols_memo[key] = (time.monotonic(), symbols)
        return symbols

    def info(self) -> Dict:
        symbols = self.symbols()
        if not symbols:
            raise NoBars('The market-data service lists no symbols this server may see')
        provenance = Provenance.from_market_data({s.ticker: s.source for s in symbols}, self.adjustment)
        return {**provenance.to_api(), 'symbols': [s.ticker for s in symbols],
                'start_date': min(s.first_bar for s in symbols).isoformat(),
                'end_date': max(s.last_bar for s in symbols).isoformat(), 'bars': None}

    def series(self, ticker: str, start: date, end: date):
        if self.cache is not None:
            return self.cache.get(self.client, ticker, start, end, self.adjustment)
        return self.client.bars(ticker, start, end, adjustment=self.adjustment)

    def load(self, symbols: Sequence[str], start: date, end: date) -> LoadedBars:
        frames, sources = [], {}
        for ticker in symbols:
            series = self.series(ticker, start, end)
            sources[ticker] = series.source
            frames.append(pd.DataFrame({
                'timestamp': pd.to_datetime([b.date for b in series.bars]),
                'symbol': ticker,
                'open': [b.open for b in series.bars],
                'high': [b.high for b in series.bars],
                'low': [b.low for b in series.bars],
                'close': [b.close for b in series.bars],
                'volume': [b.volume for b in series.bars],
            }))
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if frame.empty:
            raise NoBars(f'market-data has no bars for {", ".join(symbols)} between {start} and {end}')
        frame = frame.sort_values(['timestamp', 'symbol'], kind='mergesort').reset_index(drop=True)
        return LoadedBars(loader=InMemoryLoader(frame),
                          provenance=Provenance.from_market_data(sources, self.adjustment), frame=frame)


def open_source(config: DataConfig, name: str, **client_kwargs):
    """The source object for `name`, built from the configuration"""
    if name == SYNTHETIC:
        return SyntheticSource(config.synthetic_path)
    if name == MARKET_DATA:
        return MarketDataSource(config.client(**client_kwargs), config.cache(), config.adjustment)
    raise DataSourceError(f'unknown data source {name!r}')
