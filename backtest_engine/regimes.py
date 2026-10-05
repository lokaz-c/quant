"""
Markov-switching regime model for the synthetic price generator.

A discrete-time Markov chain picks the market regime for each trading day.
Each regime has its own annualised drift and volatility, which parameterise a
geometric Brownian motion for that day's log return. Everything is read from
config/data_generator.json.
"""
import bisect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

import numpy as np

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'data_generator.json'

_ROW_SUM_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Regime:
    name: str
    drift: float       # annualised GBM drift (mu)
    volatility: float  # annualised GBM volatility (sigma)


class RegimeModel:
    """Regimes plus a row-stochastic daily transition matrix.

    transition_matrix[i, j] is the probability that tomorrow is in regime j
    given that today is in regime i. If no initial distribution is given, the
    first day's regime is drawn from the chain's stationary distribution.
    """

    def __init__(
        self,
        regimes: Sequence[Regime],
        transition_matrix: Sequence[Sequence[float]],
        initial_distribution: Optional[Sequence[float]] = None,
        trading_days_per_year: int = 252,
        initial_price_range: Tuple[float, float] = (50.0, 200.0),
    ):
        self.regimes: Tuple[Regime, ...] = tuple(regimes)
        self.transition_matrix = np.asarray(transition_matrix, dtype=float)
        self.trading_days_per_year = int(trading_days_per_year)
        self.initial_price_range = (float(initial_price_range[0]), float(initial_price_range[1]))
        self._validate()
        if initial_distribution is None:
            self.initial_distribution = self.stationary_distribution()
        else:
            self.initial_distribution = self._check_distribution(
                np.asarray(initial_distribution, dtype=float), 'initial_distribution'
            )
        # Python lists for the per-step lookup: much faster than numpy calls in a loop
        self._cumulative_rows = [list(np.cumsum(row)) for row in self.transition_matrix]

    @classmethod
    def from_dict(cls, config: dict) -> 'RegimeModel':
        return cls(
            regimes=[Regime(r['name'], float(r['drift']), float(r['volatility'])) for r in config['regimes']],
            transition_matrix=config['transition_matrix'],
            initial_distribution=config.get('initial_distribution'),
            trading_days_per_year=config.get('trading_days_per_year', 252),
            initial_price_range=tuple(config.get('initial_price_range', (50.0, 200.0))),
        )

    @classmethod
    def from_json(cls, path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> 'RegimeModel':
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(r.name for r in self.regimes)

    def index_of(self, name: str) -> int:
        try:
            return self.names.index(name)
        except ValueError:
            raise ValueError(f"Unknown regime {name!r}; expected one of {self.names}") from None

    def _validate(self) -> None:
        n = len(self.regimes)
        if n == 0:
            raise ValueError('At least one regime is required')
        if len(set(self.names)) != n:
            raise ValueError('Regime names must be unique')
        if self.transition_matrix.shape != (n, n):
            raise ValueError(f'transition_matrix must be {n}x{n}, got {self.transition_matrix.shape}')
        for i, row in enumerate(self.transition_matrix):
            self._check_distribution(row, f'transition_matrix row {i} ({self.regimes[i].name})')
        for r in self.regimes:
            if r.volatility <= 0:
                raise ValueError(f'Regime {r.name!r} needs a positive volatility')
        if self.trading_days_per_year <= 0:
            raise ValueError('trading_days_per_year must be positive')
        low, high = self.initial_price_range
        if not 0 < low <= high:
            raise ValueError('initial_price_range must satisfy 0 < low <= high')

    @staticmethod
    def _check_distribution(p: np.ndarray, label: str) -> np.ndarray:
        if p.ndim != 1 or np.any(p < 0) or np.any(p > 1):
            raise ValueError(f'{label} must be a vector of probabilities in [0, 1]')
        if abs(p.sum() - 1.0) > _ROW_SUM_TOLERANCE:
            raise ValueError(f'{label} must sum to 1, got {p.sum():.12f}')
        return p

    def expected_durations(self) -> np.ndarray:
        """Mean number of consecutive days spent in each regime: 1 / (1 - p_ii)."""
        stay = np.diag(self.transition_matrix)
        with np.errstate(divide='ignore'):
            return 1.0 / (1.0 - stay)

    def stationary_distribution(self) -> np.ndarray:
        """Left eigenvector of the transition matrix for eigenvalue 1, normalised to sum to 1."""
        eigenvalues, eigenvectors = np.linalg.eig(self.transition_matrix.T)
        vector = np.real(eigenvectors[:, np.argmin(np.abs(eigenvalues - 1.0))])
        vector = np.clip(vector / vector.sum(), 0.0, None)
        return vector / vector.sum()

    def simulate(self, n_steps: int, rng: np.random.Generator) -> np.ndarray:
        """Regime index for each of n_steps consecutive days."""
        if n_steps <= 0:
            return np.empty(0, dtype=np.int64)
        last = len(self.regimes) - 1
        draws = rng.random(n_steps).tolist()
        path = [0] * n_steps
        state = min(bisect.bisect_right(np.cumsum(self.initial_distribution).tolist(), draws[0]), last)
        path[0] = state
        rows = self._cumulative_rows
        for t in range(1, n_steps):
            # bisect_right finds the first j with cumulative[j] > u; min() guards float round-off
            state = min(bisect.bisect_right(rows[state], draws[t]), last)
            path[t] = state
        return np.asarray(path, dtype=np.int64)

    def daily_log_returns(self, path: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """GBM log returns for one series: (mu - sigma^2 / 2) dt + sigma sqrt(dt) Z, per day's regime."""
        dt = 1.0 / self.trading_days_per_year
        mu = np.array([r.drift for r in self.regimes])[path]
        sigma = np.array([r.volatility for r in self.regimes])[path]
        shocks = rng.standard_normal(len(path))
        return (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * shocks


def transition_counts(path: np.ndarray, n_states: int) -> np.ndarray:
    """counts[i, j] = number of days where regime i was followed by regime j."""
    counts = np.zeros((n_states, n_states), dtype=np.int64)
    np.add.at(counts, (path[:-1], path[1:]), 1)
    return counts


def run_lengths(path: np.ndarray, state: int) -> np.ndarray:
    """Lengths of the maximal runs of `state` in the path (runs cut off by either end included)."""
    in_state = np.concatenate(([False], path == state, [False]))
    edges = np.flatnonzero(np.diff(in_state.astype(np.int8)))
    return edges[1::2] - edges[0::2]
