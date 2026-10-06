"""
An in-process fake of the market-data service, for httpx.MockTransport.

It implements the parts of the API the client uses, the way the service
does (MarketDataService and MarketDataController in lokaz-c/market-data):

- GET /v1/bars/{ticker}: from/to/after/limit/adjustment, keyset pages of
  `limit` rows with nextAfter = the last row's date when more rows exist
  (the service reads limit + 1 rows to find out); `source` on every page.
- GET /v1/symbols: ticker, name, source, firstBar, lastBar, lastClose.
- Visibility: with `key` set, alpaca symbols need X-API-Key == key, a wrong
  key is a 401, and without a key an alpaca symbol is the same 404 as an
  unknown one.
- Errors as RFC 9457 problem details.

`fail_next` queues responses (or exceptions) that are returned before normal
handling, to test retries. Every request is kept in `requests`.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

import httpx

from backtest_engine.data_loader import generate_sample_data


def problem(status: int, title: str, detail: str, instance: str, headers: Optional[dict] = None,
            **extra) -> httpx.Response:
    body = {'title': title, 'status': status, 'detail': detail, 'instance': instance, **extra}
    return httpx.Response(status, json=body, headers={'Content-Type': 'application/problem+json',
                                                      **(headers or {})})


def weekday_bars(start: date, count: int, base: float = 100.0) -> List[dict]:
    """`count` bars on consecutive weekdays from `start`; prices rise 0.5 a day"""
    bars, day = [], start
    while len(bars) < count:
        if day.weekday() < 5:
            close = round(base + 0.5 * len(bars), 4)
            bars.append({'date': day.isoformat(), 'open': close, 'high': round(close + 1, 4),
                         'low': round(close - 1, 4), 'close': close, 'volume': 1000 + len(bars)})
        day += timedelta(days=1)
    return bars


def generated_bars(symbols: Sequence[str], start: str, end: str) -> Dict[str, List[dict]]:
    """Bars from the seeded generator, so backtests have something to trade"""
    df = generate_sample_data(list(symbols), start, end)
    out: Dict[str, List[dict]] = {}
    for symbol, rows in df.groupby('symbol'):
        out[symbol] = [{'date': ts.date().isoformat(), 'open': float(o), 'high': float(h), 'low': float(lo),
                        'close': float(c), 'volume': int(v)}
                       for ts, o, h, lo, c, v in zip(rows['timestamp'], rows['open'], rows['high'],
                                                     rows['low'], rows['close'], rows['volume'])]
    return out


class FakeMarketData:
    def __init__(self, key: Optional[str] = None):
        self.key = key
        self.series: Dict[str, dict] = {}
        self.requests: List[httpx.Request] = []
        self.fail_next: List[object] = []

    def add(self, ticker: str, source: str, bars: List[dict], raw: Optional[List[dict]] = None) -> None:
        self.series[ticker] = {'source': source, 'split': list(bars), 'raw': list(raw if raw is not None else bars)}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def bar_requests(self, ticker: Optional[str] = None) -> List[httpx.Request]:
        prefix = '/v1/bars/' + (ticker or '')
        return [r for r in self.requests if r.url.path.startswith(prefix)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            failure = self.fail_next.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        path = request.url.path
        given = request.headers.get('X-API-Key')
        if given is not None and self.key is not None and given != self.key:
            return problem(401, 'Unauthorized', 'The X-API-Key header is not a valid key.', path)
        visible = {'alpaca', 'synthetic'} if given is not None else {'synthetic'}
        if self.key is None:
            visible = {'alpaca', 'synthetic'}   # a fake without keys shows everything
        if path == '/v1/symbols':
            return self._symbols(request, visible)
        if path.startswith('/v1/bars/'):
            return self._bars(request, path[len('/v1/bars/'):].upper(), visible)
        return problem(404, 'Not Found', 'No static resource.', path)

    def _symbols(self, request: httpx.Request, visible: set) -> httpx.Response:
        prefix = request.url.params.get('q', '').upper()
        limit = int(request.url.params.get('limit', '50'))
        rows = []
        for ticker in sorted(self.series):
            s = self.series[ticker]
            if s['source'] in visible and ticker.startswith(prefix) and s['split']:
                rows.append({'ticker': ticker, 'name': None, 'source': s['source'],
                             'firstBar': s['split'][0]['date'], 'lastBar': s['split'][-1]['date'],
                             'lastClose': s['split'][-1]['close']})
        return httpx.Response(200, json={'symbols': rows[:limit]},
                              headers={'X-RateLimit-Remaining': '29', 'Cache-Control': 'max-age=300, public'})

    def _bars(self, request: httpx.Request, ticker: str, visible: set) -> httpx.Response:
        path = request.url.path
        s = self.series.get(ticker)
        if s is None or s['source'] not in visible:
            return problem(404, 'Not Found', f'Unknown ticker: {ticker}', path)
        params = request.url.params
        adjustment = params.get('adjustment', 'split')
        limit = int(params.get('limit', '500'))
        if limit > 1000:
            return problem(400, 'Bad Request', 'Invalid request parameters.', path,
                           errors=[{'message': 'must be less than or equal to 1000', 'parameter': 'limit'}])
        start, end = date.fromisoformat(params['from']), date.fromisoformat(params['to'])
        if start > end:
            return problem(400, 'Bad Request', f'from ({start}) is after to ({end}).', path)
        after = params.get('after')
        lower = start if after is None or date.fromisoformat(after) < start \
            else date.fromisoformat(after) + timedelta(days=1)
        rows = [b for b in s[adjustment] if lower <= date.fromisoformat(b['date']) <= end][:limit + 1]
        next_after = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_after = rows[-1]['date']
        return httpx.Response(200, json={
            'ticker': ticker, 'source': s['source'], 'adjustment': adjustment,
            'from': start.isoformat(), 'to': end.isoformat(), 'bars': rows, 'nextAfter': next_after,
        }, headers={'X-RateLimit-Remaining': '28'})

