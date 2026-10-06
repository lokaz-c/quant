"""
Benchmark backtests -> docs/results.md (synthetic) or docs/results-real.md

Runs every strategy without the risk layer and under each risk profile in
config/risk_configs.json, on a fixed slice of data, and writes a Markdown
report.

    make results        # python -m scripts.results
    make results-real   # python -m scripts.results --data-source market-data

`make results` always uses the seeded synthetic sample file, whatever
QUANT_DATA_SOURCE or MARKET_DATA_URL say: nothing in that run is random and
the report has no timestamps, so it is reproducible byte for byte, and CI
checks it. `make results-real` runs the same benchmark on bars from the
market-data service (MARKET_DATA_URL, MARKET_DATA_API_KEY) and refuses to
write docs/results-real.md unless the service reports Alpaca data for every
symbol (--allow-synthetic writes it anyway, labelled synthetic).
"""
import argparse
import contextlib
import hashlib
import io
import json
import sys
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

from backtest_engine.backtester import Backtester
from backtest_engine.data_loader import DEFAULT_SEED, DataLoader
from data_sources.market_data import MarketDataError
from data_sources.sources import (
    DATA_SOURCES, MARKET_DATA, SYNTHETIC, DataConfig, DataSourceError, LoadedBars, NoBars, open_source,
)
from backtest_engine.metrics import returns_by_regime
from backtest_engine.regimes import DEFAULT_CONFIG_PATH, RegimeModel
from backtest_engine.risk import RiskConfig
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from backtest_engine.strategies.rsi_strategy import RSIMeanReversion
from backtest_engine.strategies.trend_following import TrendFollowing

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMAND = 'make results'
REAL_COMMAND = 'make results-real'

STRATEGIES = {
    'Moving Average Crossover': MovingAverageCrossover,
    'RSI Mean Reversion': RSIMeanReversion,
    'Trend Following': TrendFollowing,
}


@dataclass(frozen=True)
class BenchmarkConfig:
    data_path: Path = REPO_ROOT / 'data' / 'sample_data.csv'
    symbols: Sequence[str] = ('AAPL', 'AMZN', 'GOOGL', 'JPM', 'MSFT')
    start_date: str = '2020-01-01'
    end_date: str = '2024-12-31'
    initial_capital: float = 100_000.0
    strategies: Sequence[str] = tuple(STRATEGIES)
    # None = every profile in config/risk_configs.json, the baseline first
    risk_profiles: Optional[Sequence[str]] = None


@dataclass
class Run:
    strategy: str
    risk_profile: str
    metrics: Dict
    by_regime: Dict = field(default_factory=dict)


def load_risk_profiles(names: Optional[Sequence[str]] = None) -> List[RiskConfig]:
    with open(REPO_ROOT / 'config' / 'risk_configs.json') as f:
        raw = json.load(f).values()
    profiles = [RiskConfig(**entry) for entry in raw]
    profiles.sort(key=lambda p: p.enabled)  # baseline (risk layer off) first, then file order
    if names is not None:
        profiles = [p for p in profiles if p.name in names]
    return profiles


def run_benchmarks(config: BenchmarkConfig, bars: Optional[LoadedBars] = None) -> List[Run]:
    """Every strategy x profile on the synthetic file, or on `bars` (market-data) if given"""
    if bars is None:
        data = DataLoader(str(config.data_path)).load_csv(list(config.symbols))
        data = data[(data['timestamp'] >= config.start_date) & (data['timestamp'] <= config.end_date)]
        regime_by_date: Optional[Dict] = (
            data.drop_duplicates('timestamp').set_index('timestamp')['regime'].to_dict())
    else:
        regime_by_date = None   # real bars carry no regime labels
    regime_order = RegimeModel.from_json(DEFAULT_CONFIG_PATH).names

    runs = []
    for strategy_name in config.strategies:
        for profile in load_risk_profiles(config.risk_profiles):
            backtester = Backtester(
                strategy=STRATEGIES[strategy_name](),
                data_loader=DataLoader(str(config.data_path)) if bars is None else bars.loader,
                initial_capital=config.initial_capital,
                risk_config=profile,
                start_date=config.start_date,
                end_date=config.end_date,
                symbols=list(config.symbols),
            )
            with contextlib.redirect_stdout(io.StringIO()):  # the engine prints progress
                results = backtester.run()
            runs.append(Run(
                strategy=strategy_name,
                risk_profile=profile.name,
                metrics=results['metrics'],
                by_regime=(returns_by_regime(results['equity_curve'], regime_by_date, regime_order)
                           if regime_by_date is not None else {}),
            ))
    return runs


# An undefined metric (None; e.g. Sharpe with zero volatility, win rate with
# no trades) prints as n/a. The benchmark runs have none.
NOT_AVAILABLE = 'n/a'


def _pct(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f'{value:.2f}%'


def _signed_pct(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f'{value:+.2f}'


def _ratio(value: Optional[float], sign: str = '') -> str:
    return NOT_AVAILABLE if value is None else f'{value:{sign}.2f}'


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else a - b


def _fmt_opt(value: Optional[float]) -> str:
    return '-' if value is None else f'{value * 100:g}%'


def _method_lines(config: BenchmarkConfig) -> List[str]:
    """Setup lines shared by both reports: capital, fills, parameters, Sharpe"""
    return [
        f'- Initial capital: ${config.initial_capital:,.0f}. Orders fill at the signal bar\'s close; '
        'no commissions, slippage or partial fills. Long only.',
        '- Strategy parameters (code defaults): MA crossover 20/50; RSI 14 with 30/70 thresholds; '
        'Trend Following 20-day channel with a 2 x ATR(14) chandelier stop. Each new position is '
        '20% of equity before risk caps.',
        '- Sharpe uses daily returns, a 2% annual risk-free rate and sqrt(252) annualisation. '
        'Idle cash earns no interest, which lowers Sharpe for strategies that sit in cash.',
    ]


def _profile_lines(profiles: List[RiskConfig]) -> List[str]:
    lines = [
        '',
        'Risk profiles (`config/risk_configs.json`):',
        '',
        '| Profile | Risk layer | Max position | Max exposure | Stop-loss | Take-profit | Halt at drawdown |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for p in profiles:
        if p.enabled:
            lines.append(f'| {p.name} | on | {_fmt_opt(p.max_position_size)} | {_fmt_opt(p.max_portfolio_exposure)} | '
                         f'{_fmt_opt(p.stop_loss_pct)} | {_fmt_opt(p.take_profit_pct)} | {_fmt_opt(p.max_drawdown_pct)} |')
        else:
            lines.append(f'| {p.name} | off | - | - | - | - | - |')
    return lines


def _results_lines(config: BenchmarkConfig, runs: List[Run], profiles: List[RiskConfig]) -> List[str]:
    """The results table and the risk layer vs. baseline table"""
    lines = [
        '',
        '## Results',
        '',
        '| Strategy | Risk profile | Total return | CAGR | Max drawdown | Volatility | Sharpe | Trades | Win rate |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for r in runs:
        m = r.metrics
        lines.append(
            f'| {r.strategy} | {r.risk_profile} | {_pct(m["total_return"])} | {_pct(m["cagr"])} | '
            f'{_pct(m["max_drawdown"])} | {_pct(m["volatility"])} | {_ratio(m["sharpe_ratio"])} | '
            f'{m["num_trades"]} | {_pct(m["win_rate"])} |'
        )

    baseline_name = next((p.name for p in profiles if not p.enabled), None)
    managed = [p.name for p in profiles if p.enabled]
    if baseline_name and managed:
        lines += [
            '',
            '## Risk layer vs. baseline',
            '',
            f'Change against the same strategy with the risk layer off ({baseline_name}), in percentage '
            'points. A negative max-drawdown change means a shallower drawdown.',
            '',
            '| Strategy | Risk profile | Total return change | Max drawdown change | Sharpe change |',
            '| --- | --- | ---: | ---: | ---: |',
        ]
        by_key = {(r.strategy, r.risk_profile): r.metrics for r in runs}
        for strategy in config.strategies:
            base = by_key.get((strategy, baseline_name))
            if base is None:
                continue
            for name in managed:
                m = by_key.get((strategy, name))
                if m is None:
                    continue
                lines.append(
                    f'| {strategy} | {name} | {_signed_pct(_diff(m["total_return"], base["total_return"]))} | '
                    f'{_signed_pct(_diff(m["max_drawdown"], base["max_drawdown"]))} | '
                    f'{_ratio(_diff(m["sharpe_ratio"], base["sharpe_ratio"]), "+")} |'
                )
    return lines


def render(config: BenchmarkConfig, runs: List[Run]) -> str:
    """docs/results.md: the benchmark on the synthetic sample file"""
    data_bytes = Path(config.data_path).read_bytes()
    data = DataLoader(str(config.data_path)).load_csv(list(config.symbols))
    data = data[(data['timestamp'] >= config.start_date) & (data['timestamp'] <= config.end_date)]
    n_bars = data['timestamp'].nunique()
    regime_days = data.drop_duplicates('timestamp')['regime'].value_counts()
    model = RegimeModel.from_json(DEFAULT_CONFIG_PATH)
    profiles = load_risk_profiles(config.risk_profiles)

    lines = [
        '# Benchmark backtest results',
        '',
        '**The data is synthetic.** Prices come from a seeded Markov regime-switching '
        'geometric Brownian motion, not from any market. These numbers show how the engine '
        'and the risk layer behave on one simulated path; they say nothing about how the '
        'strategies would do on real prices.',
        '',
        f'Generated by `{COMMAND}` (`python -m scripts.results`). Nothing in the run is random '
        'and the file has no timestamps, so re-running the command reproduces it byte for byte. '
        'CI regenerates it and fails if it differs from the committed copy.',
        '',
        '## Setup',
        '',
        f'- Data: `{Path(config.data_path).relative_to(REPO_ROOT)}` '
        f'(sha256 `{hashlib.sha256(data_bytes).hexdigest()[:16]}...`), written by '
        f'`python -m backtest_engine.data_loader` with seed {DEFAULT_SEED} and the regime model in '
        '`config/data_generator.json`',
        f'- Symbols: {", ".join(config.symbols)} (labels only)',
        f'- Period: {config.start_date} to {config.end_date}, {n_bars:,} daily bars (business days)',
        f'- Days per regime in this period: '
        + ', '.join(f'{name} {int(regime_days.get(name, 0)):,}' for name in model.names),
    ]
    lines += _method_lines(config) + _profile_lines(profiles) + _results_lines(config, runs, profiles)

    baseline_name = next((p.name for p in profiles if not p.enabled), None)
    if baseline_name:
        lines += [
            '',
            '## Returns by regime (risk layer off)',
            '',
            'Each daily portfolio return is attributed to that day\'s regime label from the data '
            '(`metrics.returns_by_regime`). Compounded return over the days spent in each regime.',
            '',
            '| Strategy | ' + ' | '.join(model.names) + ' |',
            '| --- |' + ' ---: |' * len(model.names),
        ]
        for r in runs:
            if r.risk_profile != baseline_name:
                continue
            cells = [_pct(r.by_regime[name]['compounded_return_pct']) if name in r.by_regime else '-'
                     for name in model.names]
            lines.append(f'| {r.strategy} | ' + ' | '.join(cells) + ' |')

    return '\n'.join(lines) + '\n'


BAR_COLUMNS = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']


def bars_fingerprint(frame: pd.DataFrame) -> str:
    """sha256 of the bars as CSV, sorted, so the same bars always give the same hash"""
    canonical = frame[BAR_COLUMNS].sort_values(['symbol', 'timestamp']).to_csv(index=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def render_real(config: BenchmarkConfig, runs: List[Run], bars: LoadedBars) -> str:
    """
    docs/results-real.md: the same benchmark on market-data bars. The heading
    says what the service reported; it says real only when every symbol is
    Alpaca data.
    """
    provenance = bars.provenance
    frame = bars.frame
    if frame is None or provenance.symbol_sources is None:
        raise ValueError('render_real needs market-data bars')
    profiles = load_risk_profiles(config.risk_profiles)
    adjusted = 'split-adjusted' if provenance.adjustment == 'split' else 'not split-adjusted'
    sources = provenance.symbol_sources
    if provenance.real:
        banner = (f'**Data: daily bars from Alpaca, served by the market-data service, {adjusted}.** The '
                  "service ingests Alpaca's IEX feed by default (its API does not report the feed); IEX is a "
                  'single exchange, so prices and volumes are not the consolidated tape. These numbers '
                  'describe what the engine and the risk layer did on one window of a few stocks; they are '
                  'not a forecast.')
    else:
        synthetic = sorted(t for t, s in sources.items() if s == 'synthetic')
        rest = ', and `alpaca` for the others' if provenance.reported_source == 'mixed' else ''
        banner = (f'**The data is synthetic.** The market-data service reported source `synthetic` for '
                  f'{", ".join(synthetic)}{rest}. These numbers say nothing about how the strategies would '
                  'do on real prices.')
    per_symbol = frame.groupby('symbol').size()
    lines = [
        '# Benchmark backtest results on market-data bars',
        '',
        banner,
        '',
        f'Generated by `{REAL_COMMAND}` (`python -m scripts.results --data-source market-data`). The engine '
        'adds no randomness, but the bars come from the service when the command runs, so this file '
        'changes when the service\'s data does (a new split re-bases split-adjusted prices; a correction '
        'changes a bar). The fingerprint below identifies the exact bars. CI does not run this; it has no '
        'market-data service.',
        '',
        '## Setup',
        '',
        f'- Data: market-data `/v1/bars/{{ticker}}` with `adjustment={provenance.adjustment}`, read through '
        f'the local cache; sha256 of the bars used `{bars_fingerprint(frame)[:16]}...`',
        '- Source reported by the service: ' + ', '.join(f'{t} {s}' for t, s in sorted(sources.items())),
        f'- Symbols: {", ".join(config.symbols)}',
        f'- Period: {config.start_date} to {config.end_date}; {frame["timestamp"].nunique():,} sessions with '
        f'bars, {frame["timestamp"].min():%Y-%m-%d} to {frame["timestamp"].max():%Y-%m-%d}',
        '- Bars per symbol: ' + ', '.join(f'{t} {int(n):,}' for t, n in per_symbol.items()),
    ]
    lines += _method_lines(config) + _profile_lines(profiles) + _results_lines(config, runs, profiles)
    lines += ['', 'Returns are not split by regime as in docs/results.md: market bars carry no regime labels.']
    return '\n'.join(lines) + '\n'


def load_market_data_bars(config: BenchmarkConfig) -> LoadedBars:
    """The benchmark's bars from market-data (MARKET_DATA_URL), through the cache"""
    data_config = DataConfig.from_env()
    if not data_config.market_data_url:
        raise DataSourceError('MARKET_DATA_URL is not set; see .env.example')
    source = open_source(data_config, MARKET_DATA)
    try:
        return source.load(list(config.symbols), date.fromisoformat(config.start_date),
                           date.fromisoformat(config.end_date))
    finally:
        source.client.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--data-source', choices=DATA_SOURCES, default=SYNTHETIC,
                        help='synthetic (default; the sample file, whatever QUANT_DATA_SOURCE says) '
                             'or market-data (MARKET_DATA_URL)')
    parser.add_argument('--output', help='default: docs/results.md, or docs/results-real.md for market-data')
    parser.add_argument('--symbols', help='comma-separated, instead of the benchmark\'s five')
    parser.add_argument('--allow-synthetic', action='store_true',
                        help='market-data only: write the report even if the service reports synthetic '
                             'data (the report then says so)')
    args = parser.parse_args(argv)

    config = BenchmarkConfig()
    if args.symbols:
        config = replace(config, symbols=tuple(s.strip().upper() for s in args.symbols.split(',') if s.strip()))

    if args.data_source == SYNTHETIC:
        output = Path(args.output or REPO_ROOT / 'docs' / 'results.md')
        report = render(config, run_benchmarks(config))
    else:
        output = Path(args.output or REPO_ROOT / 'docs' / 'results-real.md')
        try:
            bars = load_market_data_bars(config)
        except (DataSourceError, NoBars, MarketDataError) as e:
            print(f'{REAL_COMMAND}: {e}', file=sys.stderr)
            return 1
        if not bars.provenance.real and not args.allow_synthetic:
            print(f'{REAL_COMMAND}: the market-data service reported {bars.provenance.reported_source} data '
                  f'({", ".join(f"{t} {s}" for t, s in sorted(bars.provenance.symbol_sources.items()))}). '
                  f'{output.name} is for Alpaca data: set MARKET_DATA_API_KEY for a service that has ingested '
                  'Alpaca bars, or pass --allow-synthetic to write a report labelled synthetic.',
                  file=sys.stderr)
            return 1
        report = render_real(config, run_benchmarks(config, bars), bars)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(f'Wrote {output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
