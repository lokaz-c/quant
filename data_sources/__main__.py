"""
Command line for the market-data client and cache.

    python -m data_sources symbols [--prefix S]
    python -m data_sources bars TICKER --from 2024-01-01 --to 2024-12-31 [--adjustment raw] [--no-cache]
    python -m data_sources cache info
    python -m data_sources cache clear

Reads MARKET_DATA_URL, MARKET_DATA_API_KEY, MARKET_DATA_CACHE_DIR and
MARKET_DATA_TIMEOUT like the app (see data_sources/sources.py).
"""
import argparse
import logging
import sys
from datetime import date
from typing import List, Optional

from .cache import BarCache
from .market_data import MarketDataError
from .sources import DataConfig, DataSourceError


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m data_sources', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    symbols = sub.add_parser('symbols', help='list the symbols the service shows this client')
    symbols.add_argument('--prefix', default='')
    bars = sub.add_parser('bars', help='fetch daily bars (through the cache unless --no-cache)')
    bars.add_argument('ticker')
    bars.add_argument('--from', dest='start', required=True, type=date.fromisoformat)
    bars.add_argument('--to', dest='end', required=True, type=date.fromisoformat)
    bars.add_argument('--adjustment', choices=('split', 'raw'))
    bars.add_argument('--no-cache', action='store_true')
    cache = sub.add_parser('cache', help='inspect or clear the local cache')
    cache.add_argument('action', choices=('info', 'clear'))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    try:
        config = DataConfig.from_env()
        if args.command == 'cache':
            if config.cache_dir is None:
                print('The cache is off (MARKET_DATA_CACHE_DIR=off)')
                return 0
            store = BarCache.in_dir(config.cache_dir)
            if args.action == 'clear':
                store.clear()
                print(f'Cleared {store.path}')
            else:
                rows = store.info()
                print(f'{store.path}: {len(rows)} series')
                for r in rows:
                    print(f"  {r['ticker']:<8} {r['adjustment']:<5} {r['source']:<9} {r['bars']:>6} bars "
                          f"{r['first'] or '-'} to {r['last'] or '-'}  ({r['service']})")
            return 0

        with config.client() as client:
            if args.command == 'symbols':
                for s in client.symbols(args.prefix):
                    print(f'{s.ticker:<8} {s.source:<9} {s.first_bar} to {s.last_bar}  {s.name or ""}')
                return 0
            adjustment = args.adjustment or config.adjustment
            store = None if args.no_cache else config.cache()
            if store is None:
                series = client.bars(args.ticker, args.start, args.end, adjustment=adjustment)
                fetched = f'{client.requests} request(s), no cache'
            else:
                series = store.get(client, args.ticker, args.start, args.end, adjustment)
                fetched = (', '.join(f'{a} to {b}' for a, b in series.fetched) or 'nothing (cache hit)')
                fetched = f'fetched {fetched}; {client.requests} request(s)'
            first = series.bars[0].date if series.bars else '-'
            last = series.bars[-1].date if series.bars else '-'
            print(f'{series.ticker}: {len(series.bars)} bars, {first} to {last}, source={series.source}, '
                  f'adjustment={series.adjustment}; {fetched}')
            return 0
    except (DataSourceError, MarketDataError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
