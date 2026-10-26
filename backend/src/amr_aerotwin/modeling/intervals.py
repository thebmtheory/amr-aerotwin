"""Bootstrap intervals that keep their coverage with few resampling units.

Most season results resample events, and a team has only 5-13 events in 2026. The plain
percentile bootstrap undercovers there: a nominal 90% interval for a mean covers about 80%
of the time at n = 6 and 85% at n = 10, because the bootstrap spread uses the n-divisor
variance and normal tails. The expanded percentile bootstrap (Hesterberg, 2015, "What
teachers should know about the bootstrap") reads the bootstrap distribution at wider
percentile levels, chosen so the interval matches a t interval with n - 1 degrees of freedom:

    alpha' / 2 = Phi(-sqrt(n / (n - 1)) * t_{n-1, 1 - alpha/2})

which brings coverage back close to nominal for n of about 5 and up on symmetric data. It
keeps the bootstrap's asymmetry, so skewed statistics (ratios, medians) stay skewed.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import stats


def expanded_levels(n: int, level: float = 0.90) -> tuple[float, float]:
    """Lower and upper percentile levels (0-100) for an expanded percentile interval from n units."""
    alpha = 1.0 - level
    if n < 2:
        return 100 * alpha / 2, 100 * (1 - alpha / 2)
    z = np.sqrt(n / (n - 1.0)) * stats.t.ppf(1 - alpha / 2, n - 1)
    a = float(stats.norm.cdf(-z))
    return 100 * a, 100 * (1 - a)


def boot_ci(draws: ArrayLike, n: int, level: float = 0.90) -> tuple[float, float]:
    """Expanded percentile interval of scalar bootstrap `draws` made by resampling `n` units (NaNs ignored)."""
    lo, hi = expanded_levels(n, level)
    out = np.nanpercentile(np.asarray(draws, dtype=float), [lo, hi])
    return float(out[0]), float(out[1])


def boot_ci_columns(draws: ArrayLike, n: int, level: float = 0.90) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Same as `boot_ci`, per column of a (draws x quantities) array."""
    lo, hi = expanded_levels(n, level)
    out = np.nanpercentile(np.asarray(draws, dtype=float), [lo, hi], axis=0)
    return out[0], out[1]
