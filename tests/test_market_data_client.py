"""
MarketDataClient against a fake market-data service (tests/fake_market_data.py,
through httpx.MockTransport) and, for timeouts and refused connections, real
sockets: pagination, split-adjusted by default, the API key, retries and
backoff, Retry-After, timeouts, error mapping and contract checks.
"""
import random
import socket
import threading
import time
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from data_sources.market_data import (
    API_KEY_HEADER, MarketDataBadRequest, MarketDataClient, MarketDataContractError, MarketDataNotFound,
    MarketDataRateLimited, MarketDataUnauthorized, MarketDataUnavailable, parse_retry_after, redact_url,
)
from tests.fake_market_data import FakeMarketData, problem, weekday_bars

URL = 'http://market-data.test'


class Sleeps(list):
    """Records requested sleeps instead of sleeping"""

    def __call__(self, seconds):
        self.append(seconds)


def client_for(fake, **kwargs):
    kwargs.setdefault('sleep', Sleeps())
    return MarketDataClient(URL, transport=fake.transport(), **kwargs)


@pytest.fixture
def fake():
    f = FakeMarketData()
    f.add('SYNA', 'synthetic', weekday_bars(date(2024, 1, 1), 25))
    return f


def test_follows_keyset_pagination_until_next_after_is_null(fake):
    client = client_for(fake, page_size=10)
    series = client.bars('SYNA', date(2024, 1, 1), date(2024, 3, 31))

    assert len(series.bars) == 25
    assert [b.date for b in series.bars] == sorted({b.date for b in series.bars})
    params = [dict(r.url.params) for r in fake.requests]
    assert len(params) == 3   # 10 + 10 + 5
    assert 'after' not in params[0]
    assert params[1]['after'] == series.bars[9].date.isoformat()
    assert params[2]['after'] == series.bars[19].date.isoformat()
    assert all(p['limit'] == '10' and p['from'] == '2024-01-01' and p['to'] == '2024-03-31' for p in params)


def test_split_adjusted_by_default_raw_on_request():
    fake = FakeMarketData()
    split = weekday_bars(date(2024, 1, 1), 3, base=100)
    raw = weekday_bars(date(2024, 1, 1), 3, base=400)
    fake.add('SPLT', 'synthetic', split, raw=raw)
    client = client_for(fake)

    assert client.bars('SPLT', date(2024, 1, 1), date(2024, 1, 5)).bars[0].close == 100.0
    assert fake.requests[-1].url.params['adjustment'] == 'split'
    raw_series = client.bars('SPLT', date(2024, 1, 1), date(2024, 1, 5), adjustment='raw')
    assert raw_series.bars[0].close == 400.0 and raw_series.adjustment == 'raw'
    assert fake.requests[-1].url.params['adjustment'] == 'raw'


def test_sends_the_api_key_only_when_configured(fake):
    client_for(fake).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert API_KEY_HEADER not in fake.requests[-1].headers

    client_for(fake, api_key='k-123').bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert fake.requests[-1].headers[API_KEY_HEADER] == 'k-123'


def test_from_env_reads_url_key_and_timeout(fake):
    client = MarketDataClient.from_env(
        {'MARKET_DATA_URL': URL + '/', 'MARKET_DATA_API_KEY': 'k', 'MARKET_DATA_TIMEOUT': '2.5'},
        transport=fake.transport())
    assert client.base_url == URL and client.has_api_key
    assert client._http.timeout.read == 2.5 and client._http.timeout.connect == 5.0
    with pytest.raises(ValueError, match='MARKET_DATA_URL'):
        MarketDataClient.from_env({})


def test_retries_5xx_with_backoff_then_succeeds(fake):
    fake.fail_next = [problem(503, 'Service Unavailable', 'warming up', '/v1/bars/SYNA'),
                      httpx.Response(502, text='bad gateway')]
    sleeps = Sleeps()
    client = client_for(fake, sleep=sleeps, backoff=0.5, rng=random.Random(1))
    series = client.bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))

    assert len(series.bars) == 5
    assert client.retries == 2 and len(fake.requests) == 3
    # full jitter: attempt n waits uniform(0, backoff * 2**n)
    assert 0 <= sleeps[0] <= 0.5 and 0 <= sleeps[1] <= 1.0


def test_429_waits_exactly_retry_after(fake):
    fake.fail_next = [problem(429, 'Too Many Requests', 'Rate limit of 60 requests per minute exceeded. '
                              'Retry in 3 s.', '/v1/bars/SYNA', headers={'Retry-After': '3'})]
    sleeps = Sleeps()
    client_for(fake, sleep=sleeps).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert sleeps == [3.0]


def test_a_retry_after_longer_than_the_cap_fails_at_once(fake):
    fake.fail_next = [problem(429, 'Too Many Requests', 'slow down', '/v1/bars/SYNA',
                              headers={'Retry-After': '600'})]
    sleeps = Sleeps()
    with pytest.raises(MarketDataRateLimited) as error:
        client_for(fake, sleep=sleeps, max_retry_after=60).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert error.value.retry_after == 600 and sleeps == []
    assert 'wait 600 s' in str(error.value)


def test_retry_after_as_an_http_date():
    now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after('Tue, 06 Oct 2026 12:00:07 GMT', now) == 7.0
    assert parse_retry_after('Tue, 06 Oct 2026 11:00:00 GMT', now) == 0.0
    assert parse_retry_after('12', now) == 12.0
    assert parse_retry_after('soon', now) is None and parse_retry_after(None) is None


def test_gives_up_after_max_retries_on_5xx(fake):
    fake.fail_next = [problem(503, 'Service Unavailable', 'database down', '/v1/bars/SYNA')] * 10
    client = client_for(fake, max_retries=2)
    with pytest.raises(MarketDataUnavailable, match='503: database down'):
        client.bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert len(fake.requests) == 3


def test_gives_up_on_a_429_that_keeps_coming(fake):
    fake.fail_next = [problem(429, 'Too Many Requests', 'slow down', '/v1/symbols',
                              headers={'Retry-After': '1'})] * 10
    sleeps = Sleeps()
    with pytest.raises(MarketDataRateLimited) as error:
        client_for(fake, sleep=sleeps, max_retries=3).symbols()
    assert sleeps == [1.0, 1.0, 1.0] and error.value.retry_after == 1.0


@pytest.mark.parametrize('response, error, text', [
    (problem(400, 'Bad Request', 'Invalid request parameters.', '/v1/bars/SYNA',
             errors=[{'message': 'must be less than or equal to 1000', 'parameter': 'limit'}]),
     MarketDataBadRequest, 'limit: must be less than or equal to 1000'),
    (problem(401, 'Unauthorized', 'The X-API-Key header is not a valid key.', '/v1/bars/SYNA'),
     MarketDataUnauthorized, 'not a valid key'),
    (problem(404, 'Not Found', 'Unknown ticker: SYNA', '/v1/bars/SYNA'),
     MarketDataNotFound, 'Unknown ticker: SYNA'),
], ids=['400', '401', '404'])
def test_client_errors_are_mapped_and_not_retried(fake, response, error, text):
    fake.fail_next = [response]
    with pytest.raises(error, match=text) as raised:
        client_for(fake).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))
    assert len(fake.requests) == 1
    assert raised.value.status == response.status_code
    assert raised.value.problem['instance'] == '/v1/bars/SYNA'


def test_a_404_without_a_key_explains_that_alpaca_symbols_need_one():
    fake = FakeMarketData(key='secret')
    fake.add('AAPL', 'alpaca', weekday_bars(date(2024, 1, 1), 5))
    with pytest.raises(MarketDataNotFound, match='MARKET_DATA_API_KEY'):
        client_for(fake).bars('AAPL', date(2024, 1, 1), date(2024, 1, 5))
    assert client_for(fake, api_key='secret').bars('AAPL', date(2024, 1, 1), date(2024, 1, 5)).source == 'alpaca'
    with pytest.raises(MarketDataUnauthorized):
        client_for(fake, api_key='wrong').bars('AAPL', date(2024, 1, 1), date(2024, 1, 5))


def test_an_error_body_that_is_not_json_still_gives_the_status(fake):
    fake.fail_next = [httpx.Response(418, text='<html>teapot</html>')]
    with pytest.raises(Exception, match="418: I'm a teapot"):
        client_for(fake).symbols()


def test_timeouts_are_retried_then_reported(fake):
    fake.fail_next = [httpx.ReadTimeout('read timed out')] * 10
    client = client_for(fake, max_retries=2)
    with pytest.raises(MarketDataUnavailable, match='timed out'):
        client.symbols()
    assert len(fake.requests) == 3


def test_a_timeout_then_success(fake):
    fake.fail_next = [httpx.ConnectTimeout('connect timed out')]
    assert client_for(fake).symbols()[0].ticker == 'SYNA'


class _SlowHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        time.sleep(0.5)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"symbols": []}')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


def test_read_timeout_on_a_real_socket():
    server = ThreadingHTTPServer(('127.0.0.1', 0), _SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = MarketDataClient(f'http://127.0.0.1:{server.server_port}', max_retries=1, sleep=Sleeps(),
                                  timeout=httpx.Timeout(0.1))
        started = time.monotonic()
        with pytest.raises(MarketDataUnavailable, match='ReadTimeout'):
            client.symbols()
        assert time.monotonic() - started < 0.5 * 2   # gave up on each attempt before the server answered
        assert _SlowHandler.calls == 2                 # one try plus one retry
    finally:
        server.shutdown()
        server.server_close()


def test_connection_refused_is_unavailable():
    with socket.socket() as s:   # a port nothing listens on
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    client = MarketDataClient(f'http://127.0.0.1:{port}', max_retries=0)
    with pytest.raises(MarketDataUnavailable, match='could not reach market-data'):
        client.symbols()


def test_records_the_rate_limit_remaining_header(fake):
    client = client_for(fake)
    client.symbols()
    assert client.rate_limit_remaining == 29


def test_backoff_stays_within_full_jitter_bounds():
    client = MarketDataClient(URL, backoff=0.5, max_backoff=4.0, rng=random.Random(7))
    for attempt in range(8):
        cap = min(4.0, 0.5 * 2 ** attempt)
        delays = [client._backoff_delay(attempt) for _ in range(200)]
        assert all(0 <= d <= cap for d in delays)
        assert max(delays) > cap * 0.8   # spread over the whole range, not pinned low


def _page(**overrides):
    body = {'ticker': 'SYNA', 'source': 'synthetic', 'adjustment': 'split', 'from': '2024-01-01',
            'to': '2024-01-05', 'nextAfter': None,
            'bars': [{'date': '2024-01-02', 'open': 10, 'high': 11, 'low': 9, 'close': 10.5, 'volume': 5}]}
    body.update(overrides)
    return httpx.Response(200, json=body)


@pytest.mark.parametrize('response, text', [
    (_page(source='polygon'), "unknown source 'polygon'"),
    (_page(adjustment='raw'), 'asked for adjustment=split'),
    (_page(ticker='OTHR'), 'asked for SYNA, got OTHR'),
    (_page(**{'from': '2023-01-01'}), 'the page says 2023-01-01'),
    (_page(bars=[{'date': '2024-01-03', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1},
                 {'date': '2024-01-02', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]),
     'strictly increasing'),
    (_page(bars=[{'date': '2024-01-02', 'open': 1, 'high': 1, 'low': 1, 'close': '1', 'volume': 1}]),
     'expected a number'),
    (_page(bars=[{'date': '2024-01-02', 'open': 1, 'high': 1, 'low': 1, 'volume': 1}]), 'missing field "close"'),
    (_page(bars=[{'date': '2024-01-02', 'open': 5, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]),
     'OHLC out of range'),
    (_page(nextAfter='2024-01-04'), "nextAfter is not the last bar's date"),
    (httpx.Response(200, text='<html>proxy login</html>'), 'not JSON'),
], ids=['unknown-source', 'adjustment', 'ticker', 'range', 'order', 'string-price', 'missing', 'ohlc',
        'cursor', 'not-json'])
def test_responses_outside_the_contract_are_errors(fake, response, text):
    fake.fail_next = [response]
    with pytest.raises(MarketDataContractError, match=text):
        client_for(fake).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))


def test_a_cursor_that_does_not_advance_is_caught(fake):
    stuck = {'ticker': 'SYNA', 'source': 'synthetic', 'adjustment': 'split', 'from': '2024-01-01',
             'to': '2024-01-05', 'nextAfter': '2024-01-02',
             'bars': [{'date': '2024-01-02', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]}
    fake.fail_next = [httpx.Response(200, json=stuck)] * 5
    with pytest.raises(MarketDataContractError, match='page after 2024-01-02 starts on 2024-01-02'):
        client_for(fake).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))


def test_a_source_that_changes_between_pages_is_caught(fake):
    first = {'ticker': 'SYNA', 'source': 'synthetic', 'adjustment': 'split', 'from': '2024-01-01',
             'to': '2024-01-05', 'nextAfter': '2024-01-02',
             'bars': [{'date': '2024-01-02', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]}
    second = {**first, 'source': 'alpaca', 'nextAfter': None,
              'bars': [{'date': '2024-01-03', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]}
    fake.fail_next = [httpx.Response(200, json=first), httpx.Response(200, json=second)]
    with pytest.raises(MarketDataContractError, match='source changed between pages'):
        client_for(fake).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5))


def test_urls_in_messages_and_keys_have_no_credentials():
    assert redact_url('https://user:pw@md.example.com:8443/base/') == 'https://md.example.com:8443/base'
    assert MarketDataClient('https://user:pw@md.example.com').base_url == 'https://md.example.com'


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        MarketDataClient('md.example.com')
    with pytest.raises(ValueError):
        MarketDataClient(URL, page_size=5000)
    with pytest.raises(ValueError):
        MarketDataClient(URL).bars('SYNA', date(2024, 1, 1), date(2024, 1, 5), adjustment='dividend')
