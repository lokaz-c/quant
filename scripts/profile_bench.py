"""
Profile one `make bench` case -> stdout

Runs Backtester.run() once under cProfile and prints the functions with the
most time of their own and the most cumulative time. With --lines it runs the
case again under line_profiler and prints per-line timings of the engine loop
and the strategy (pip install line_profiler; it is not in requirements.txt).

    make profile                              # python -m scripts.profile_bench
    python -m scripts.profile_bench --case 1 --lines
    python -m scripts.profile_bench --output run.prof   # also save the cProfile stats

The default case is the largest benchmark case: 25 symbols over 2020-2024,
32,625 rows. Profiling slows the run down; use `make bench` for timings.
"""
import argparse
import contextlib
import cProfile
import io
import pstats
import time
from typing import List, Optional

from backtest_engine import strategy_base
from backtest_engine.backtester import Backtester
from backtest_engine.data_loader import DataLoader
from backtest_engine.strategies.moving_average import MovingAverageCrossover
from scripts.bench import CASES, DATA_PATH, load_average, machine_info

COMMAND = 'make profile'


def make_backtester(case: int) -> Backtester:
    _, symbols, start, end = CASES[case]
    return Backtester(MovingAverageCrossover(), DataLoader(str(DATA_PATH)), 100_000,
                      start_date=start, end_date=end, symbols=list(symbols))


def run_quietly(backtester: Backtester) -> float:
    began = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):   # the engine prints progress
        backtester.run()
    return time.perf_counter() - began


def cprofile_case(case: int, top: int, output: Optional[str]) -> None:
    backtester = make_backtester(case)
    profiler = cProfile.Profile()
    profiler.enable()
    seconds = run_quietly(backtester)
    profiler.disable()
    print(f'cProfile: one run in {seconds:.2f} s (slower than unprofiled)\n')
    if output:
        profiler.dump_stats(output)
        print(f'Saved the stats to {output} (python -m pstats {output}, or snakeviz)\n')
    for key, title in (('tottime', 'own time (tottime)'), ('cumulative', 'cumulative time')):
        print(f'--- top {top} by {title} ---')
        buffer = io.StringIO()
        pstats.Stats(profiler, stream=buffer).strip_dirs().sort_stats(key).print_stats(top)
        # Drop pstats' header lines before the table
        lines = buffer.getvalue().splitlines()
        start = next((i for i, line in enumerate(lines) if line.lstrip().startswith('ncalls')), 0)
        print('\n'.join(lines[start:]).rstrip() + '\n')


def line_targets() -> List:
    """
    Backtester.run and whichever of these methods the checkout defines: the
    strategy's, StrategyBase's and SymbolBars'. Also works on a checkout from
    before precomputation, where the strategy had only generate_signals.
    """
    targets = [Backtester.run]
    for owner in (MovingAverageCrossover, strategy_base.StrategyBase, getattr(strategy_base, 'SymbolBars', None)):
        for name in ('generate_signals', 'prepare', 'indicators', 'signal', 'bar'):
            function = vars(owner).get(name) if owner is not None else None
            if callable(function) and not getattr(function, '__isabstractmethod__', False):
                targets.append(function)
    return targets


def line_profile_case(case: int) -> None:
    try:
        from line_profiler import LineProfiler
    except ImportError:
        raise SystemExit('--lines needs line_profiler: pip install line_profiler')
    profiler = LineProfiler(*line_targets())
    backtester = make_backtester(case)
    seconds = profiler.runcall(run_quietly, backtester)
    print(f'line_profiler: one run in {seconds:.2f} s (slower than unprofiled)\n')
    profiler.print_stats(output_unit=1e-3, stripzeros=True)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--case', type=int, default=len(CASES) - 1, choices=range(len(CASES)),
                        help='index into scripts.bench.CASES (default: the largest)')
    parser.add_argument('--top', type=int, default=20, help='rows per cProfile table')
    parser.add_argument('--output', help='also write the cProfile stats to this file')
    parser.add_argument('--lines', action='store_true', help='add per-line timings (needs line_profiler)')
    args = parser.parse_args(argv)

    label, symbols, start, end = CASES[args.case]
    info = machine_info()
    print(f'{COMMAND}: {label} ({len(symbols)} symbols, {start} to {end}), Moving Average Crossover 20/50')
    print(f'{info["CPU"]}, Python {info["Python"]}, load average {load_average()}\n')
    cprofile_case(args.case, args.top, args.output)
    if args.lines:
        line_profile_case(args.case)


if __name__ == '__main__':
    main()
