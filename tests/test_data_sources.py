"""
The data source switch (DataConfig), the provenance a run records, and the
market-data source that turns the client's bars into the engine's frame.
"""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from data_sources import sources
from data_sources.market_data import MarketDataClient
from data_sources.sources import (
    DEFAULT_CACHE_DIR, DataConfig, DataSourceError, InMemoryLoader, MarketDataSource, NoBars, Provenance,
    summarize_sources,
)
from tests.fake_market_data import FakeMarketData, weekday_bars

URL = 'http://market-data.test'


@pytest.fixture(autouse=True)
def fresh_symbol_memo():
    sources._symbols_memo.clear()
    yield
    sources._symbols_memo.clear()


# --- the switch ---------------------------------------------------------------

def test_synthetic_is_the_default_without_a_market_data_url():
    config = DataConfig.from_env({})
    assert config.default_source == 'synthetic' and config.available == ['synthetic']
    with pytest.raises(DataSourceError, match='not configured'):
        config.resolve('market-data')


def test_market_data_is_the_default_when_its_url_is_set():
    config = DataConfig.from_env({'MARKET_DATA_URL': URL})
    assert config.default_source == 'market-data'
    assert config.available == ['synthetic', 'market-data']
    assert config.resolve(None) == 'market-data' and config.resolve('synthetic') == 'synthetic'
    assert config.adjustment == 'split' and config.cache_dir == DEFAULT_CACHE_DIR


def test_synthetic_can_be_chosen_explicitly_with_a_url_set():
    config = DataConfig.from_env({'MARKET_DATA_URL': URL, 'QUANT_DATA_SOURCE': 'synthetic'})
    assert config.default_source == 'synthetic' and 'market-data' in config.available


@pytest.mark.parametrize('env, message', [
    ({'QUANT_DATA_SOURCE': 'market-data'}, 'needs MARKET_DATA_URL'),
    ({'QUANT_DATA_SOURCE': 'alpaca'}, 'must be one of'),
    ({'MARKET_DATA_URL': URL, 'MARKET_DATA_ADJUSTMENT': 'dividend'}, 'split or raw'),
])
def test_bad_configuration_is_rejected(env, message):
    with pytest.raises(DataSourceError, match=message):
        DataConfig.from_env(env)


def test_cache_dir_and_key_settings():
    config = DataConfig.from_env({'MARKET_DATA_URL': URL, 'MARKET_DATA_CACHE_DIR': 'off',
                                  'MARKET_DATA_API_KEY': 'secret-key', 'MARKET_DATA_ADJUSTMENT': 'raw'})
    assert config.cache_dir is None and config.cache() is None and config.adjustment == 'raw'
    assert 'secret-key' not in repr(config)
    assert DataConfig.from_env({'MARKET_DATA_CACHE_DIR': '/tmp/x'}).cache_dir == Path('/tmp/x')


def test_unknown_data_source_in_a_request_is_rejected():
    with pytest.raises(DataSourceError, match='data_source must be one of'):
        DataConfig.from_env({}).resolve('yahoo')


# --- provenance and labelling ------------------------------------------------

def test_summarize_sources():
    assert summarize_sources({'AAPL': 'alpaca', 'MSFT': 'alpaca'}) == 'alpaca'
    assert summarize_sources({'S001': 'synthetic'}) == 'synthetic'
    assert summarize_sources({'AAPL': 'alpaca', 'S001': 'synthetic'}) == 'mixed'
    with pytest.raises(ValueError, match='unknown source'):
        summarize_sources({'X': 'polygon'})
    with pytest.raises(ValueError):
        summarize_sources({})


def test_only_market_data_bars_labelled_alpaca_count_as_real():
    real = Provenance.from_market_data({'AAPL': 'alpaca', 'MSFT': 'alpaca'}, 'split')
    assert real.real and real.to_api()['synthetic'] is False
    assert "Alpaca's IEX feed" in real.description()

    served_synthetic = Provenance.from_market_data({'S001': 'synthetic'}, 'split')
    assert not served_synthetic.real and served_synthetic.to_api()['synthetic'] is True
    assert 'source=synthetic' in served_synthetic.description()

    mixed = Provenance.from_market_data({'AAPL': 'alpaca', 'S001': 'synthetic'}, 'split')
    assert mixed.reported_source == 'mixed' and not mixed.real
    assert 'S001' in mixed.description() and mixed.to_api()['synthetic'] is True

    local = Provenance.local_synthetic()
    assert not local.real and local.to_api() == {
        'source': 'synthetic', 'reported_source': 'synthetic', 'synthetic': True,
        'description': sources.SYNTHETIC_DESCRIPTION, 'file': 'data/sample_data.csv'}


@pytest.mark.parametrize('kwargs', [
    dict(data_source='synthetic', reported_source='alpaca'),
    dict(data_source='market-data', reported_source='alpaca', symbol_sources={'S001': 'synthetic'}),
    dict(data_source='market-data', reported_source='real'),
    dict(data_source='csv', reported_source='synthetic'),
], ids=['local-claims-alpaca', 'summary-disagrees', 'unknown-reported', 'unknown-source'])
def test_inconsistent_provenance_cannot_be_built(kwargs):
    with pytest.raises(ValueError):
        Provenance(**kwargs)


def test_alpaca_without_per_symbol_sources_is_not_real():
    assert not Provenance(data_source='market-data', reported_source='alpaca').real


# --- the market-data source ---------------------------------------------------

@pytest.fixture
def fake():
    f = FakeMarketData()
    f.add('S001', 'synthetic', weekday_bars(date(2024, 1, 1), 20, base=50))
    f.add('AAPL', 'alpaca', weekday_bars(date(2024, 1, 1), 20, base=180))
    return f


def source_for(fake, tmp_path=None):
    client = MarketDataClient(URL, transport=fake.transport())
    cache = sources.BarCache(tmp_path / 'c.sqlite3') if tmp_path else None
    return MarketDataSource(client, cache)


def test_load_builds_the_engine_frame_and_provenance(fake, tmp_path):
    loaded = source_for(fake, tmp_path).load(['AAPL', 'S001'], date(2024, 1, 1), date(2024, 1, 31))
    frame = loaded.frame
    assert list(frame.columns) == ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
    assert len(frame) == 40 and frame['timestamp'].is_monotonic_increasing
    assert pd.api.types.is_datetime64_any_dtype(frame['timestamp'])
    assert loaded.provenance == Provenance.from_market_data({'AAPL': 'alpaca', 'S001': 'synthetic'}, 'split')
    # the Backtester reads it through the same interface as the CSV loader
    assert set(loaded.loader.load_csv(['AAPL'])['symbol']) == {'AAPL'}


def test_load_with_no_bars_in_range_is_an_error(fake):
    with pytest.raises(NoBars):
        source_for(fake).load(['S001'], date(2025, 1, 1), date(2025, 1, 31))


def test_info_lists_symbols_with_their_reported_source(fake):
    info = source_for(fake).info()
    assert info['source'] == 'market-data' and info['reported_source'] == 'mixed'
    assert info['symbols'] == ['AAPL', 'S001'] and info['synthetic'] is True
    assert info['symbol_sources'] == {'AAPL': 'alpaca', 'S001': 'synthetic'}
    assert (info['start_date'], info['bars']) == ('2024-01-01', None)


def test_symbol_listing_is_memoised(fake):
    source = source_for(fake)
    source.symbols()
    source.symbols()
    assert len([r for r in fake.requests if r.url.path == '/v1/symbols']) == 1


def test_in_memory_loader_filters_and_sorts_like_the_csv_loader():
    frame = pd.DataFrame({'timestamp': pd.to_datetime(['2024-01-03', '2024-01-02', '2024-01-02']),
                          'symbol': ['B', 'B', 'A'], 'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0,
                          'volume': 1})
    loaded = InMemoryLoader(frame).load_csv(['B'])
    assert list(loaded['timestamp'].dt.day) == [2, 3] and set(loaded['symbol']) == {'B'}


# --- the command line ---------------------------------------------------------

def test_cli_cache_info_and_clear(monkeypatch, tmp_path, capsys, fake):
    from data_sources.__main__ import main
    monkeypatch.setenv('MARKET_DATA_CACHE_DIR', str(tmp_path))
    cache = sources.BarCache.in_dir(tmp_path)
    cache.get(MarketDataClient(URL, transport=fake.transport()), 'S001', date(2024, 1, 1), date(2024, 1, 31))

    assert main(['cache', 'info']) == 0
    out = capsys.readouterr().out
    assert '1 series' in out and 'S001' in out and 'synthetic' in out
    assert main(['cache', 'clear']) == 0 and cache.info() == []


def test_cli_explains_missing_configuration(monkeypatch, capsys):
    from data_sources.__main__ import main
    monkeypatch.delenv('MARKET_DATA_URL', raising=False)
    assert main(['symbols']) == 1
    assert 'MARKET_DATA_URL is not set' in capsys.readouterr().err
    monkeypatch.setenv('MARKET_DATA_CACHE_DIR', 'off')
    assert main(['cache', 'info']) == 0
    assert 'The cache is off' in capsys.readouterr().out
