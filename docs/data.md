# Synthetic data generator

`data/sample_data.csv` is **synthetic**: 25 ticker labels, business days from 2020-01-01 to 2024-12-31, 32,625 rows. It is exactly the output of:

```bash
make data        # python -m backtest_engine.data_loader  (seed 42)
```

`tests/test_data_generation.py` regenerates it and compares it with the committed file byte for byte. The engine reads any CSV with the columns `timestamp, symbol, open, high, low, close, volume`. The sample adds a `regime` column.

This file is the `synthetic` data source: the default when `MARKET_DATA_URL` is not set, and always the data behind `make results` and CI. Bars from the market-data service are the other source; see [market-data.md](market-data.md).

## Model

1. **Regimes.** A discrete-time Markov chain picks one market-wide regime per day: `bull`, `bear` or `sideways`. The first day is drawn from the chain's stationary distribution unless `initial_distribution` is set. Every symbol shares the same regime path.
2. **Prices.** Each symbol's close follows a geometric Brownian motion, using the drift μ and volatility σ of that day's regime (annualised, dt = 1/252):

   log(S_t / S_{t-1}) = (μ − σ²/2)·dt + σ·√dt·Z_t, with Z_t ~ N(0, 1)

   The start price is uniform in `initial_price_range`.
3. **Bars.** The intraday range is 1–3% of the close. High and low fall inside it, and the open falls between them. Volume is uniform between 100,000 and 10,000,000. Prices are rounded to cents.

Parameters live in `config/data_generator.json`:

| Regime | Drift μ (annual) | Volatility σ (annual) | Stay probability p_ii (daily) |
| --- | ---: | ---: | ---: |
| bull | 0.20 | 0.18 | 0.985 |
| bear | -0.25 | 0.35 | 0.965 |
| sideways | 0.02 | 0.12 | 0.980 |

Full daily transition matrix (rows: today, columns: tomorrow; each row sums to 1):

```
            bull    bear   sideways
bull       0.985   0.005   0.010
bear       0.015   0.965   0.020
sideways   0.010   0.010   0.980
```

The expected time spent in a regime before leaving it is 1 / (1 − p_ii) days: 66.7 (bull), 28.6 (bear) and 50.0 (sideways). The stationary distribution is 0.435 / 0.174 / 0.391. Both are printed by:

```bash
python -c "from backtest_engine.regimes import RegimeModel; m = RegimeModel.from_json(); print(m.expected_durations(), m.stationary_distribution())"
```

## Seeding

- The regime path uses `np.random.default_rng([seed, 0])`.
- Each symbol uses `np.random.default_rng([seed, 1, zlib.crc32(symbol)])`.
- No global numpy state is used. Python's built-in `hash()` is never used: it is salted per process (`PYTHONHASHSEED`), which made the old generator write different data on every run.
- A symbol's series does not depend on which other symbols are generated alongside it.

## Tests

`tests/test_regimes.py` runs one seeded 300,000-step simulation in about 0.1 s and checks:

- transition rows sum to 1, and malformed matrices are rejected
- each empirical transition frequency is within 5 standard errors (√(p(1−p)/n_i)) of the matrix
- the mean run length of each regime is within 10% of 1/(1 − p_ii); that is over 4 standard errors at this sample size
- time spent in each regime matches the stationary distribution
- per-regime GBM drift and volatility are recovered from simulated log returns

I checked that a slightly perturbed matrix (bull stay probability 0.980 instead of 0.985) and the old fixed 60-day cycle both fail the frequency and duration checks.

`tests/test_data_generation.py` checks determinism. Two subprocesses with different `PYTHONHASHSEED` values produce identical data, and the committed CSV matches the generator.

## Limits

- Symbols are independent given the regime. There is no cross-sectional correlation beyond the shared regime, and no fat tails within a regime.
- Business days include market holidays.
- Ticker names are labels. The prices have nothing to do with the real companies.
