"""Fuel- and tyre-corrected race pace, fitted from every green-flag lap of a race.

Model (ordinary least squares with fixed effects, one race at a time):

    t(d, l) = alpha_d + delta_c + gamma_c * age + beta * lap + e

    alpha_d   driver pace on the reference compound, fresh tyres, zero laps of fuel burn
    delta_c   compound offset vs the reference compound (most-used compound)
    gamma_c   tyre degradation per lap of tyre age, per compound
    beta      fuel effect per lap (negative: the car gets lighter)

Fuel and tyre age are separable because tyre age resets at every stop while lap number
does not. Laps are filtered to green-flag running (no pit in/out laps, no lap 1, track
status '1', within 107% of the driver's median) and gross outliers are trimmed iteratively.
Uncertainty comes from a wild cluster bootstrap by driver (Cameron, Gelbach and Miller
2008) with Webb's six-point weights, which behave well with ~20 clusters. Every draw keeps
the design fixed and repeats the outlier trimming. The tests check interval coverage by
Monte Carlo with autocorrelated within-stint errors and stint-level offsets. With fewer
than about 12 drivers (clusters) the intervals become too narrow.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SLICKS = ("SOFT", "MEDIUM", "HARD")


@dataclass(frozen=True)
class RacePaceResult:
    fuel_s_per_lap: float
    fuel_ci90: tuple[float, float]
    deg_s_per_lap: dict[str, float]
    deg_ci90: dict[str, tuple[float, float]]
    reference_compound: str
    driver_pace: pd.DataFrame  # driver, team, pace_s, ci_lo, ci_hi, n_laps
    team_pace: pd.DataFrame  # team, pace_s, gap_s, ci_lo, ci_hi (gap to fastest team)
    n_laps: int
    residual_sd_s: float


def clean_race_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Green-flag racing laps on slick tyres."""
    d = laps.copy()
    d = d[d["time"].notna() & (d["lap"] >= 2) & ~d["is_pit_in"] & ~d["is_pit_out"]]
    d = d[(d["status"] == "1") & ~d["del"] & d["compound"].isin(SLICKS) & d["life"].notna()]
    med = d.groupby("drv")["time"].transform("median")
    d = d[d["time"] <= 1.07 * med]
    d["stint_key"] = d["drv"].astype(str) + "_" + d["stint"].astype(str)
    return d.reset_index(drop=True)


def _design(d: pd.DataFrame, ref: str) -> tuple[np.ndarray, list[str]]:
    drivers = sorted(d["drv"].unique())
    comps = sorted(d["compound"].unique())
    cols, names = [], []
    for drv in drivers:
        cols.append((d["drv"] == drv).to_numpy(float))
        names.append(f"alpha:{drv}")
    for c in comps:
        if c != ref:
            cols.append((d["compound"] == c).to_numpy(float))
            names.append(f"delta:{c}")
    for c in comps:
        cols.append(((d["compound"] == c) * d["life"]).to_numpy(float))
        names.append(f"gamma:{c}")
    cols.append(d["lap"].to_numpy(float))
    names.append("beta")
    return np.column_stack(cols), names


def _fit(
    d: pd.DataFrame, ref: str, trim_iters: int = 2, weights: np.ndarray | None = None
) -> tuple[pd.Series, pd.DataFrame, float]:
    x, names = _design(d, ref)
    y = d["time"].to_numpy()
    if weights is not None:
        sw = np.sqrt(weights)
        beta = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)[0]
        return pd.Series(beta, index=names), d, float("nan")
    keep = np.ones(len(d), dtype=bool)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    for _ in range(trim_iters):
        resid = y - x @ beta
        mad = 1.4826 * np.median(np.abs(resid[keep] - np.median(resid[keep])))
        keep = np.abs(resid - np.median(resid[keep])) <= 3.0 * max(mad, 0.05)
        beta = np.linalg.lstsq(x[keep], y[keep], rcond=None)[0]
    coef = pd.Series(beta, index=names)
    return coef, d[keep].reset_index(drop=True), float(np.std(y[keep] - x[keep] @ beta))


def fit_race_pace(
    laps: pd.DataFrame,
    driver_team: dict[str, str],
    n_boot: int = 200,
    seed: int = 1,
    min_laps_per_driver: int = 10,
) -> RacePaceResult | None:
    """Fit the race pace model; returns None for races with too little clean slick running."""
    d = clean_race_laps(laps)
    counts = d["drv"].value_counts()
    d = d[d["drv"].isin(counts[counts >= min_laps_per_driver].index)].reset_index(drop=True)
    if d["drv"].nunique() < 6 or d["compound"].nunique() < 1:
        return None
    ref = str(d["compound"].value_counts().idxmax())
    x_check, _ = _design(d, ref)
    if np.linalg.matrix_rank(x_check) < x_check.shape[1]:
        # Fuel and tyre age are only separable when stints start on different laps
        return None
    coef, used, resid_sd = _fit(d, ref)

    # Wild cluster bootstrap by driver (Webb six-point weights), trimming repeated in every
    # draw. Residuals of one driver share a weight, so within-driver correlation (traffic,
    # tyre state, stint offsets) is preserved.
    rng = np.random.default_rng(seed)
    x_used, names_used = _design(used, ref)
    fitted = x_used @ coef.reindex(names_used).to_numpy()
    resid = used["time"].to_numpy() - fitted
    drv_codes, drv_index = np.unique(used["drv"].to_numpy(), return_inverse=True)
    webb = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])
    boots = []
    for _ in range(n_boot):
        w = rng.choice(webb, size=len(drv_codes))[drv_index]
        b, _, _ = _fit(used.assign(time=fitted + w * resid), ref, trim_iters=2)
        boots.append(b.reindex(coef.index))
    bt = pd.DataFrame(boots)

    def ci(name: str) -> tuple[float, float]:
        col = bt[name].dropna()
        if len(col) <= 10:
            return (np.nan, np.nan)
        return float(col.quantile(0.05)), float(col.quantile(0.95))

    drivers = sorted(used["drv"].unique())
    dp = pd.DataFrame(
        {
            "driver": drivers,
            "team": [driver_team.get(x, "") for x in drivers],
            "pace_s": [coef[f"alpha:{x}"] for x in drivers],
            "ci_lo": [ci(f"alpha:{x}")[0] for x in drivers],
            "ci_hi": [ci(f"alpha:{x}")[1] for x in drivers],
            "n_laps": [int((used["drv"] == x).sum()) for x in drivers],
        }
    )
    # Team pace = faster driver's corrected pace; CI from the bootstrap of that statistic
    teams = sorted(dp["team"].unique())
    team_vals = {t: dp[dp["team"] == t]["pace_s"].min() for t in teams}
    team_boot = {
        t: bt[[f"alpha:{x}" for x in dp[dp["team"] == t]["driver"]]].min(axis=1).to_numpy() for t in teams
    }
    best = min(team_vals.values())
    best_boot = np.min(np.vstack(list(team_boot.values())), axis=0)

    def gap_ci(t: str) -> tuple[float, float]:
        diff = team_boot[t] - best_boot
        return float(np.nanquantile(diff, 0.05)), float(np.nanquantile(diff, 0.95))

    cis = {t: gap_ci(t) for t in teams}
    tp = pd.DataFrame(
        {
            "team": teams,
            "pace_s": [team_vals[t] for t in teams],
            "gap_s": [team_vals[t] - best for t in teams],
            "ci_lo": [cis[t][0] for t in teams],
            "ci_hi": [cis[t][1] for t in teams],
        }
    ).sort_values("gap_s").reset_index(drop=True)

    comps = sorted(used["compound"].unique())
    return RacePaceResult(
        fuel_s_per_lap=float(coef["beta"]),
        fuel_ci90=ci("beta"),
        deg_s_per_lap={c: float(coef[f"gamma:{c}"]) for c in comps},
        deg_ci90={c: ci(f"gamma:{c}") for c in comps},
        reference_compound=ref,
        driver_pace=dp,
        team_pace=tp,
        n_laps=len(used),
        residual_sd_s=resid_sd,
    )
