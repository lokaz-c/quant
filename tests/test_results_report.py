"""
The benchmark report (scripts/results.py, `make results`) must be reproducible.
This uses a small configuration so it stays fast; CI also regenerates the full
docs/results.md and fails if it differs from the committed file.
"""
from scripts.results import BenchmarkConfig, render, run_benchmarks

SMALL = BenchmarkConfig(
    symbols=('AAPL', 'MSFT'),
    start_date='2023-01-01',
    end_date='2023-12-31',
    strategies=('Moving Average Crossover', 'Trend Following'),
    risk_profiles=('No Risk Management', 'Conservative'),
)


def test_report_is_byte_identical_across_runs():
    first = render(SMALL, run_benchmarks(SMALL))
    second = render(SMALL, run_benchmarks(SMALL))
    assert first == second


def test_report_states_synthetic_data_and_the_command():
    report = render(SMALL, run_benchmarks(SMALL))
    assert '**The data is synthetic.**' in report
    assert '`make results`' in report
    assert 'seed 42' in report
    # one results row per strategy x profile
    assert report.count('| Moving Average Crossover | ') >= 2
