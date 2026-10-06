"""
Client for the market-data service's REST API (lokaz-c/market-data, /v1).

The contract, as the service implements it (MarketDataController, Dtos,
ApiAccessFilter and RateLimitFilter in that repo):

- GET /v1/symbols?q=&limit=   limit 1-200, no pagination
      {"symbols": [{ticker, name, source, firstBar, lastBar, lastClose}]}
- GET /v1/bars/{ticker}?from=&to=&after=&limit=&adjustment=split|raw
      limit 1-1000, adjustment defaults to split
      {ticker, source, adjustment, from, to,
       bars: [{date, open, high, low, close, volume}], nextAfter}
  Keyset pagination: while nextAfter is not null, ask again with after=nextAfter.
- `source` is "alpaca" or "synthetic", on every symbol and every page.
- Errors are RFC 9457 problem details (application/problem+json): title,
  status, detail, instance, and `errors: [{parameter, message}]` when a
  parameter fails validation.
- Without an X-API-Key header only public sources are visible (synthetic by
  default) and an Alpaca symbol is a 404, the same as an unknown one. A wrong
  key is a 401. Anonymous requests are rate-limited per client IP; a 429
  carries Retry-After in seconds, and successful responses carry
  X-RateLimit-Remaining.

This client only reads. It retries 429, 5xx, timeouts and connection errors
with backoff, honours Retry-After, follows the pagination, and checks every
response against the contract above: a response it can't trust is an error,
never a guess.
"""
from __future__ import annotations

import email.utils
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

API_KEY_HEADER = 'X-API-Key'
SOURCES = ('alpaca', 'synthetic')       # the service's symbols.source CHECK constraint
ADJUSTMENTS = ('split', 'raw')
DEFAULT_ADJUSTMENT = 'split'
MAX_PAGE_SIZE = 1000                    # MarketDataController.MAX_PAGE
MAX_SYMBOLS = 200                       # @Max(200) on /v1/symbols?limit
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Connect fast or fail; a page of 1,000 bars is small, but the service may be
# waking from a cold start
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class MarketDataError(Exception):
    """Any failure talking to the market-data service"""

    def __init__(self, message: str, *, status: Optional[int] = None, url: Optional[str] = None,
                 problem: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.problem = dict(problem or {})


class MarketDataBadRequest(MarketDataError):
    """400: the service rejected the parameters"""


class MarketDataUnauthorized(MarketDataError):
    """401/403: a wrong API key, or an endpoint that needs one"""


class MarketDataNotFound(MarketDataError):
    """404: unknown ticker, or an Alpaca ticker requested without an API key"""


class MarketDataRateLimited(MarketDataError):
    """429 that outlasted the retries, or a Retry-After longer than we wait"""

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class MarketDataUnavailable(MarketDataError):
    """5xx, timeouts or connection errors that outlasted the retries"""


class MarketDataContractError(MarketDataError):
    """A response that doesn't match the API contract"""


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class BarsPage:
    ticker: str
    source: str
    adjustment: str
    start: date          # `from` in the JSON
    end: date            # `to`
    bars: Tuple[Bar, ...]
    next_after: Optional[date]


@dataclass(frozen=True)
class BarSeries:
    """Every page of one request, joined"""
    ticker: str
    source: str
    adjustment: str
    start: date
    end: date
    bars: Tuple[Bar, ...]


@dataclass(frozen=True)
class SymbolSummary:
    ticker: str
    name: Optional[str]
    source: str
    first_bar: date
    last_bar: date
    last_close: float


# --- Parsing: strict, so a contract change fails loudly ----------------------

def _field(obj: Mapping[str, Any], key: str, where: str) -> Any:
    if not isinstance(obj, Mapping):
        raise MarketDataContractError(f'{where}: expected a JSON object, got {type(obj).__name__}')
    if key not in obj:
        raise MarketDataContractError(f'{where}: missing field "{key}"')
    return obj[key]


def _date(value: Any, where: str) -> date:
    if not isinstance(value, str):
        raise MarketDataContractError(f'{where}: expected a YYYY-MM-DD string, got {value!r}')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise MarketDataContractError(f'{where}: not a YYYY-MM-DD date: {value!r}') from None


def _number(value: Any, where: str) -> float:
    # bool is an int subclass; reject it explicitly
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MarketDataContractError(f'{where}: expected a number, got {value!r}')
    return float(value)


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataContractError(f'{where}: expected an integer, got {value!r}')
    return value


def _source(value: Any, where: str) -> str:
    if value not in SOURCES:
        # Never guess a label: an unknown source could be anything
        raise MarketDataContractError(f'{where}: unknown source {value!r}; expected one of {SOURCES}')
    return value


def parse_bar(obj: Mapping[str, Any], where: str = 'bar') -> Bar:
    bar = Bar(
        date=_date(_field(obj, 'date', where), f'{where}.date'),
        open=_number(_field(obj, 'open', where), f'{where}.open'),
        high=_number(_field(obj, 'high', where), f'{where}.high'),
        low=_number(_field(obj, 'low', where), f'{where}.low'),
        close=_number(_field(obj, 'close', where), f'{where}.close'),
        volume=_integer(_field(obj, 'volume', where), f'{where}.volume'),
    )
    if not (bar.low <= min(bar.open, bar.close) and max(bar.open, bar.close) <= bar.high):
        raise MarketDataContractError(f'{where}: OHLC out of range on {bar.date}')
    return bar


def parse_bars_page(payload: Any) -> BarsPage:
    """A /v1/bars/{ticker} response body"""
    where = 'bars page'
    adjustment = _field(payload, 'adjustment', where)
    if adjustment not in ADJUSTMENTS:
        raise MarketDataContractError(f'{where}: unknown adjustment {adjustment!r}')
    raw_bars = _field(payload, 'bars', where)
    if not isinstance(raw_bars, list):
        raise MarketDataContractError(f'{where}: "bars" is not a list')
    next_after = _field(payload, 'nextAfter', where)
    page = BarsPage(
        ticker=str(_field(payload, 'ticker', where)),
        source=_source(_field(payload, 'source', where), f'{where}.source'),
        adjustment=adjustment,
        start=_date(_field(payload, 'from', where), f'{where}.from'),
        end=_date(_field(payload, 'to', where), f'{where}.to'),
        bars=tuple(parse_bar(b, f'bars[{i}]') for i, b in enumerate(raw_bars)),
        next_after=None if next_after is None else _date(next_after, f'{where}.nextAfter'),
    )
    dates = [b.date for b in page.bars]
    if any(a >= b for a, b in zip(dates, dates[1:])):
        raise MarketDataContractError(f'{where}: bars are not in strictly increasing date order')
    if dates and (dates[0] < page.start or dates[-1] > page.end):
        raise MarketDataContractError(f'{where}: bars outside {page.start} to {page.end}')
    if page.next_after is not None and (not dates or page.next_after != dates[-1]):
        raise MarketDataContractError(f'{where}: nextAfter is not the last bar\'s date')
    return page


def parse_symbols(payload: Any) -> List[SymbolSummary]:
    """A /v1/symbols response body"""
    raw = _field(payload, 'symbols', 'symbols')
    if not isinstance(raw, list):
        raise MarketDataContractError('symbols: "symbols" is not a list')
    symbols = []
    for i, obj in enumerate(raw):
        where = f'symbols[{i}]'
        name = _field(obj, 'name', where)
        symbols.append(SymbolSummary(
            ticker=str(_field(obj, 'ticker', where)),
            name=None if name is None else str(name),
            source=_source(_field(obj, 'source', where), f'{where}.source'),
            first_bar=_date(_field(obj, 'firstBar', where), f'{where}.firstBar'),
            last_bar=_date(_field(obj, 'lastBar', where), f'{where}.lastBar'),
            last_close=_number(_field(obj, 'lastClose', where), f'{where}.lastClose'),
        ))
    return symbols


# --- HTTP ---------------------------------------------------------------------

def redact_url(url: str) -> str:
    """The URL without any user:password@ part, for logs, errors and cache keys"""
    parts = urlsplit(url)
    host = parts.hostname or ''
    if parts.port:
        host = f'{host}:{parts.port}'
    return urlunsplit((parts.scheme, host, parts.path.rstrip('/'), '', ''))


def parse_retry_after(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Retry-After as seconds: delta-seconds or an HTTP-date (RFC 9110 10.2.3)"""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


def _problem(response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class MarketDataClient:
    """
    Reads bars and symbols from the market-data service.

    Retries: 429, 500, 502, 503, 504, timeouts and connection errors, up to
    `max_retries` times. A Retry-After header sets the wait; without one the
    wait is "full jitter" exponential backoff, uniform in
    [0, min(max_backoff, backoff * 2**attempt)]. A Retry-After longer than
    `max_retry_after` is not waited out: the call fails at once with
    MarketDataRateLimited, which says how long to wait. Other 4xx responses
    are not retried.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = 4,
        backoff: float = 0.5,
        max_backoff: float = 30.0,
        max_retry_after: float = 120.0,
        page_size: int = MAX_PAGE_SIZE,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Optional[random.Random] = None,
    ):
        if not base_url or not base_url.startswith(('http://', 'https://')):
            raise ValueError(f'market-data base URL must start with http:// or https://, got {base_url!r}')
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f'page_size must be between 1 and {MAX_PAGE_SIZE}')
        self.base_url = redact_url(base_url)
        self.has_api_key = bool(api_key)
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.max_retry_after = max_retry_after
        self.page_size = page_size
        self._sleep = sleep
        self._rng = rng or random.Random()
        headers = {'Accept': 'application/json', 'User-Agent': 'quant-backtester'}
        if api_key:
            headers[API_KEY_HEADER] = api_key
        self._http = httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=timeout,
                                  transport=transport, follow_redirects=False)
        # Observability: requests made, retries taken, and the last
        # X-RateLimit-Remaining the service reported (None when it sends none,
        # e.g. for keyed requests, which are not limited)
        self.requests = 0
        self.retries = 0
        self.rate_limit_remaining: Optional[int] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, **kwargs) -> 'MarketDataClient':
        """MARKET_DATA_URL (required), MARKET_DATA_API_KEY, MARKET_DATA_TIMEOUT (read timeout, s)"""
        env = os.environ if env is None else env
        url = env.get('MARKET_DATA_URL', '').strip()
        if not url:
            raise ValueError('MARKET_DATA_URL is not set')
        if 'timeout' not in kwargs and env.get('MARKET_DATA_TIMEOUT'):
            kwargs['timeout'] = httpx.Timeout(connect=DEFAULT_TIMEOUT.connect, read=float(env['MARKET_DATA_TIMEOUT']),
                                              write=DEFAULT_TIMEOUT.write, pool=DEFAULT_TIMEOUT.pool)
        return cls(url, env.get('MARKET_DATA_API_KEY', '').strip() or None, **kwargs)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> 'MarketDataClient':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- endpoints -------------------------------------------------------

    def symbols(self, prefix: str = '', limit: int = MAX_SYMBOLS) -> List[SymbolSummary]:
        """Symbols this caller may see (all sources with a key, public ones without)"""
        params: Dict[str, Any] = {'limit': min(max(limit, 1), MAX_SYMBOLS)}
        if prefix:
            params['q'] = prefix
        return parse_symbols(self._get_json('/v1/symbols', params))

    def bars_page(self, ticker: str, start: date, end: date, *, after: Optional[date] = None,
                  adjustment: str = DEFAULT_ADJUSTMENT, limit: Optional[int] = None) -> BarsPage:
        """One page of daily bars for [start, end]"""
        if adjustment not in ADJUSTMENTS:
            raise ValueError(f'adjustment must be one of {ADJUSTMENTS}, got {adjustment!r}')
        params: Dict[str, Any] = {'from': start.isoformat(), 'to': end.isoformat(),
                                  'limit': limit or self.page_size, 'adjustment': adjustment}
        if after is not None:
            params['after'] = after.isoformat()
        page = parse_bars_page(self._get_json(f"/v1/bars/{quote(ticker, safe='')}", params))
        if page.ticker != ticker.upper():
            raise MarketDataContractError(f'asked for {ticker.upper()}, got {page.ticker}')
        if page.adjustment != adjustment:
            raise MarketDataContractError(f'asked for adjustment={adjustment}, got {page.adjustment}')
        if (page.start, page.end) != (start, end):
            raise MarketDataContractError(
                f'asked for {start} to {end}, the page says {page.start} to {page.end}')
        if after is not None and page.bars and page.bars[0].date <= after:
            raise MarketDataContractError(f'page after {after} starts on {page.bars[0].date}')
        return page

    def bars(self, ticker: str, start: date, end: date, *,
             adjustment: str = DEFAULT_ADJUSTMENT) -> BarSeries:
        """Every daily bar in [start, end], following nextAfter across pages"""
        if start > end:
            raise ValueError(f'start {start} is after end {end}')
        # A page holds at most page_size bars and there is at most one bar per
        # calendar day, so more pages than this means the cursor is looping
        max_pages = (end - start).days // self.page_size + 2
        pages: List[BarsPage] = []
        after: Optional[date] = None
        while True:
            if len(pages) == max_pages:
                raise MarketDataContractError(
                    f'{ticker}: more than {max_pages} pages for {start} to {end}; the cursor is not advancing')
            page = self.bars_page(ticker, start, end, after=after, adjustment=adjustment)
            if pages and page.source != pages[0].source:
                raise MarketDataContractError(
                    f'{ticker}: source changed between pages ({pages[0].source} -> {page.source})')
            pages.append(page)
            if page.next_after is None:
                break
            after = page.next_after
        return BarSeries(ticker=pages[0].ticker, source=pages[0].source, adjustment=adjustment,
                         start=start, end=end, bars=tuple(b for p in pages for b in p.bars))

    # --- transport -------------------------------------------------------

    def _backoff_delay(self, attempt: int) -> float:
        return self._rng.uniform(0.0, min(self.max_backoff, self.backoff * (2 ** attempt)))

    def _get_json(self, path: str, params: Mapping[str, Any]) -> Any:
        url = f'{self.base_url}{path}'
        attempt = 0
        while True:
            error: MarketDataError
            try:
                self.requests += 1
                response = self._http.get(path, params=params)
            except httpx.TimeoutException as e:
                error = MarketDataUnavailable(f'market-data timed out ({type(e).__name__}) on {url}', url=url)
                delay: Optional[float] = self._backoff_delay(attempt)
            except httpx.TransportError as e:
                error = MarketDataUnavailable(f'could not reach market-data at {url}: {e}', url=url)
                delay = self._backoff_delay(attempt)
            else:
                remaining = response.headers.get('X-RateLimit-Remaining')
                if remaining is not None and remaining.isdigit():
                    self.rate_limit_remaining = int(remaining)
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise MarketDataContractError(f'{url}: the response is not JSON', status=200, url=url)
                error = self._error(response, url)
                if response.status_code not in RETRY_STATUSES:
                    raise error
                retry_after = parse_retry_after(response.headers.get('Retry-After'))
                if retry_after is not None and retry_after > self.max_retry_after:
                    raise MarketDataRateLimited(
                        f'{error} The service asks to wait {retry_after:.0f} s, longer than '
                        f'{self.max_retry_after:.0f} s; try again later.',
                        retry_after=retry_after, status=response.status_code, url=url, problem=error.problem)
                delay = retry_after if retry_after is not None else self._backoff_delay(attempt)

            if attempt >= self.max_retries:
                raise error
            attempt += 1
            self.retries += 1
            log.warning('market-data: %s; retry %d of %d in %.2f s', error, attempt, self.max_retries, delay)
            self._sleep(delay)

    def _error(self, response: httpx.Response, url: str) -> MarketDataError:
        status = response.status_code
        problem = _problem(response)
        detail = problem.get('detail') or problem.get('title') or response.reason_phrase or f'HTTP {status}'
        errors = problem.get('errors')
        if isinstance(errors, list) and errors:
            detail += ' (' + '; '.join(
                f"{e.get('parameter')}: {e.get('message')}" for e in errors if isinstance(e, dict)) + ')'
        message = f'market-data {status}: {detail}'
        kwargs = dict(status=status, url=url, problem=problem)
        if status == 404:
            if not self.has_api_key:
                message += (' Without MARKET_DATA_API_KEY the service only shows its public sources'
                            ' (synthetic by default), so an Alpaca ticker is also a 404.')
            return MarketDataNotFound(message, **kwargs)
        if status in (401, 403):
            return MarketDataUnauthorized(message, **kwargs)
        if status == 429:
            return MarketDataRateLimited(message, retry_after=parse_retry_after(response.headers.get('Retry-After')),
                                         **kwargs)
        if status >= 500:
            return MarketDataUnavailable(message, **kwargs)
        if status == 400:
            return MarketDataBadRequest(message, **kwargs)
        return MarketDataError(message, **kwargs)
