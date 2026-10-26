"""Corner minimum-speed model across a season: physics baseline, ML, and hybrid.

Each row is one corner on one driver's fastest qualifying lap. The target is the minimum
speed through the corner. Features are things the driver does not control on that lap:
corner geometry (from the multi-driver consensus path), air density, the headwind
component at the corner, track temperature, tyre age and season. The target never enters
a feature, which is what the original prototype got wrong.

Models, all evaluated with GroupKFold over *circuits* (every event at a circuit, in both
seasons, is held out together, so the model never sees the test track):
  steady    v^2 = a R / (1 - b rho R): the steady-state cornering limit with aero grip,
            with (a, b) fitted on the training folds only
  physics   the lap simulator run on the event's geometry with a nominal car whose
            parameters are the median of the *training-fold* events' calibrations
            (`sim_fn`; falls back to `steady` where no simulation exists). Unlike the
            steady-state limit it knows that fast corners are reached at power-limited speed.
  ml        gradient-boosted trees on the raw features
  hybrid    gradient-boosted trees on the residual of `physics`

Prediction intervals use split conformal calibration across folds: the interval width for
fold k comes only from residuals on the *other* folds. Coverage is marginal: it is reported
per event as well, because it varies a lot between tracks.

Almost all of the target's variance is between corners (a hairpin vs a flat-out kink), so
R^2 mostly measures geometry. The `within_corner_r2` metric asks the harder question:
how well the model explains differences between cars at the *same* corner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from math import factorial

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

NUMERIC_FEATURES = [
    "radius_m", "turn_angle_deg", "approach_m", "rho_kg_m3", "headwind_ms",
    "track_temp_c", "tyre_life", "season_2026",
]
V_CAP_KMH = 345.0


def physics_speed_kmh(radius_m: np.ndarray, rho: np.ndarray, a: float, b: float) -> np.ndarray:
    """Steady-state cornering limit v^2 = a R / (1 - b rho R), capped where aero grip wins."""
    denom = 1.0 - b * rho * radius_m
    v2 = np.where(denom > 0.02, a * radius_m / np.maximum(denom, 0.02), (V_CAP_KMH / 3.6) ** 2)
    return np.minimum(np.sqrt(np.maximum(v2, 1.0)) * 3.6, V_CAP_KMH)


def fit_physics(df: pd.DataFrame) -> tuple[float, float]:
    """Fit (a = mu g, b = mu ClA / (2 m)) by robust least squares on grip-limited corners."""
    r, rho, v = df["radius_m"].to_numpy(), df["rho_kg_m3"].to_numpy(), df["v_min_kmh"].to_numpy()

    def resid(p: np.ndarray) -> np.ndarray:
        return physics_speed_kmh(r, rho, np.exp(p[0]), np.exp(p[1])) - v

    fit = least_squares(resid, x0=np.log([18.0, 0.0024]), loss="soft_l1", f_scale=10.0)
    return float(np.exp(fit.x[0])), float(np.exp(fit.x[1]))


def _gbm() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=30,
        l2_regularization=1.0, random_state=0,
    )


def _matrix(df: pd.DataFrame, use_team: bool, teams: list[str]) -> np.ndarray:
    cols = [df[NUMERIC_FEATURES].to_numpy(float)]
    if use_team:
        cols.append(np.column_stack([(df["team"] == t).to_numpy(float) for t in teams]))
    return np.column_stack(cols)


@dataclass(frozen=True)
class CornerModelReport:
    metrics: pd.DataFrame  # model, rmse_kmh, mae_kmh, r2 (out-of-fold)
    oof: pd.DataFrame  # rows + physics/ml/hybrid OOF predictions
    conformal_coverage: float
    conformal_halfwidth_kmh: float
    coverage_by_class: dict[str, float]
    coverage_by_event: dict[str, float]
    physics_params: tuple[float, float]  # fitted on all data, for reporting
    feature_names: list[str]


def cross_validate(
    df: pd.DataFrame,
    n_splits: int = 5,
    alpha: float = 0.10,
    use_team: bool = False,
    group_col: str = "circuit",
    sim_fn: Callable[[set[str]], pd.DataFrame] | None = None,
) -> CornerModelReport:
    """Grouped (by circuit) cross-validation of steady, physics, ML and hybrid models.

    `sim_fn(train_event_keys)` returns columns (event_key, corner_key, v_sim_kmh) computed with
    a nominal car from the training events only, so no calibration from a test event
    reaches the physics baseline.
    """
    df = df.reset_index(drop=True).copy()
    groups = df[group_col if group_col in df else "event_key"].to_numpy()
    teams = sorted(df["team"].unique())
    y = df["v_min_kmh"].to_numpy()
    oof = {m: np.full(len(df), np.nan) for m in ("steady", "physics", "ml", "hybrid")}
    fold_id = np.full(len(df), -1)
    gkf = GroupKFold(n_splits=min(n_splits, len(np.unique(groups))))
    for k, (tr, te) in enumerate(gkf.split(df, y, groups)):
        fold_id[te] = k
        a, b = fit_physics(df.iloc[tr])
        steady = physics_speed_kmh(df["radius_m"].to_numpy(), df["rho_kg_m3"].to_numpy(), a, b)
        if sim_fn is not None:
            sims = sim_fn(set(df["event_key"].iloc[tr]))
            v_sim = df[["event_key", "corner_key"]].merge(sims, on=["event_key", "corner_key"], how="left")["v_sim_kmh"].to_numpy()
        elif "v_sim_kmh" in df:
            v_sim = df["v_sim_kmh"].to_numpy()
        else:
            v_sim = np.full(len(df), np.nan)
        phys = np.where(np.isfinite(v_sim), v_sim, steady)
        phys_tr, phys_te = phys[tr], phys[te]
        x = _matrix(df, use_team, teams)
        oof["steady"][te] = steady[te]
        oof["physics"][te] = phys_te
        oof["ml"][te] = _gbm().fit(x[tr], y[tr]).predict(x[te])
        oof["hybrid"][te] = phys_te + _gbm().fit(x[tr], y[tr] - phys_tr).predict(x[te])

    rows = []
    cell = df["event_key"].astype(str) + "|" + df["corner_key"].astype(str)
    y_within = y - df.groupby(cell)["v_min_kmh"].transform("mean").to_numpy()
    for m, pred in oof.items():
        err = y - pred
        p_within = pred - pd.Series(pred).groupby(cell.to_numpy()).transform("mean").to_numpy()
        rows.append({
            "model": m,
            "rmse_kmh": float(np.sqrt(np.mean(err**2))),
            "mae_kmh": float(np.mean(np.abs(err))),
            "r2": float(1 - np.sum(err**2) / np.sum((y - y.mean()) ** 2)),
            "within_corner_r2": float(1 - np.sum((y_within - p_within) ** 2) / np.sum(y_within**2)),
        })

    # Split-conformal across folds: interval width for fold k from the other folds only
    abs_r = np.abs(y - oof["hybrid"])
    covered = np.zeros(len(df), dtype=bool)
    widths = np.zeros(len(df))
    for k in np.unique(fold_id):
        other = abs_r[fold_id != k]
        n = len(other)
        level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
        q = float(np.quantile(other, level))
        covered[fold_id == k] = abs_r[fold_id == k] <= q
        widths[fold_id == k] = q
    out = df.assign(pred_steady=oof["steady"], pred_physics=oof["physics"], pred_ml=oof["ml"], pred_hybrid=oof["hybrid"],
                    conformal_halfwidth=widths, covered=covered, fold=fold_id)
    by_class = out.groupby("speed_class")["covered"].mean().to_dict()
    per_event = out.groupby("event_key")["covered"].mean()
    names = NUMERIC_FEATURES + ([f"team:{t}" for t in teams] if use_team else [])
    return CornerModelReport(
        metrics=pd.DataFrame(rows),
        oof=out,
        conformal_coverage=float(covered.mean()),
        conformal_halfwidth_kmh=float(widths.mean()),
        coverage_by_class={str(k): float(v) for k, v in by_class.items()},
        coverage_by_event={str(k): float(v) for k, v in per_event.items()},
        physics_params=fit_physics(df),
        feature_names=names,
    )


# --------------------------------------------------------------------------- team effects
def team_corner_deficit(oof: pd.DataFrame, n_boot: int = 400, seed: int = 4) -> pd.DataFrame:
    """Corner minimum speed vs the *other* teams at the same corner (km/h), by corner class.

    At one corner of one event, geometry and conditions are shared, so this is essentially a
    like-for-like speed comparison (the model's residual cancels almost entirely once the
    corner mean is removed). The comparison excludes the team itself. Bootstrap over events.
    """
    d = oof.assign(resid=oof["v_min_kmh"] - oof["pred_hybrid"])
    key = d["event_key"].astype(str) + "|" + d["corner_key"].astype(str)
    team_mean = d.groupby([key, d["team"]])["resid"].transform("mean")
    tot = d.groupby(key)["resid"].transform("sum")
    cnt = d.groupby(key)["resid"].transform("size")
    team_sum = d.groupby([key, d["team"]])["resid"].transform("sum")
    team_cnt = d.groupby([key, d["team"]])["resid"].transform("size")
    others = (tot - team_sum) / (cnt - team_cnt).replace(0, np.nan)
    d["resid"] = team_mean - others
    events = d["event_key"].unique()
    rng = np.random.default_rng(seed)
    rows = []
    for (team, cls), g in d.groupby(["team", "speed_class"]):
        by_ev = g.groupby("event_key")["resid"].mean()
        boots = [by_ev.reindex(rng.choice(events, len(events))).dropna().mean() for _ in range(n_boot)]
        rows.append({
            "team": team, "speed_class": cls, "deficit_kmh": float(by_ev.mean()),
            "ci_lo": float(np.nanpercentile(boots, 5)), "ci_hi": float(np.nanpercentile(boots, 95)),
            "n_events": int(by_ev.size),
        })
    return pd.DataFrame(rows)


def wind_sensitivity(df: pd.DataFrame, n_boot: int = 400, seed: int = 6) -> pd.DataFrame:
    """Effect of headwind on corner minimum speed (km/h per m/s), by corner speed class.

    Identification: corner fixed effects (same corner across seasons and laps) and
    team-season fixed effects absorb geometry and car pace; the headwind coefficient is
    then estimated from the same corner driven under different wind. Bootstrap over events.
    """
    rows = []
    rng = np.random.default_rng(seed)
    for cls, g in df.groupby("speed_class"):
        g = g.reset_index(drop=True)
        if len(g) < 200:
            continue

        def coef(d: pd.DataFrame) -> float:
            x = pd.concat([
                pd.get_dummies(d["circuit_corner"], dtype=float),
                pd.get_dummies(d["team"] + d["season"].astype(str), dtype=float).iloc[:, 1:],
                d[["headwind_ms", "rho_kg_m3", "track_temp_c"]],
            ], axis=1).to_numpy(float)
            return float(np.linalg.lstsq(x, d["v_min_kmh"].to_numpy(float), rcond=None)[0][-3])

        est = coef(g)
        events = g["event_key"].unique()
        boots = []
        for _ in range(n_boot):
            pick = rng.choice(events, len(events))
            boots.append(coef(pd.concat([g[g["event_key"] == e] for e in pick], ignore_index=True)))
        rows.append({"speed_class": cls, "kmh_per_ms_headwind": est,
                     "ci_lo": float(np.percentile(boots, 5)), "ci_hi": float(np.percentile(boots, 95)), "n": len(g)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Shapley
def exact_baseline_shapley(
    predict: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    baseline: np.ndarray,
    groups: list[list[int]],
) -> np.ndarray:
    """Exact Shapley values of `predict` for each row of x, over feature *groups*.

    Value of a coalition S: f(x with features outside S set to the baseline). Every one of
    the 2^M coalitions is evaluated, so the values satisfy efficiency exactly:
    sum_j phi_j(x) = f(x) - f(baseline). Feasible for M <= ~12 groups.
    """
    m = len(groups)
    n = x.shape[0]
    value: dict[frozenset[int], np.ndarray] = {}
    for size in range(m + 1):
        for coal in combinations(range(m), size):
            xs = np.tile(baseline, (n, 1))
            for j in coal:
                xs[:, groups[j]] = x[:, groups[j]]
            value[frozenset(coal)] = predict(xs)
    phi = np.zeros((n, m))
    for j in range(m):
        others = [i for i in range(m) if i != j]
        for size in range(m):
            w = factorial(size) * factorial(m - size - 1) / factorial(m)
            for coal in combinations(others, size):
                s = frozenset(coal)
                phi[:, j] += w * (value[s | {j}] - value[s])
    return phi


def hybrid_shapley(df: pd.DataFrame, rows: np.ndarray) -> tuple[pd.DataFrame, list[str]]:
    """Exact Shapley attribution of the reported hybrid model (lap-sim prior + boosted residual).

    Groups: the physics prior `v_sim_kmh` (one group) and each remaining feature. The model is
    refitted on all rows for attribution; validation numbers come from `cross_validate`.
    """
    d = df[df["v_sim_kmh"].notna()].reset_index(drop=True) if "v_sim_kmh" in df else df
    if "v_sim_kmh" not in d or d.empty:
        return pd.DataFrame(), []
    sel_mask = np.zeros(len(df), dtype=bool)
    sel_mask[np.asarray(rows)] = True
    sel = sel_mask[df["v_sim_kmh"].notna().to_numpy()]
    x_feat = d[NUMERIC_FEATURES].to_numpy(float)
    gbm = _gbm().fit(x_feat, d["v_min_kmh"].to_numpy() - d["v_sim_kmh"].to_numpy())
    x_all = np.column_stack([d["v_sim_kmh"].to_numpy(), x_feat])

    def predict(xm: np.ndarray) -> np.ndarray:
        return xm[:, 0] + gbm.predict(xm[:, 1:])

    names = ["physics_prior"] + NUMERIC_FEATURES
    phi = exact_baseline_shapley(predict, x_all[sel], np.median(x_all, axis=0), [[i] for i in range(len(names))])
    out = pd.DataFrame(phi, columns=names)
    out.index = np.flatnonzero(sel)
    return out, names
