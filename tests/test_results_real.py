"""
`make results-real` (scripts/results.py --data-source market-data) against the
fake market-data service, with a small configuration so it stays fast:

- it says "real" only when the service reported alpaca for every symbol;
- it refuses to write synthetic data unless --allow-synthetic, and then
  labels it synthetic;
- `make results` (no flag) stays on the synthetic file even with
  MARKET_DATA_URL set.
"""
import pytest

from data_sources import sources
from scripts import results
from scripts.results import BenchmarkConfig
from tests.fake_market_data import FakeMarketData, generated_bars

URL = 'http://market-data.test'
SMALL = BenchmarkConfig(
    symbols=('AAPL', 'MSFT'),
    start_date='2023-01-01',
    end_date='2023-12-31',
    strategies=('Moving Average Crossover',),
    risk_profiles=('No Risk Management', 'Conservative'),
)
BARS = generated_bars(['AAPL', 'MSFT'], '2023-01-01', '2023-12-31')


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fake = FakeMarketData()
    monkeypatch.setenv('MARKET_DATA_URL', URL)
    monkeypatch.setenv('MARKET_DATA_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(results, 'BenchmarkConfig', lambda: SMALL)
    real_open = sources.open_source
    monkeypatch.setattr(results, 'open_source',
                        lambda config, name: real_open(config, name, transport=fake.transport()))
    return fake


def test_alpaca_bars_give_a_report_labelled_real(fake, tmp_path):
    fake.add('AAPL', 'alpaca', BARS['AAPL'])
    fake.add('MSFT', 'alpaca', BARS['MSFT'])
    out = tmp_path / 'results-real.md'
    assert results.main(['--data-source', 'market-data', '--output', str(out)]) == 0

    report = out.read_text()
    assert '**Data: daily bars from Alpaca, served by the market-data service, split-adjusted.**' in report
    assert 'synthetic' not in report.split('## Setup')[0]
    assert '- Source reported by the service: AAPL alpaca, MSFT alpaca' in report
    assert 'sha256 of the bars used' in report and '`make results-real`' in report
    assert '| Moving Average Crossover | Conservative |' in report
    assert '## Returns by regime' not in report


def test_synthetic_bars_are_refused_unless_allowed_and_then_labelled(fake, tmp_path, capsys):
    fake.add('AAPL', 'synthetic', BARS['AAPL'])
    fake.add('MSFT', 'alpaca', BARS['MSFT'])
    out = tmp_path / 'results-real.md'
    assert results.main(['--data-source', 'market-data', '--output', str(out)]) == 1
    assert not out.exists()
    assert 'reported mixed data' in capsys.readouterr().err

    assert results.main(['--data-source', 'market-data', '--output', str(out), '--allow-synthetic']) == 0
    report = out.read_text()
    assert report.count('**The data is synthetic.**') == 1
    assert 'reported source `synthetic` for AAPL, and `alpaca` for the others' in report
    assert "Alpaca's IEX feed" not in report


def test_the_same_bars_give_the_same_report(fake, tmp_path):
    fake.add('AAPL', 'alpaca', BARS['AAPL'])
    fake.add('MSFT', 'alpaca', BARS['MSFT'])
    first, second = tmp_path / 'a.md', tmp_path / 'b.md'
    results.main(['--data-source', 'market-data', '--output', str(first)])
    results.main(['--data-source', 'market-data', '--output', str(second)])
    assert first.read_text() == second.read_text()


def test_without_a_service_url_it_explains_and_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv('MARKET_DATA_URL', raising=False)
    monkeypatch.setattr(results, 'BenchmarkConfig', lambda: SMALL)
    assert results.main(['--data-source', 'market-data', '--output', str(tmp_path / 'r.md')]) == 1
    assert 'MARKET_DATA_URL is not set' in capsys.readouterr().err


def test_an_unknown_ticker_explains_the_api_key(fake, tmp_path, capsys):
    fake.add('MSFT', 'synthetic', BARS['MSFT'])
    assert results.main(['--data-source', 'market-data', '--output', str(tmp_path / 'r.md')]) == 1
    assert 'Unknown ticker: AAPL' in capsys.readouterr().err


def test_make_results_ignores_market_data_settings(fake, tmp_path):
    out = tmp_path / 'results.md'
    assert results.main(['--output', str(out)]) == 0
    assert out.read_text() == results.render(SMALL, results.run_benchmarks(SMALL))
    assert fake.requests == []
