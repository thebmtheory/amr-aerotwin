"""Expanded percentile bootstrap intervals (Hesterberg 2015), which keep their coverage with few events.

The plain percentile interval undercovers at small n (its spread has the n-divisor variance and normal tails).
The expanded one reads the bootstrap distribution at alpha' / 2 = Phi(-sqrt(n / (n - 1)) t_{n-1, 1 - alpha/2}),
which matches a t interval with n - 1 degrees of freedom and keeps the bootstrap's asymmetry.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import stats

LEVEL = 0.90  # every interval in the season results
INTERVAL_Z = float(stats.norm.ppf(0.5 + LEVEL / 2))  # 1.645


def expanded_levels(n: int, level: float = LEVEL) -> tuple[float, float]:
    """Lower and upper percentile levels (0-100) for an expanded percentile interval from n units."""
    alpha = 1.0 - level
    if n < 2:
        return 100 * alpha / 2, 100 * (1 - alpha / 2)
    z = np.sqrt(n / (n - 1.0)) * stats.t.ppf(1 - alpha / 2, n - 1)
    a = float(stats.norm.cdf(-z))
    return 100 * a, 100 * (1 - a)


def boot_ci(draws: ArrayLike, n: int, level: float = LEVEL) -> tuple[float, float]:
    """Expanded percentile interval of scalar bootstrap `draws` made by resampling `n` units (NaNs ignored)."""
    lo, hi = expanded_levels(n, level)
    out = np.nanpercentile(np.asarray(draws, dtype=float), [lo, hi])
    return float(out[0]), float(out[1])


def boot_ci_columns(draws: ArrayLike, n: int, level: float = LEVEL) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Same as `boot_ci`, per column of a (draws x quantities) array."""
    lo, hi = expanded_levels(n, level)
    out = np.nanpercentile(np.asarray(draws, dtype=float), [lo, hi], axis=0)
    return out[0], out[1]


def coverage_check(ns: tuple[int, ...] = (4, 6, 8, 12), reps: int = 2000, n_boot: int = 1000,
                   level: float = LEVEL, seed: int = 11) -> dict[str, Any]:
    """Coverage (%) of plain and expanded percentile intervals for the mean of normal data, by sample size.

    The report quotes it to show why intervals are widened.
    """
    rng = np.random.default_rng(seed)
    tail = 50.0 * (1.0 - level)
    plain, expanded = [], []
    for n in ns:
        hit_p = hit_e = 0
        for _ in range(reps):
            x = rng.normal(0.0, 1.0, n)
            b = x[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
            lo, hi = np.percentile(b, [tail, 100.0 - tail])
            hit_p += bool(lo <= 0.0 <= hi)
            lo2, hi2 = boot_ci(b, n, level)
            hit_e += bool(lo2 <= 0.0 <= hi2)
        plain.append(100.0 * hit_p / reps)
        expanded.append(100.0 * hit_e / reps)
    return {"n_events": list(ns), "plain_pct": plain, "expanded_pct": expanded, "reps": reps, "level": level}
