"""
Local cache of market-data bars: one SQLite file, by default
data/cache/market_data.sqlite3 (git-ignored).

Keys. A series is (service URL, ticker, adjustment); split-adjusted and raw
bars of the same ticker are separate series, and so are two services. For
each series the cache keeps its bars by date, the source the service reported
(alpaca or synthetic), and the date ranges known to be complete.

Fetching only what is missing. A range is complete once the service has been
asked for it and has returned every bar it has in it, including the
weekends and holidays that have none. A request for [start, end] subtracts
the complete ranges and fetches only the gaps, then reads the whole range
from the cache. A fetch replaces the cached bars in its range, so the fetched
range always matches the service.

Invalidation:

1. Settling. market-data re-ingests the last 7 days every session, so recent
   bars can still change. Bars newer than `settle_days` (7) before the fetch
   date are stored, but their dates are not marked complete, and the next
   request for them fetches them again.
2. Re-basing. A new split changes every earlier split-adjusted price, and the
   service can correct old bars. Each fetch next to cached data also fetches
   the nearest cached bar (by extending the request when the bar is adjacent,
   or with a one-day request otherwise) and compares it with the cached copy.
   If it differs, the whole series is dropped and fetched again, so the bars
   of one series always share one adjustment basis. A fully cached range is
   not re-checked; scaling every price by the same factor doesn't change a
   backtest's returns.
3. Source. If the service reports a different source for a ticker than the
   cache holds, the series is dropped.
4. By hand: `python -m data_sources cache clear`, or delete the file. A schema
   change (SCHEMA_VERSION) rebuilds the file.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from .market_data import Bar, MarketDataClient, MarketDataError

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_SETTLE_DAYS = 7     # market-data's ingestion lookback-days
DEFAULT_FILENAME = 'market_data.sqlite3'

Range = Tuple[date, date]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    service     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    adjustment  TEXT NOT NULL CHECK (adjustment IN ('split', 'raw')),
    source      TEXT NOT NULL CHECK (source IN ('alpaca', 'synthetic')),
    PRIMARY KEY (service, ticker, adjustment)
);
CREATE TABLE IF NOT EXISTS coverage (
    service     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    adjustment  TEXT NOT NULL,
    start       TEXT NOT NULL,      -- inclusive, YYYY-MM-DD
    end         TEXT NOT NULL,      -- inclusive
    fetched_on  TEXT NOT NULL,
    PRIMARY KEY (service, ticker, adjustment, start),
    FOREIGN KEY (service, ticker, adjustment) REFERENCES series ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS bars (
    service     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    adjustment  TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    volume      INTEGER NOT NULL,
    PRIMARY KEY (service, ticker, adjustment, date),
    FOREIGN KEY (service, ticker, adjustment) REFERENCES series ON DELETE CASCADE
);
"""


def subtract(start: date, end: date, covered: Sequence[Range]) -> List[Range]:
    """The parts of [start, end] not in `covered` (sorted, non-overlapping ranges)"""
    gaps = []
    cursor = start
    for lo, hi in covered:
        if hi < cursor:
            continue
        if lo > end:
            break
        if lo > cursor:
            gaps.append((cursor, lo - timedelta(days=1)))
        cursor = max(cursor, hi + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def merge(ranges: Sequence[Range]) -> List[Range]:
    """Sorted union, joining ranges that overlap or touch"""
    merged: List[Range] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


@dataclass
class CachedSeries:
    """The bars for one request, and what it took to get them"""
    ticker: str
    source: str
    adjustment: str
    bars: List[Bar]
    fetched: List[Range] = field(default_factory=list)   # ranges requested from the service
    rebased: bool = False                                 # the series was dropped and fetched again


class _Stale(Exception):
    """The cached series no longer matches the service"""


class BarCache:
    def __init__(self, path, *, settle_days: int = DEFAULT_SETTLE_DAYS,
                 today: Callable[[], date] = date.today):
        self.path = Path(path)
        self.settle_days = settle_days
        self._today = today
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version != SCHEMA_VERSION:
                # A cache: rebuilding loses nothing that can't be fetched again
                db.executescript('DROP TABLE IF EXISTS bars; DROP TABLE IF EXISTS coverage; '
                                 'DROP TABLE IF EXISTS series;')
                db.executescript(_SCHEMA)
                db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    @classmethod
    def in_dir(cls, directory, **kwargs) -> 'BarCache':
        return cls(Path(directory) / DEFAULT_FILENAME, **kwargs)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One short-lived connection per operation: safe across threads and
        # gunicorn workers. WAL lets readers run during a write; writes take
        # the lock up front (BEGIN IMMEDIATE) and wait up to 30 s for it.
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute('PRAGMA journal_mode = WAL')
            db.execute('PRAGMA foreign_keys = ON')
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise

    # --- reads -------------------------------------------------------------

    def source(self, service: str, ticker: str, adjustment: str) -> Optional[str]:
        with self._connect() as db:
            row = db.execute('SELECT source FROM series WHERE service = ? AND ticker = ? AND adjustment = ?',
                             (service, ticker, adjustment)).fetchone()
        return row[0] if row else None

    def covered(self, service: str, ticker: str, adjustment: str) -> List[Range]:
        with self._connect() as db:
            rows = db.execute('SELECT start, end FROM coverage WHERE service = ? AND ticker = ? '
                              'AND adjustment = ? ORDER BY start', (service, ticker, adjustment)).fetchall()
        return [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in rows]

    def missing(self, service: str, ticker: str, adjustment: str, start: date, end: date) -> List[Range]:
        return subtract(start, end, self.covered(service, ticker, adjustment))

    def read(self, service: str, ticker: str, adjustment: str, start: date, end: date) -> List[Bar]:
        with self._connect() as db:
            rows = db.execute(
                'SELECT date, open, high, low, close, volume FROM bars WHERE service = ? AND ticker = ? '
                'AND adjustment = ? AND date BETWEEN ? AND ? ORDER BY date',
                (service, ticker, adjustment, start.isoformat(), end.isoformat())).fetchall()
        return [Bar(date.fromisoformat(d), o, h, lo, c, v) for d, o, h, lo, c, v in rows]

    def _nearest_bar(self, service: str, ticker: str, adjustment: str,
                     start: date, end: date) -> Optional[Bar]:
        """The complete-range bar closest before `start`, or else closest after `end`"""
        # Only bars inside complete ranges: an unsettled bar may have changed
        # legitimately and says nothing about the adjustment basis
        query = ('SELECT date, open, high, low, close, volume FROM bars b WHERE service = ? AND ticker = ? '
                 'AND adjustment = ? AND date {op} ? AND EXISTS (SELECT 1 FROM coverage c '
                 'WHERE (c.service, c.ticker, c.adjustment) = (b.service, b.ticker, b.adjustment) '
                 'AND b.date BETWEEN c.start AND c.end) ORDER BY date {order} LIMIT 1')
        key = (service, ticker, adjustment)
        with self._connect() as db:
            row = (db.execute(query.format(op='<', order='DESC'), (*key, start.isoformat())).fetchone()
                   or db.execute(query.format(op='>', order='ASC'), (*key, end.isoformat())).fetchone())
        if row is None:
            return None
        d, o, h, lo, c, v = row
        return Bar(date.fromisoformat(d), o, h, lo, c, v)

    def info(self) -> List[dict]:
        """One row per cached series"""
        with self._connect() as db:
            rows = db.execute(
                'SELECT s.service, s.ticker, s.adjustment, s.source, COUNT(b.date), MIN(b.date), MAX(b.date) '
                'FROM series s LEFT JOIN bars b USING (service, ticker, adjustment) '
                'GROUP BY s.service, s.ticker, s.adjustment ORDER BY s.service, s.ticker, s.adjustment'
            ).fetchall()
        return [dict(zip(('service', 'ticker', 'adjustment', 'source', 'bars', 'first', 'last'), r))
                for r in rows]

    # --- writes ------------------------------------------------------------

    def store(self, service: str, ticker: str, adjustment: str, source: str,
              start: date, end: date, bars: Sequence[Bar]) -> Optional[Range]:
        """
        Replace the cached bars in [start, end] with `bars` (a complete answer
        from the service for that range), and mark the settled part complete.
        Returns the range marked complete, if any.
        """
        today = self._today()
        settled_end = min(end, today - timedelta(days=self.settle_days))
        key = (service, ticker, adjustment)
        with self._write() as db:
            db.execute('INSERT INTO series (service, ticker, adjustment, source) VALUES (?, ?, ?, ?) '
                       'ON CONFLICT (service, ticker, adjustment) DO UPDATE SET source = excluded.source',
                       (*key, source))
            db.execute('DELETE FROM bars WHERE service = ? AND ticker = ? AND adjustment = ? '
                       'AND date BETWEEN ? AND ?', (*key, start.isoformat(), end.isoformat()))
            db.executemany(
                'INSERT INTO bars (service, ticker, adjustment, date, open, high, low, close, volume) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                [(*key, b.date.isoformat(), b.open, b.high, b.low, b.close, b.volume) for b in bars])
            if settled_end < start:
                return None
            rows = db.execute('SELECT start, end FROM coverage WHERE service = ? AND ticker = ? '
                              'AND adjustment = ?', key).fetchall()
            ranges = merge([(date.fromisoformat(a), date.fromisoformat(b)) for a, b in rows]
                           + [(start, settled_end)])
            db.execute('DELETE FROM coverage WHERE service = ? AND ticker = ? AND adjustment = ?', key)
            db.executemany(
                'INSERT INTO coverage (service, ticker, adjustment, start, end, fetched_on) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                [(*key, lo.isoformat(), hi.isoformat(), today.isoformat()) for lo, hi in ranges])
        return (start, settled_end)

    def drop(self, service: str, ticker: str, adjustment: str) -> None:
        with self._write() as db:
            db.execute('DELETE FROM series WHERE service = ? AND ticker = ? AND adjustment = ?',
                       (service, ticker, adjustment))

    def clear(self) -> None:
        with self._write() as db:
            db.execute('DELETE FROM series')

    # --- the read-through path ---------------------------------------------

    def get(self, client: MarketDataClient, ticker: str, start: date, end: date,
            adjustment: str = 'split') -> CachedSeries:
        """Bars for [start, end], fetching only the ranges the cache lacks"""
        if start > end:
            raise ValueError(f'start {start} is after end {end}')
        ticker = ticker.upper()
        service = client.base_url
        rebased = False
        while True:
            fetched: List[Range] = []
            try:
                for gap_start, gap_end in self.missing(service, ticker, adjustment, start, end):
                    fetched.append(self._fill(client, service, ticker, adjustment, gap_start, gap_end))
            except _Stale as e:
                if rebased:
                    # A dropped series has nothing cached to disagree with, so
                    # only a concurrent writer gets here
                    raise MarketDataError(f'{ticker}: the cached series changed again during a refetch') from e
                log.info('market-data cache: %s %s %s; refetching the series', ticker, adjustment, e)
                self.drop(service, ticker, adjustment)
                rebased = True
                continue
            source = self.source(service, ticker, adjustment)
            if source is None:   # every complete range was stored with a source
                raise MarketDataError(f'{ticker}: cached bars without a source')
            return CachedSeries(ticker=ticker, source=source, adjustment=adjustment,
                                bars=self.read(service, ticker, adjustment, start, end),
                                fetched=fetched, rebased=rebased)

    def _fill(self, client: MarketDataClient, service: str, ticker: str, adjustment: str,
              gap_start: date, gap_end: date) -> Range:
        anchor = self._nearest_bar(service, ticker, adjustment, gap_start, gap_end)
        fetch_start, fetch_end = gap_start, gap_end
        separate_check = False
        if anchor is not None:
            covered = self.covered(service, ticker, adjustment)
            # Adjacent: the cached days between the anchor and the gap are
            # complete and hold no bars, so extending the request re-reads
            # exactly one bar
            if any(lo <= anchor.date <= hi and (hi + timedelta(days=1) == gap_start
                                               or lo - timedelta(days=1) == gap_end)
                   for lo, hi in covered):
                fetch_start, fetch_end = min(gap_start, anchor.date), max(gap_end, anchor.date)
            else:
                separate_check = True

        series = client.bars(ticker, fetch_start, fetch_end, adjustment=adjustment)
        cached_source = self.source(service, ticker, adjustment)
        if cached_source is not None and cached_source != series.source:
            raise _Stale(f'source changed from {cached_source} to {series.source}')
        if anchor is not None:
            if separate_check:
                check = client.bars(ticker, anchor.date, anchor.date, adjustment=adjustment).bars
            else:
                check = tuple(b for b in series.bars if b.date == anchor.date)
            if not check or check[0] != anchor:
                raise _Stale(f'the cached bar for {anchor.date} differs from the service\'s')
        self.store(service, ticker, adjustment, series.source, fetch_start, fetch_end, series.bars)
        return (fetch_start, fetch_end)
