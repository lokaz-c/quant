"""
DataLoader keeps the parsed CSV per file version (path, modification time,
size), so the API doesn't parse the same sample file for every run. A changed
file is read again, and no caller can change what the next one gets.
"""
import os

import pandas as pd

from backtest_engine.data_loader import DataLoader, clear_csv_cache, generate_sample_data


def test_a_cached_load_equals_a_fresh_parse(tmp_path):
    path = tmp_path / 'bars.csv'
    generate_sample_data(['AAPL', 'MSFT'], '2023-01-01', '2023-03-31', output_path=path, seed=5)
    clear_csv_cache()
    first = DataLoader(str(path)).load_csv(['MSFT'])
    cached = DataLoader(str(path)).load_csv(['MSFT'])

    fresh = pd.read_csv(path)
    fresh['timestamp'] = pd.to_datetime(fresh['timestamp'])
    fresh = fresh[fresh['symbol'] == 'MSFT'].sort_values(['symbol', 'timestamp']).reset_index(drop=True)
    pd.testing.assert_frame_equal(first, fresh, check_exact=True)
    pd.testing.assert_frame_equal(cached, fresh, check_exact=True)


def test_changing_a_returned_frame_does_not_change_the_next_load(tmp_path):
    path = tmp_path / 'bars.csv'
    generate_sample_data(['AAPL'], '2023-01-01', '2023-02-28', output_path=path, seed=5)
    loader = DataLoader(str(path))
    loaded = loader.load_csv()
    expected = loaded['close'].copy()
    loaded['close'] = 0.0
    loader.filter_by_date('2023-01-01', '2023-12-31')['close'] = -1.0
    pd.testing.assert_series_equal(DataLoader(str(path)).load_csv()['close'], expected)


def test_a_rewritten_file_is_read_again(tmp_path):
    path = tmp_path / 'bars.csv'
    generate_sample_data(['AAPL'], '2023-01-01', '2023-02-28', output_path=path, seed=5)
    before = DataLoader(str(path)).load_csv()
    written = os.stat(path).st_mtime_ns
    generate_sample_data(['AAPL'], '2023-01-01', '2023-02-28', output_path=path, seed=6)
    # Date the rewrite a second later, whatever the filesystem's timestamp resolution
    os.utime(path, ns=(written + 10**9, written + 10**9))
    after = DataLoader(str(path)).load_csv()
    assert not after['close'].equals(before['close'])
