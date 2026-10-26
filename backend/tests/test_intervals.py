"""Small-sample bootstrap intervals: coverage checked by simulation, not assumed."""

import numpy as np
import pytest
from amr_aerotwin.modeling.intervals import boot_ci, expanded_levels


def _coverage(n: int, expanded: bool, reps: int = 600, n_boot: int = 1000, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(reps):
        x = rng.normal(0.0, 1.0, n)
        boots = x[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
        lo, hi = boot_ci(boots, n) if expanded else (np.percentile(boots, 5), np.percentile(boots, 95))
        hits += lo <= 0.0 <= hi
    return hits / reps


@pytest.mark.parametrize("n", [5, 8, 12])
def test_expanded_percentile_interval_keeps_nominal_coverage_with_few_events(n):
    plain, expanded = _coverage(n, False), _coverage(n, True)
    assert plain < 0.87  # the plain percentile bootstrap undercovers at these sizes
    assert 0.86 <= expanded <= 0.95


def test_expanded_levels_tend_to_plain_percentiles():
    lo, hi = expanded_levels(5)
    assert lo < 1.5 and hi > 98.5  # much wider than 5/95 for five units
    lo, hi = expanded_levels(10_000)
    assert lo == pytest.approx(5.0, abs=0.05) and hi == pytest.approx(95.0, abs=0.05)
