"""
Contract test: the client's parser against responses recorded from the real
market-data service.

Where the samples come from: tests/fixtures/market_data/*.json are verbatim
response bodies from lokaz-c/market-data at commit d70abcb (PR #4 head,
branch feat/perf-docker-deploy), run locally from its Docker image with
synthetic demo data only (DEMO_SEED=always, PUBLIC_DATA_SOURCES=synthetic, no
Alpaca keys), recorded with curl on 2026-10-06:

    bars_page_{1,2,3}.json     /v1/bars/S001?from=2024-01-02&to=2024-01-10&limit=3 [&after=...]
    bars_split_S007.json       /v1/bars/S007?from=2022-03-14&to=2022-03-17
    bars_raw_S007.json         the same with &adjustment=raw (a synthetic 1-for-3 split on 2022-03-16)
    symbols.json               /v1/symbols?limit=3
    problem_404.json           /v1/bars/NOPE
    problem_400_parameter.json /v1/bars/S001?limit=5000
    problem_400_range.json     /v1/bars/S001?from=2024-02-01&to=2024-01-01
    problem_429.json           /v1/symbols after the burst of 30 (sent with Retry-After: 1)

Their shapes are the service's DTO records (com.lokaz.marketdata.api.Dtos:
BarsPage, Bar, SymbolList, SymbolSummary) and RFC 9457 problem details
(ApiExceptionHandler, Problems). If the service changes a field, re-record
these and this test shows what broke.
"""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from data_sources.market_data import (
    MarketDataBadRequest, MarketDataClient, MarketDataNotFound, MarketDataRateLimited, parse_bars_page,
    parse_symbols,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'market_data'


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_bars_page_matches_the_dto():
    page = parse_bars_page(load('bars_page_1.json'))
    assert (page.ticker, page.source, page.adjustment) == ('S001', 'synthetic', 'split')
    assert (page.start, page.end) == (date(2024, 1, 2), date(2024, 1, 10))
    assert len(page.bars) == 3 and page.next_after == date(2024, 1, 4)
    first = page.bars[0]
    assert first.date == date(2024, 1, 2)
    assert (first.open, first.high, first.low, first.close) == (44.6398, 44.8072, 44.4495, 44.6149)
    assert first.volume == 3911527 and isinstance(first.volume, int)


def test_the_last_page_has_a_null_cursor():
    assert parse_bars_page(load('bars_page_3.json')).next_after is None


def test_the_client_joins_the_recorded_pages():
    pages = {None: 'bars_page_1.json', '2024-01-04': 'bars_page_2.json', '2024-01-09': 'bars_page_3.json'}

    def handler(request):
        assert request.url.path == '/v1/bars/S001'
        return httpx.Response(200, json=load(pages[request.url.params.get('after')]))

    client = MarketDataClient('http://md.test', page_size=3, transport=httpx.MockTransport(handler))
    series = client.bars('S001', date(2024, 1, 2), date(2024, 1, 10))
    assert series.source == 'synthetic'
    assert [b.date.isoformat() for b in series.bars] == [
        '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10']


def test_split_adjusted_and_raw_bars_differ_before_the_ex_date():
    split = parse_bars_page(load('bars_split_S007.json'))
    raw = parse_bars_page(load('bars_raw_S007.json'))
    assert (split.adjustment, raw.adjustment) == ('split', 'raw')
    for s, r in zip(split.bars, raw.bars):
        if s.date < date(2022, 3, 16):   # before the 1-for-3 split: prices / 3, volume * 3
            assert s.close == pytest.approx(r.close / 3, abs=1e-4)
            assert s.volume == pytest.approx(r.volume * 3, abs=2)
        else:
            assert (s.close, s.volume) == (r.close, r.volume)


def test_symbols_match_the_dto():
    symbols = parse_symbols(load('symbols.json'))
    assert [s.ticker for s in symbols] == ['S001', 'S002', 'S003']
    s = symbols[0]
    assert (s.name, s.source) == ('Synthetic 001', 'synthetic')
    assert (s.first_bar, s.last_bar, s.last_close) == (date(2020, 10, 5), date(2026, 10, 2), 61.1792)


def _client_answering(name, status, headers=None):
    def handler(request):
        return httpx.Response(status, content=(FIXTURES / name).read_bytes(),
                              headers={'Content-Type': 'application/problem+json', **(headers or {})})
    return MarketDataClient('http://md.test', transport=httpx.MockTransport(handler), max_retries=0)


def test_recorded_404_maps_to_not_found():
    with pytest.raises(MarketDataNotFound, match='Unknown ticker: NOPE') as error:
        _client_answering('problem_404.json', 404).bars('NOPE', date(2024, 1, 1), date(2024, 1, 5))
    assert error.value.problem == load('problem_404.json')


def test_recorded_400s_map_to_bad_request_with_the_parameter():
    with pytest.raises(MarketDataBadRequest, match='limit: must be less than or equal to 1000'):
        _client_answering('problem_400_parameter.json', 400).bars('S001', date(2024, 1, 1), date(2024, 1, 5))
    with pytest.raises(MarketDataBadRequest, match=r'from \(2024-02-01\) is after to'):
        _client_answering('problem_400_range.json', 400).bars('S001', date(2024, 1, 1), date(2024, 1, 5))


def test_recorded_429_carries_retry_after():
    client = _client_answering('problem_429.json', 429, headers={'Retry-After': '1'})
    with pytest.raises(MarketDataRateLimited, match='Rate limit of 60 requests per minute') as error:
        client.symbols()
    assert error.value.retry_after == 1.0
