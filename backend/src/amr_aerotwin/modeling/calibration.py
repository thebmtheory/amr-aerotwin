"""Modular Bayesian calibration of the lap simulator against a measured lap (Liu, Bayarri and Berger 2009).

Log-parameters are fitted by MAP with weak log-normal priors and a Laplace posterior; a Gaussian process on
the remaining speed residual then shows where the point-mass physics is wrong. Lap residuals are autocorrelated,
so the data term counts n_eff = n (1 - r1) / (1 + r1) samples, with r1 the lag-1 autocorrelation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from amr_aerotwin.modeling.intervals import INTERVAL_Z
from amr_aerotwin.physics.lapsim import LapSimResult, VehicleParams, simulate_lap

PARAM_NAMES = ("mu", "cla_m2", "cda_m2", "power_w", "long_grip_scale", "low_drag_cda_m2")

# Weak log-normal priors as (median, sigma of log), wide enough not to dominate the data
DEFAULT_PRIORS: dict[str, tuple[float, float]] = {
    "mu": (1.6, 0.35),
    "cla_m2": (4.5, 0.45),
    "cda_m2": (1.3, 0.45),
    "power_w": (700e3, 0.30),
    "long_grip_scale": (0.9, 0.25),
    "low_drag_cda_m2": (1.0, 0.45),
}


@dataclass(frozen=True)
class CalibrationResult:
    params: VehicleParams
    names: tuple[str, ...]
    theta_map: NDArray[np.float64]  # log-parameters at the MAP
    cov_log: NDArray[np.float64]  # Laplace covariance of log-parameters
    noise_sigma_ms: float
    lag1_autocorr: float
    n_effective: float
    sim: LapSimResult
    observed_speed_ms: NDArray[np.float64]
    rmse_kmh: float
    lap_time_error_s: float
    converged: bool

    def ci90(self) -> dict[str, tuple[float, float, float]]:
        """Median and 90% credible interval of each parameter (natural units)."""
        sd = np.sqrt(np.diag(self.cov_log))
        return {
            n: (float(np.exp(m)), float(np.exp(m - INTERVAL_Z * s)), float(np.exp(m + INTERVAL_Z * s)))
            for n, m, s in zip(self.names, self.theta_map, sd)
        }

    def correlation(self) -> NDArray[np.float64]:
        sd = np.sqrt(np.diag(self.cov_log))
        return self.cov_log / np.outer(sd, sd)


def _params_from_theta(base: VehicleParams, names: tuple[str, ...], theta: NDArray[np.float64]) -> VehicleParams:
    return replace(base, **{n: float(np.exp(t)) for n, t in zip(names, theta)})


def lag1_autocorrelation(x: NDArray[np.float64]) -> float:
    x = np.asarray(x, dtype=float) - np.mean(x)
    denom = float(np.dot(x, x))
    return float(np.dot(x[:-1], x[1:]) / denom) if denom > 0 else 0.0


def effective_sample_size(n: int, r1: float) -> float:
    r1 = float(np.clip(r1, 0.0, 0.999))
    return max(2.0, n * (1.0 - r1) / (1.0 + r1))


def calibrate_lapsim(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    observed_speed_ms: NDArray[np.float64],
    base: VehicleParams,
    observed_lap_time_s: float,
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
    priors: dict[str, tuple[float, float]] | None = None,
) -> CalibrationResult:
    """Fit lap-simulator parameters to a measured speed trace (MAP + Laplace posterior)."""
    priors = {**DEFAULT_PRIORS, **(priors or {})}
    use_low_drag = low_drag_mask is not None and bool(np.any(low_drag_mask))
    names = PARAM_NAMES if use_low_drag else PARAM_NAMES[:5]
    if use_low_drag and base.low_drag_cda_m2 is None:
        base = replace(base, low_drag_cda_m2=base.cda_m2 * 0.8)
    prior_mu = np.log([priors[n][0] for n in names])
    prior_sd = np.array([priors[n][1] for n in names])
    mask = low_drag_mask if use_low_drag else None

    def sim(theta: NDArray[np.float64]) -> LapSimResult:
        return simulate_lap(distance_m, kappa, _params_from_theta(base, names, theta), mask, lap_length_m)

    def residuals(theta: NDArray[np.float64], sigma: float, weight: float) -> NDArray[np.float64]:
        r_data = (sim(theta).speed_ms - observed_speed_ms) / sigma * np.sqrt(weight)
        return np.concatenate([r_data, (theta - prior_mu) / prior_sd])

    theta0 = np.log([getattr(base, n) for n in names])
    n = len(observed_speed_ms)
    sigma, weight = 3.0, 1.0
    fit = None
    for _ in range(3):  # alternate: fit theta given sigma and n_eff, then re-estimate both
        fit = least_squares(residuals, theta0, args=(sigma, weight), method="trf", x_scale=1.0,
                            diff_step=1e-3, max_nfev=400)
        theta0 = fit.x
        resid = sim(fit.x).speed_ms - observed_speed_ms
        sigma = float(max(np.std(resid), 0.05))
        r1 = lag1_autocorrelation(resid)
        weight = effective_sample_size(n, r1) / n
    assert fit is not None
    fit = least_squares(residuals, theta0, args=(sigma, weight), method="trf", diff_step=1e-3, max_nfev=400)
    jac = fit.jac
    cov = np.linalg.pinv(jac.T @ jac)

    best = sim(fit.x)
    resid = best.speed_ms - observed_speed_ms
    return CalibrationResult(
        params=_params_from_theta(base, names, fit.x),
        names=names,
        theta_map=fit.x,
        cov_log=cov,
        noise_sigma_ms=sigma,
        lag1_autocorr=lag1_autocorrelation(resid),
        n_effective=weight * n,
        sim=best,
        observed_speed_ms=observed_speed_ms,
        rmse_kmh=float(np.sqrt(np.mean(resid**2)) * 3.6),
        lap_time_error_s=float(best.lap_time_s - observed_lap_time_s),
        converged=bool(fit.success),
    )


def posterior_lap_times(
    cal: CalibrationResult,
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
    n_draws: int = 200,
    seed: int = 7,
) -> NDArray[np.float64]:
    """Simulated lap times (s) for parameter draws from the Laplace posterior."""
    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(cal.theta_map, cal.cov_log, size=n_draws)
    mask = low_drag_mask if "low_drag_cda_m2" in cal.names else None
    return np.array(
        [
            simulate_lap(distance_m, kappa, _params_from_theta(cal.params, cal.names, th), mask, lap_length_m).lap_time_s
            for th in draws
        ]
    )


def metropolis_posterior(
    cal: CalibrationResult,
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
    n_steps: int = 3000,
    burn_in: int = 500,
    seed: int = 11,
    priors: dict[str, tuple[float, float]] | None = None,
) -> tuple[NDArray[np.float64], float]:
    """Random-walk Metropolis samples of the log-parameters after burn-in, and the acceptance rate.

    Proposals use the scaled Laplace covariance; the samples check the Laplace approximation.
    """
    priors = {**DEFAULT_PRIORS, **(priors or {})}
    names = cal.names
    prior_mu = np.log([priors[n][0] for n in names])
    prior_sd = np.array([priors[n][1] for n in names])
    mask = low_drag_mask if "low_drag_cda_m2" in names else None
    weight = cal.n_effective / len(cal.observed_speed_ms)

    def log_post(theta: NDArray[np.float64]) -> float:
        v = simulate_lap(distance_m, kappa, _params_from_theta(cal.params, names, theta), mask, lap_length_m).speed_ms
        ll = -0.5 * weight * float(np.sum(((v - cal.observed_speed_ms) / cal.noise_sigma_ms) ** 2))
        return ll - 0.5 * float(np.sum(((theta - prior_mu) / prior_sd) ** 2))

    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(cal.cov_log * (2.38**2 / len(names)) + 1e-12 * np.eye(len(names)))
    theta = cal.theta_map.copy()
    lp = log_post(theta)
    out, accepted = [], 0
    for step in range(n_steps):
        prop = theta + chol @ rng.standard_normal(len(names))
        lp_prop = log_post(prop)
        if np.log(rng.uniform()) < lp_prop - lp:
            theta, lp = prop, lp_prop
            accepted += 1
        if step >= burn_in:
            out.append(theta.copy())
    return np.array(out), accepted / n_steps


@dataclass(frozen=True)
class DiscrepancyResult:
    distance_m: NDArray[np.float64]
    mean_kmh: NDArray[np.float64]
    std_kmh: NDArray[np.float64]
    length_scale_m: float
    noise_kmh: float


def fit_discrepancy_gp(
    distance_m: NDArray[np.float64],
    residual_ms: NDArray[np.float64],
    subsample: int = 3,
) -> DiscrepancyResult:
    """GP regression of the model discrepancy delta(s) = v_obs - v_sim along the lap (km/h)."""
    s = distance_m[::subsample, None]
    y = residual_ms[::subsample] * 3.6
    kernel = ConstantKernel(25.0, (1e-2, 1e4)) * RBF(60.0, (10.0, 2000.0)) + WhiteKernel(4.0, (1e-3, 1e3))
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=False, n_restarts_optimizer=1, random_state=0)
    gp.fit(s, y)
    mean, std = gp.predict(distance_m[:, None], return_std=True)
    k = gp.kernel_
    return DiscrepancyResult(
        distance_m=distance_m,
        mean_kmh=mean,
        std_kmh=std,
        length_scale_m=float(k.k1.k2.length_scale),
        noise_kmh=float(np.sqrt(k.k2.noise_level)),
    )
