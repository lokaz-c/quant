"""
Tests for the Markov regime model behind the synthetic data generator.

The statistical tests use one long seeded simulation, so they are deterministic.
Tolerances are set from the sampling error of each estimator (see comments),
so a correct chain passes with a wide margin and a wrong one does not.
"""
import json

import numpy as np
import pytest

from backtest_engine.data_loader import generate_sample_data
from backtest_engine.regimes import (
    DEFAULT_CONFIG_PATH, Regime, RegimeModel, run_lengths, transition_counts,
)

N_STEPS = 300_000
SEED = 2024


@pytest.fixture(scope='module')
def model():
    return RegimeModel.from_json(DEFAULT_CONFIG_PATH)


@pytest.fixture(scope='module')
def long_path(model):
    return model.simulate(N_STEPS, np.random.default_rng(SEED))


def test_config_transition_rows_sum_to_one():
    with open(DEFAULT_CONFIG_PATH) as f:
        matrix = np.array(json.load(f)['transition_matrix'], dtype=float)
    assert matrix.shape[0] == matrix.shape[1]
    assert np.all((matrix >= 0) & (matrix <= 1))
    np.testing.assert_allclose(matrix.sum(axis=1), 1.0, atol=1e-12)


def test_config_has_bull_bear_sideways(model):
    assert model.names == ('bull', 'bear', 'sideways')
    drift = {r.name: r.drift for r in model.regimes}
    assert drift['bull'] > drift['sideways'] > drift['bear']


@pytest.mark.parametrize('matrix', [
    [[0.9, 0.2], [0.5, 0.5]],     # row sums to 1.1
    [[1.1, -0.1], [0.5, 0.5]],    # negative entry
    [[1.0]],                      # wrong shape
])
def test_invalid_transition_matrix_is_rejected(matrix):
    regimes = [Regime('up', 0.1, 0.2), Regime('down', -0.1, 0.3)]
    with pytest.raises(ValueError):
        RegimeModel(regimes, matrix)


def test_non_positive_volatility_is_rejected():
    with pytest.raises(ValueError):
        RegimeModel([Regime('flat', 0.0, 0.0)], [[1.0]])


def test_stationary_distribution_is_invariant(model):
    pi = model.stationary_distribution()
    np.testing.assert_allclose(pi @ model.transition_matrix, pi, atol=1e-12)
    assert pi.sum() == pytest.approx(1.0)


def test_same_seed_same_path_different_seed_different_path(model):
    a = model.simulate(1_000, np.random.default_rng(1))
    b = model.simulate(1_000, np.random.default_rng(1))
    c = model.simulate(1_000, np.random.default_rng(2))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_empirical_transition_frequencies_match_matrix(model, long_path):
    counts = transition_counts(long_path, len(model.regimes))
    visits = counts.sum(axis=1)
    empirical = counts / visits[:, None]
    expected = model.transition_matrix
    # Given n_i visits to regime i, row i of the counts is multinomial(n_i, P[i]),
    # so each entry has standard error sqrt(p (1 - p) / n_i). Allow 5 of them.
    tolerance = 5 * np.sqrt(expected * (1 - expected) / visits[:, None])
    assert np.all(np.abs(empirical - expected) <= tolerance + 1e-12), empirical


def test_mean_regime_duration_matches_one_over_one_minus_p_ii(model, long_path):
    expected = model.expected_durations()
    for i, regime in enumerate(model.regimes):
        runs = run_lengths(long_path, i)
        # Durations are geometric; with ~1,800+ runs per regime the relative
        # standard error of the mean is about 2.3%, so 10% is over 4 of them.
        assert runs.mean() == pytest.approx(expected[i], rel=0.10), regime.name


def test_time_in_each_regime_matches_stationary_distribution(model, long_path):
    occupancy = np.bincount(long_path, minlength=len(model.regimes)) / len(long_path)
    np.testing.assert_allclose(occupancy, model.stationary_distribution(), atol=0.03)


def test_gbm_log_returns_use_each_regimes_drift_and_volatility(model):
    dt = 1.0 / model.trading_days_per_year
    n = 200_000
    for i, regime in enumerate(model.regimes):
        path = np.full(n, i)
        log_returns = model.daily_log_returns(path, np.random.default_rng(SEED + i))
        annual_vol = log_returns.std(ddof=1) / np.sqrt(dt)
        annual_drift = log_returns.mean() / dt + 0.5 * annual_vol ** 2
        # Relative SE of the std is 1/sqrt(2n) ~ 0.16%; SE of the drift is
        # sigma / sqrt(n dt), at most 0.35 / 28 ~ 0.0125.
        assert annual_vol == pytest.approx(regime.volatility, rel=0.01)
        assert annual_drift == pytest.approx(regime.drift, abs=0.05)


def test_generated_bars_follow_the_regime_path_and_ohlc_rules():
    df = generate_sample_data(['AAPL', 'MSFT'], '2020-01-01', '2021-12-31', seed=3)
    assert set(df['regime']) <= {'bull', 'bear', 'sideways'}
    # The regime is market-wide: on any date every symbol has the same label
    assert df.groupby('timestamp')['regime'].nunique().max() == 1
    assert (df['high'] >= df[['open', 'close']].max(axis=1)).all()
    assert (df['low'] <= df[['open', 'close']].min(axis=1)).all()
    assert (df['low'] > 0).all()


def test_fixed_regime_option_holds_one_regime():
    df = generate_sample_data(['AAPL'], '2020-01-01', '2020-12-31', regime='bear', seed=3)
    assert set(df['regime']) == {'bear'}
    with pytest.raises(ValueError):
        generate_sample_data(['AAPL'], '2020-01-01', '2020-12-31', regime='crash')
