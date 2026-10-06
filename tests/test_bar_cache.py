"""
BarCache (data_sources/cache.py) against the fake market-data service: hits,
fetching only missing ranges, the anchor check that catches re-based series,
the settle window for recent bars, source changes, and the keys.
"""
import sqlite3
from datetime import date

import pytest

from data_sources.cache import SCHEMA_VERSION, BarCache, merge, subtract
from data_sources.market_data import MarketDataClient
from tests.fake_market_data import FakeMarketData, weekday_bars

URL = 'http://market-data.test'
D = date.fromisoformat
TODAY = date(2025, 6, 30)   # far after the test bars, so they are all settled


@pytest.fixture
def fake():
    f = FakeMarketData()
    # 2024-01-01 (a Monday) to 2024-12-31: every weekday of 2024
    f.add('SYNA', 'synthetic', weekday_bars(D('2024-01-01'), 262))
    return f


@pytest.fixture
def client(fake):
    return MarketDataClient(URL, transport=fake.transport(), sleep=lambda s: None)


@pytest.fixture
def cache(tmp_path):
    return BarCache(tmp_path / 'bars.sqlite3', today=lambda: TODAY)


def bar_params(fake):
    return [(r.url.params['from'], r.url.params['to']) for r in fake.bar_requests()]


def test_ranges_subtract_and_merge():
    covered = [(D('2024-01-01'), D('2024-01-31')), (D('2024-03-01'), D('2024-03-31'))]
    assert subtract(D('2024-01-15'), D('2024-04-10'), covered) == [
        (D('2024-02-01'), D('2024-02-29')), (D('2024-04-01'), D('2024-04-10'))]
    assert subtract(D('2024-01-05'), D('2024-01-20'), covered) == []
    assert subtract(D('2023-12-01'), D('2023-12-31'), covered) == [(D('2023-12-01'), D('2023-12-31'))]
    assert merge([(D('2024-01-10'), D('2024-01-20')), (D('2024-01-01'), D('2024-01-09')),
                  (D('2024-02-01'), D('2024-02-02'))]) == [
        (D('2024-01-01'), D('2024-01-20')), (D('2024-02-01'), D('2024-02-02'))]


def test_second_request_is_a_cache_hit(fake, client, cache):
    first = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-03-31'))
    assert first.fetched == [(D('2024-01-01'), D('2024-03-31'))]
    requests = len(fake.requests)

    again = cache.get(client, 'SYNA', D('2024-02-01'), D('2024-02-29'))
    assert len(fake.requests) == requests and again.fetched == []
    assert [b.date for b in again.bars] == [b.date for b in first.bars if D('2024-02-01') <= b.date <= D('2024-02-29')]
    assert again.source == 'synthetic'


def test_extending_a_range_fetches_only_the_new_part_plus_one_anchor_bar(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-06-30'))   # ends on a Sunday; last bar Fri 06-28
    fake.requests.clear()

    series = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-12-31'))
    # the gap starts 07-01; the request starts at the last cached bar to compare it
    assert bar_params(fake) == [('2024-06-28', '2024-12-31')]
    assert len(series.bars) == 262 and not series.rebased


def test_a_hole_between_two_cached_ranges_is_the_only_fetch(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-03-31'))
    cache.get(client, 'SYNA', D('2024-07-01'), D('2024-09-30'))
    fake.requests.clear()

    series = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-09-30'))
    assert bar_params(fake) == [('2024-03-29', '2024-06-30')]   # Fri 03-29 is the anchor
    assert len(series.bars) == len([b for b in fake.series['SYNA']['split'] if b['date'] <= '2024-09-30'])
    assert cache.covered(URL, 'SYNA', 'split') == [(D('2024-01-01'), D('2024-09-30'))]


def test_a_distant_anchor_is_checked_with_a_one_day_request(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-01-31'))
    fake.requests.clear()

    cache.get(client, 'SYNA', D('2024-06-03'), D('2024-06-07'))
    assert bar_params(fake) == [('2024-06-03', '2024-06-07'), ('2024-01-31', '2024-01-31')]


def test_a_re_based_series_is_dropped_and_fetched_again(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-06-30'))
    # A 2-for-1 split on 2024-09-02: the service now halves every earlier split-adjusted price
    for bar in fake.series['SYNA']['split']:
        if bar['date'] < '2024-09-02':
            for k in ('open', 'high', 'low', 'close'):
                bar[k] = round(bar[k] / 2, 4)
    fake.requests.clear()

    series = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-12-31'))
    assert series.rebased
    # the extension saw the anchor change, then the whole range was fetched again
    assert bar_params(fake) == [('2024-06-28', '2024-12-31'), ('2024-01-01', '2024-12-31')]
    served = {b['date']: b['close'] for b in fake.series['SYNA']['split']}
    assert all(b.close == served[b.date.isoformat()] for b in series.bars)


def test_a_changed_source_drops_the_series(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-03-31'))
    fake.series['SYNA']['source'] = 'alpaca'
    fake.requests.clear()

    series = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-04-30'))
    assert series.rebased and series.source == 'alpaca'
    assert cache.source(URL, 'SYNA', 'split') == 'alpaca'
    assert bar_params(fake)[-1] == ('2024-01-01', '2024-04-30')


def test_recent_bars_are_cached_but_fetched_again_until_they_settle(fake, client, tmp_path):
    today = D('2024-12-31')
    cache = BarCache(tmp_path / 'bars.sqlite3', settle_days=7, today=lambda: today)
    first = cache.get(client, 'SYNA', D('2024-12-01'), D('2024-12-31'))
    assert first.bars[-1].date == D('2024-12-31')
    assert cache.covered(URL, 'SYNA', 'split') == [(D('2024-12-01'), D('2024-12-24'))]
    fake.requests.clear()

    cache.get(client, 'SYNA', D('2024-12-01'), D('2024-12-31'))
    assert bar_params(fake) == [('2024-12-24', '2024-12-31')]   # anchor Tue 12-24, then the unsettled week


def test_a_range_with_no_bars_is_remembered(fake, client, cache):
    weekend = cache.get(client, 'SYNA', D('2024-01-06'), D('2024-01-07'))
    assert weekend.bars == [] and weekend.source == 'synthetic'
    fake.requests.clear()
    cache.get(client, 'SYNA', D('2024-01-06'), D('2024-01-07'))
    assert fake.requests == []


def test_split_and_raw_and_services_are_separate_keys(fake, cache, tmp_path):
    fake.series['SYNA']['raw'] = [{**b, 'close': b['close'] * 2, 'high': b['high'] * 2, 'open': b['open'] * 2,
                                   'low': b['low'] * 2} for b in fake.series['SYNA']['split']]
    client = MarketDataClient(URL, transport=fake.transport())
    split = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-01-31'))
    raw = cache.get(client, 'SYNA', D('2024-01-01'), D('2024-01-31'), adjustment='raw')
    assert raw.bars[0].close == 2 * split.bars[0].close
    assert len(fake.bar_requests()) == 2

    other = MarketDataClient('http://other-market-data.test', transport=fake.transport())
    cache.get(other, 'SYNA', D('2024-01-01'), D('2024-01-31'))
    assert len(fake.bar_requests()) == 3
    assert {(r['service'], r['adjustment']) for r in cache.info()} == {
        (URL, 'split'), (URL, 'raw'), ('http://other-market-data.test', 'split')}


def test_clear_empties_the_cache(fake, client, cache):
    cache.get(client, 'SYNA', D('2024-01-01'), D('2024-01-31'))
    cache.clear()
    assert cache.info() == [] and cache.covered(URL, 'SYNA', 'split') == []


def test_an_old_schema_version_rebuilds_the_file(fake, client, tmp_path):
    path = tmp_path / 'bars.sqlite3'
    BarCache(path, today=lambda: TODAY).get(client, 'SYNA', D('2024-01-01'), D('2024-01-31'))
    with sqlite3.connect(path) as db:
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION + 1}')
    assert BarCache(path, today=lambda: TODAY).info() == []


def test_rejects_a_reversed_range(client, cache):
    with pytest.raises(ValueError):
        cache.get(client, 'SYNA', D('2024-02-01'), D('2024-01-01'))
