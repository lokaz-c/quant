"""
Tests for the synthetic data generator: determinism and seeding
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from backtest_engine.data_loader import (
    DEFAULT_END, DEFAULT_SEED, DEFAULT_START, DEFAULT_SYMBOLS, generate_sample_data,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runs in a fresh interpreter, so str hashing is salted by that process's PYTHONHASHSEED.
DIGEST_SCRIPT = """
import hashlib
from backtest_engine.data_loader import generate_sample_data
df =generate_sample_data(['AAPL', 'MSFT', 'TSLA'], '2022-01-03', '2022-06-30', seed=7)
print(hashlib.sha256(df.to_csv(index=False).encode()).hexdigest())
"""


def _digest(df):
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def _digest_in_subprocess(hash_seed: int) -> str:
    env = {**os.environ, 'PYTHONHASHSEED': str(hash_seed)}
    result = subprocess.run(
        [sys.executable, '-c', DIGEST_SCRIPT],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_identical_data_across_processes_with_different_hash_seeds():
    assert _digest_in_subprocess(1) == _digest_in_subprocess(2)


def test_subprocess_matches_in_process_generation():
    df = generate_sample_data(['AAPL', 'MSFT', 'TSLA'], '2022-01-03', '2022-06-30', seed=7)
    assert _digest_in_subprocess(3) == _digest(df)


def test_seed_changes_the_data():
    a = generate_sample_data(['AAPL'], '2022-01-03', '2022-06-30', seed=1)
    b = generate_sample_data(['AAPL'], '2022-01-03', '2022-06-30', seed=2)
    assert not a['close'].equals(b['close'])


def test_symbol_series_does_not_depend_on_other_symbols():
    alone = generate_sample_data(['MSFT'], '2022-01-03', '2022-06-30', seed=7)
    together = generate_sample_data(['AAPL', 'MSFT', 'TSLA'], '2022-01-03', '2022-06-30', seed=7)
    msft = together[together['symbol'] == 'MSFT'].reset_index(drop=True)
    assert alone['close'].tolist() == msft['close'].tolist()


def test_committed_sample_csv_matches_the_generator():
    """data/sample_data.csv is exactly `python -m backtest_engine.data_loader` output."""
    df = generate_sample_data(DEFAULT_SYMBOLS, DEFAULT_START, DEFAULT_END, seed=DEFAULT_SEED)
    committed = (REPO_ROOT / 'data' / 'sample_data.csv').read_text()
    assert df.to_csv(index=False) == committed
