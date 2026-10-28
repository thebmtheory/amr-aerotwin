"""Gaussian-process emulator of the calibrated lap simulator (Sacks et al. 1989; Kennedy and O'Hagan 2001).

Maps factors on mu, ClA, CdA and power, each within +-15% of the calibrated car, to the lap-time change.
Simulator runs are cheap, so the aim is a response surface checked on held-out runs rather than speed; it
shows what the linear surrogate from the 1% sensitivities misses (curvature and interactions).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import qmc
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from amr_aerotwin.modeling.intervals import INTERVAL_Z
from amr_aerotwin.physics.lapsim import SENSITIVITY_STEPS, VehicleParams, simulate_lap

PARAMS: tuple[str, ...] = ("mu", "cla_m2", "cda_m2", "power_w")
HALF_RANGE = 0.15  # each factor in [1 - h, 1 + h]
N_TRAIN = 60
N_TEST = 60
SOBOL_LOG2_N = 14  # 2^14 base points for the indices of the GP mean (cheap: no simulator runs)

Seed = int | Sequence[int]


def scaled_car(p: VehicleParams, factors: Mapping[str, float]) -> VehicleParams:
    """`p` with the named fields multiplied; the low-drag CdA moves with CdA, as in the sensitivities."""
    out = p.scaled(**factors)
    if "cda_m2" in factors and p.low_drag_cda_m2 is not None:
        out = replace(out, low_drag_cda_m2=p.low_drag_cda_m2 * factors["cda_m2"])
    return out


def latin_hypercube(n: int, seed: Seed, half_range: float = HALF_RANGE) -> NDArray[np.float64]:
    """n x 4 factors (order of PARAMS), uniform on [1 - h, 1 + h], one run in each of n strata per axis."""
    u = qmc.LatinHypercube(d=len(PARAMS), rng=np.random.default_rng(seed)).random(n)
    return np.asarray(qmc.scale(u, 1.0 - half_range, 1.0 + half_range), dtype=float)


def simulated_lap_times(
    factors: NDArray[np.float64],
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
) -> NDArray[np.float64]:
    """Simulated lap time (s) of the car scaled by each row of `factors`."""
    return np.array([
        simulate_lap(distance_m, kappa, scaled_car(p, dict(zip(PARAMS, map(float, f)))), low_drag_mask, lap_length_m).lap_time_s
        for f in np.atleast_2d(factors)
    ])


def linear_changes(factors: NDArray[np.float64], sensitivities: Mapping[str, float]) -> NDArray[np.float64]:
    """Lap-time change (s) from the first-order surrogate dt = sum_i s_i (f_i - 1) / step_i.

    s_i is the central-difference lap-time change for a +1% step (`lap_time_sensitivities`).
    """
    slope = np.array([float(sensitivities[f"{n}_plus_1pct_s"]) / SENSITIVITY_STEPS[n] for n in PARAMS])
    return np.asarray((np.atleast_2d(factors) - 1.0) @ slope, dtype=float)


def fit_emulator(factors: NDArray[np.float64], dt_s: NDArray[np.float64], seed: int = 0) -> GaussianProcessRegressor:
    """GP on log factors: constant x anisotropic RBF + white noise, standardised targets, seeded restarts.

    The white noise absorbs kinks where grid points switch between grip-limited and flat-out. Some restarts
    end in an abnormal line search; 8 restarts find the same optimum as these 3, so the warnings are silenced.
    """
    d = factors.shape[1]
    kernel = (ConstantKernel(1.0, (1e-3, 1e4)) * RBF(np.full(d, 0.3), (1e-2, 1e3))
              + WhiteKernel(1e-6, (1e-12, 1e-1)))
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=3, random_state=seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        return gp.fit(np.log(factors), dt_s)


def sobol_first_order(
    fn: Callable[[NDArray[np.float64]], NDArray[np.float64]],
    half_range: float = HALF_RANGE,
    log2_n: int = SOBOL_LOG2_N,
    seed: Seed = 0,
) -> NDArray[np.float64]:
    """First-order Sobol indices S_i = Var(E[Y | X_i]) / Var(Y), with X uniform on the factor box.

    Pick-freeze estimator of Janon et al. (2014) on the two halves of one scrambled Sobol' sequence;
    fn takes a matrix of factor rows and is evaluated on 2^log2_n (d + 1) rows.
    """
    d = len(PARAMS)
    ab = qmc.Sobol(d=2 * d, scramble=True, rng=np.random.default_rng(seed)).random_base2(log2_n)
    ab = qmc.scale(ab, 1.0 - half_range, 1.0 + half_range)
    a, b = ab[:, :d], ab[:, d:]
    ya = np.asarray(fn(a), dtype=float)
    out = np.empty(d)
    for i in range(d):
        bi = b.copy()
        bi[:, i] = a[:, i]
        yi = np.asarray(fn(bi), dtype=float)
        m = 0.5 * (ya.mean() + yi.mean())
        out[i] = (np.mean(ya * yi) - m**2) / (0.5 * np.mean(ya**2 + yi**2) - m**2)
    return out


def _rmse(err: NDArray[np.float64]) -> float:
    return float(np.sqrt(np.mean(err**2)))


@dataclass(frozen=True)
class Emulator:
    """A fitted emulator with its held-out check. Factors are rows in the order of PARAMS."""

    gp: GaussianProcessRegressor
    half_range: float
    base_lap_time_s: float
    train_factors: NDArray[np.float64]
    train_dt_s: NDArray[np.float64]
    test_factors: NDArray[np.float64]
    test_dt_s: NDArray[np.float64]  # simulator
    test_mean_s: NDArray[np.float64]  # GP predictive mean
    test_sd_s: NDArray[np.float64]  # GP predictive sd (includes the white-noise term)
    test_linear_s: NDArray[np.float64]  # linear surrogate
    sobol_first: NDArray[np.float64]  # one minus their sum is the interactions' share of the variance

    def predict(self, factors: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Lap-time change from the calibrated car (s): predictive mean and sd."""
        mean, sd = self.gp.predict(np.log(np.atleast_2d(factors)), return_std=True)
        return np.asarray(mean, dtype=float), np.asarray(sd, dtype=float)

    def length_scales(self) -> NDArray[np.float64]:
        """RBF length scales in log-factor units (the box is about 0.30 wide); longer = closer to linear."""
        return np.atleast_1d(np.asarray(self.gp.kernel_.k1.k2.length_scale, dtype=float))

    def summary(self) -> dict[str, Any]:
        """JSON-ready validation summary, plus the held-out runs (rounded) for charts."""
        err = self.test_mean_s - self.test_dt_s
        lin = self.test_linear_s - self.test_dt_s
        return {
            "params": list(PARAMS),
            "half_range": float(self.half_range),
            "n_train": int(len(self.train_dt_s)),
            "n_test": int(len(self.test_dt_s)),
            "base_lap_time_s": float(self.base_lap_time_s),
            "spread_s": float(np.std(self.test_dt_s, ddof=1)),
            "rmse_s": _rmse(err),
            "max_abs_err_s": float(np.max(np.abs(err))),
            "coverage90": float(np.mean(np.abs(err) <= INTERVAL_Z * self.test_sd_s)),
            "linear_rmse_s": _rmse(lin),
            "linear_max_abs_err_s": float(np.max(np.abs(lin))),
            "sobol_first": {n: float(v) for n, v in zip(PARAMS, self.sobol_first)},
            "length_scales": {n: float(v) for n, v in zip(PARAMS, self.length_scales())},
            "test_factors": [[round(float(v), 3) for v in row] for row in self.test_factors],
            "test_sim_s": [round(float(v), 4) for v in self.test_dt_s],
            "test_gp_s": [round(float(v), 4) for v in self.test_mean_s],
            "test_gp_sd_s": [round(float(v), 4) for v in self.test_sd_s],
            "test_linear_s": [round(float(v), 4) for v in self.test_linear_s],
        }


def build_emulator(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    low_drag_mask: NDArray[np.bool_] | None,
    lap_length_m: float | None,
    sensitivities: Mapping[str, float],
    seed: int = 0,
    n_train: int = N_TRAIN,
    n_test: int = N_TEST,
    half_range: float = HALF_RANGE,
    sobol_log2_n: int = SOBOL_LOG2_N,
) -> Emulator:
    """Run the simulator on two independent Latin hypercubes, fit the GP to one, test it on the other."""

    def lap_times(f: NDArray[np.float64]) -> NDArray[np.float64]:
        return simulated_lap_times(f, distance_m, kappa, p, low_drag_mask, lap_length_m)

    base = float(lap_times(np.ones((1, len(PARAMS))))[0])
    x_train = latin_hypercube(n_train, [seed, 1], half_range)
    x_test = latin_hypercube(n_test, [seed, 2], half_range)
    y_train = lap_times(x_train) - base
    y_test = lap_times(x_test) - base
    gp = fit_emulator(x_train, y_train, seed)
    mean, sd = gp.predict(np.log(x_test), return_std=True)

    def gp_mean(f: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.asarray(gp.predict(np.log(f)), dtype=float)

    return Emulator(
        gp=gp, half_range=half_range, base_lap_time_s=base,
        train_factors=x_train, train_dt_s=y_train, test_factors=x_test, test_dt_s=y_test,
        test_mean_s=np.asarray(mean, dtype=float), test_sd_s=np.asarray(sd, dtype=float),
        test_linear_s=linear_changes(x_test, sensitivities),
        sobol_first=sobol_first_order(gp_mean, half_range, sobol_log2_n, [seed, 3]),
    )


def lap_time_emulator(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    low_drag_mask: NDArray[np.bool_] | None,
    lap_length_m: float | None,
    sensitivities: Mapping[str, float],
    seed: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fit and validate the lap-time emulator for one calibrated car; JSON-ready summary (see Emulator.summary)."""
    return build_emulator(distance_m, kappa, p, low_drag_mask, lap_length_m, sensitivities, seed, **kwargs).summary()
