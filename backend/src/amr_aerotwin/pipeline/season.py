"""Build the multi-season dataset and the season-level analyses.

    fetch     download every event's files into the cache (threads)
    build     process events in parallel (processes), write per-event JSON and tables
    analyse   season analyses on the tables -> data/processed/season.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from amr_aerotwin.data.repository import DEFAULT_CACHE_DIR, DataUnavailableError, TelemetryRepository
from amr_aerotwin.domain import DATA_DIR, TARGET_TEAM
from amr_aerotwin.modeling.corner_model import (
    cross_validate,
    hybrid_shapley,
    team_corner_deficit,
)
from amr_aerotwin.modeling.energy import relative_metric, speed_gap_profile
from amr_aerotwin.modeling.intervals import boot_ci, boot_ci_columns
from amr_aerotwin.modeling.powertrain import joint_deficit  # noqa: F401  (used by powertrain_analysis)
from amr_aerotwin.modeling.season import (
    bayesian_changepoint,
    car_vs_driver_variance,
    changepoint_count_evidence,
    supertime_table,
    upgrade_effects,
)
from amr_aerotwin.physics.dynamics import corner_speed_class
from amr_aerotwin.physics.lapsim import VehicleParams, simulate_lap
from amr_aerotwin.pipeline.event import _r, prefetch_event, safe_process_event

log = logging.getLogger(__name__)
PROCESSED_DIR = DATA_DIR / "processed"
UPGRADES_CSV = DATA_DIR / "reference" / "amr_upgrades.csv"
RECENT_DAYS = 10  # events this recent are re-downloaded on fetch (timing data may still change)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def event_calendar(repo: TelemetryRepository, years: list[int], refresh: bool = False) -> pd.DataFrame:
    """Events that have a qualifying session, ordered by date.

    `round` is the event's position among events with data in that season, not the
    official championship round (cancelled events are absent from the archive).
    """
    rows = []
    for y in years:
        for ev in repo.list_events(y, refresh=refresh):
            try:
                laps = repo.session_laps(y, ev, "Qualifying")
            except DataUnavailableError:
                continue
            date = laps["lSD"].dropna().min() if "lSD" in laps else None
            if date is None or pd.isna(date) or laps["time"].notna().sum() < 10:
                continue
            rows.append({"season": y, "event": ev, "date": str(date)[:10]})
    if not rows:
        return pd.DataFrame(columns=["season", "event", "date", "round"])
    cal = pd.DataFrame(rows).sort_values(["season", "date"]).reset_index(drop=True)
    cal["round"] = cal.groupby("season").cumcount() + 1
    return cal


def fetch(years: list[int], cache_dir: Path = DEFAULT_CACHE_DIR, workers: int = 6) -> pd.DataFrame:
    repo = TelemetryRepository(cache_dir, offline=False)
    cal = event_calendar(repo, years, refresh=True)
    cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    for r in cal[cal["date"] >= cutoff].itertuples():
        log.info("re-fetching recent event %s %s (%d cached files)", r.season, r.event, repo.invalidate_event(r.season, r.event))
    failures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(prefetch_event, repo, r.season, r.event): r for r in cal.itertuples()}
        for f in as_completed(futs):
            r = futs[f]
            try:
                f.result()
                log.info("fetched %s %s", r.season, r.event)
            except Exception as err:  # noqa: BLE001
                log.warning("fetch failed %s %s: %s", r.season, r.event, err)
                failures[f"{r.season}|{r.event}"] = str(err)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    (PROCESSED_DIR / "fetch_failures.json").write_text(json.dumps(failures, indent=1), encoding="utf-8")
    return cal


def _fetch_failures(out_dir: Path) -> dict[str, str]:
    p = out_dir / "fetch_failures.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _worker(args: tuple[str, int, str, int, bool]) -> Any:
    cache, year, event, round_no, mcmc = args
    repo = TelemetryRepository(Path(cache), offline=True)
    return safe_process_event(repo, year, event, round_no, mcmc)


def build(
    years: list[int],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    out_dir: Path = PROCESSED_DIR,
    processes: int | None = None,
    run_mcmc: bool = True,
) -> dict[str, pd.DataFrame]:
    """Process every cached event and write per-event JSON plus season tables."""
    repo = TelemetryRepository(cache_dir, offline=True)
    cal = event_calendar(repo, years)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "events.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    jobs = [(str(cache_dir), int(r.season), r.event, int(r.round), run_mcmc) for r in cal.itertuples()]
    outputs: list[Any] = []
    skipped: list[dict[str, Any]] = []
    n_proc = processes or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=n_proc) as pool:
        futures = {pool.submit(_worker, job): job for job in jobs}
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                res = fut.result()
            except Exception as err:  # noqa: BLE001 - a crashed worker must not lose the season
                res = f"worker crashed: {type(err).__name__}: {err}"
            if isinstance(res, str):
                fetch_fail = _fetch_failures(out_dir).get(f"{job[1]}|{job[2]}")
                if fetch_fail and "Not cached" in res:
                    res = f"archive file unavailable at fetch time ({fetch_fail})"
                log.warning("skipped %s %s: %s", job[1], job[2], res)
                skipped.append({"season": job[1], "event": job[2], "reason": res})
                continue
            outputs.append(res)
            path = staging / f"{job[1]}-{slug(job[2])}.json"
            path.write_text(json.dumps(_r(res.summary, 6), separators=(",", ":"), allow_nan=False), encoding="utf-8")
            log.info("built %s %s", job[1], job[2])
    if not outputs:
        shutil.rmtree(staging)
        raise RuntimeError("No event could be processed; previous outputs were left untouched.")

    # Swap in the new event files only once the whole build has finished
    final = out_dir / "events"
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)
    outputs.sort(key=lambda o: (o.summary["season"], o.summary["round"]))

    def cat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    tables = {
        "drivers": cat([o.driver_rows for o in outputs]),
        "teams": cat([o.team_rows for o in outputs]),
        "corners": cat([o.corner_rows for o in outputs]),
        "race_pace": cat([o.race_rows for o in outputs]),
        "accel": cat([o.accel_rows for o in outputs]),
        "profile": cat([o.profile_rows for o in outputs]),
        "timing": cat([o.timing_rows for o in outputs]),
        "sections": cat([o.section_rows for o in outputs]),
    }
    for name, df in tables.items():
        tmp = out_dir / f".{name}.csv.gz.tmp"
        df.to_csv(tmp, index=False, compression="gzip")
        tmp.replace(out_dir / f"{name}.csv.gz")
    cal.to_csv(out_dir / "calendar.csv", index=False)
    (out_dir / "skipped.json").write_text(json.dumps(sorted(skipped, key=lambda r: (r["season"], r["event"])), indent=1), encoding="utf-8")
    return tables


def load_tables(out_dir: Path = PROCESSED_DIR) -> dict[str, pd.DataFrame]:
    def read(name: str) -> pd.DataFrame:
        try:
            return pd.read_csv(out_dir / f"{name}.csv.gz")
        except (pd.errors.EmptyDataError, FileNotFoundError):
            return pd.DataFrame()
    return {n: read(n) for n in ("drivers", "teams", "corners", "race_pace", "accel", "profile", "timing", "sections")}


# --------------------------------------------------------------------------- analyses
def rel_to_other_teams(df: pd.DataFrame, col: str, keys: tuple[str, ...] = ("season", "round")) -> pd.Series:
    """Each team's value divided by the median of the *other* teams at the same event."""
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby(list(keys)):
        for i, row in g.iterrows():
            o = g.loc[g["team"] != row["team"], col].dropna()
            if len(o) >= 4 and np.isfinite(row[col]):
                out[i] = row[col] / o.median()
    return out


def _bootstrap_mean(values: np.ndarray, n_boot: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = [rng.choice(v, len(v)).mean() for _ in range(n_boot)]
    lo, hi = boot_ci(boots, len(v))
    return float(v.mean()), lo, hi


def aero_map(teams: pd.DataFrame, events: dict[str, dict]) -> dict[str, Any]:
    """Per season: each team's high-speed grip and straight-line speed relative to the field.

    Converted to ClA- and CdA-equivalent % so lap-time sensitivity lines can be overlaid:
      dClA% ~ dGrip_high% / aero_share  (grip_high = mu (g + q ClA / m))
      dCdA% ~ -3 dV%                     (drag-limited speed  v ~ CdA^(-1/3))
    """
    t = teams[teams["geometry_ok"].astype(bool)].copy()
    share = t.groupby(["season", "round"])["aero_share_high"].transform("median")
    t["d_grip_pct"] = (rel_to_other_teams(t, "grip_high_g") - 1) * 100
    t["d_cla_equiv_pct"] = t["d_grip_pct"] / share.clip(lower=0.2)
    t["d_speed_pct"] = t["straight_speed_delta_kmh"] / t["straight_peak_kmh"] * 100
    t["d_cda_equiv_pct"] = -3.0 * t["d_speed_pct"]
    out: dict[str, Any] = {}
    for season, g in t.groupby("season"):
        rows = []
        for team, gt in g.groupby("team"):
            x = _bootstrap_mean(gt["d_cla_equiv_pct"].to_numpy())
            y = _bootstrap_mean(gt["d_cda_equiv_pct"].to_numpy())
            gl = _bootstrap_mean(gt["grip_low_g"].to_numpy() - g[g["round"].isin(gt["round"])].groupby("round")["grip_low_g"].transform("median").reindex(gt.index).to_numpy())
            rows.append({"team": team, "color": gt["color"].iloc[0], "n_events": int(gt["d_cla_equiv_pct"].notna().sum()),
                         "d_cla_equiv_pct": x, "d_cda_equiv_pct": y, "d_grip_low_g": gl,
                         "mean_gap_pct": float(gt["gap_pct"].mean())})
        sens = [e["lapsim"][e["iso_lap_time"]["car"]]["sensitivities"] for e in events.values()
                if e["season"] == season and e.get("iso_lap_time") and e["iso_lap_time"]["car"] in e.get("lapsim", {})]
        out[str(season)] = {
            "teams": _r(rows, 3),
            "season_sensitivity": {
                "cla_plus_1pct_s": _r(np.mean([s["cla_m2_plus_1pct_s"] for s in sens]), 4) if sens else None,
                "cda_plus_1pct_s": _r(np.mean([s["cda_m2_plus_1pct_s"] for s in sens]), 4) if sens else None,
                "n_events": len(sens),
            },
            "per_event": _r(t[t["season"] == season][["round", "event", "team", "d_cla_equiv_pct", "d_cda_equiv_pct", "gap_pct"]].to_dict("records"), 3),
        }
    return out


def circuit_sensitivities(events: dict[str, dict]) -> list[dict[str, Any]]:
    """Lap-time value of downforce, drag, power and mass at each circuit (calibrated lap sim)."""
    rows = []
    for e in events.values():
        car = (e.get("iso_lap_time") or {}).get("car")
        if not car or car not in e.get("lapsim", {}):
            continue
        s = e["lapsim"][car]["sensitivities"]
        rows.append({"season": e["season"], "round": e["round"], "event": e["event"], "car": car,
                     **{k: s[k] for k in s}, "lap_time_error_s": e["lapsim"][car]["lap_time_error_s"],
                     "rmse_kmh": e["lapsim"][car]["rmse_kmh"]})
    return sorted(rows, key=lambda r: (r["season"], r["round"]))


def powertrain_analysis(accel: pd.DataFrame) -> dict[str, Any]:
    """Joint (dP, dCdA) of every team vs the field, per season (event bootstrap)."""
    out: dict[str, Any] = {}
    for season, g in accel.groupby("season"):
        teams = {}
        for team in sorted(g["team"].unique()):
            jd = joint_deficit(g, team)
            if jd is None:
                continue
            sub = jd.draws[:: max(1, len(jd.draws) // 400)]
            teams[team] = {
                "d_power_kw": jd.d_power_kw, "d_power_ci90": list(jd.d_power_ci90),
                "d_cda_m2": jd.d_cda_m2, "d_cda_ci90": list(jd.d_cda_ci90),
                "correlation": jd.correlation, "matched_kw": jd.matched_kw, "matched_ci90": list(jd.matched_ci90),
                "n_events": jd.n_events, "draws": sub.tolist(),
                "per_event": jd.per_event.to_dict("records"),
            }
        out[str(season)] = _r(teams, 4)
    return out


def grip_matched_params(pole: VehicleParams, r_low: float, r_high: float, q_low: float, q_high: float) -> tuple[VehicleParams, bool]:
    """Scale (mu, ClA) of the pole car so its grip at q_low and q_high changes by r_low, r_high.

    Lap-sim grip is mu (g + q ClA / m). Two reference points give two equations:
      mu' (g + q_l c') = r_l mu (g + q_l c),   mu' (g + q_h c') = r_h mu (g + q_h c),  c = ClA/m
    whose solution is c' = g (R - 1) / (q_h - R q_l) with R = (r_h / r_l)(g + q_h c)/(g + q_l c).
    Returns (params, clamped): `clamped` is True when the solution needed a negative ClA and
    was limited to zero, in which case the high-q ratio is not reproduced.
    """
    from dataclasses import replace

    from amr_aerotwin.domain import GRAVITY_ACCEL as G

    c = pole.cla_m2 / pole.mass_kg
    big_r = (r_high / r_low) * (G + q_high * c) / (G + q_low * c)
    c_new = G * (big_r - 1) / (q_high - big_r * q_low)
    clamped = bool(c_new < 0)
    c_new = max(c_new, 0.0)
    mu_new = r_low * pole.mu * (G + q_low * c) / (G + q_low * c_new)
    return replace(pole, mu=float(mu_new), cla_m2=float(c_new * pole.mass_kg)), clamped


def _posterior_draws(ls: dict[str, Any], n: int, rng: np.random.Generator) -> list[dict[str, float]]:
    """Parameter draws from a lap-sim calibration's log-normal Laplace posterior."""
    names = ls["param_names"]
    med = np.log([ls["params"][k]["median"] for k in names])
    sd = np.array([(np.log(ls["params"][k]["hi"]) - np.log(ls["params"][k]["lo"])) / (2 * 1.6448536) for k in names])
    corr = np.asarray(ls["correlation"], float)
    cov = corr * np.outer(sd, sd) + 1e-12 * np.eye(len(names))
    draws = np.exp(rng.multivariate_normal(med, cov, size=n))
    return [dict(zip(names, d)) for d in draws]


def _ratio_se(a: float, a_lo: float, a_hi: float, b: float, b_lo: float, b_hi: float) -> float:
    """Approximate SE of a/b from two 90% intervals (delta method on log scale)."""
    sa, sb = (a_hi - a_lo) / (2 * 1.6448536 * a), (b_hi - b_lo) / (2 * 1.6448536 * b)
    return float((a / b) * np.sqrt(sa**2 + sb**2))


def _straight_peaks_kmh(speed_ms: np.ndarray, kappa: np.ndarray, step_m: float, min_len_m: float = 350.0,
                        windows: list | None = None) -> float:
    """Mean peak speed over the lap's straights. With `windows` (the same index windows used to
    measure the teams' top-speed gap), peaks are taken there; otherwise over runs with
    |curvature| < 1/1000 m of at least min_len_m."""
    if windows:
        return float(np.mean([np.max(speed_ms[lo:hi + 1]) for lo, hi in windows]) * 3.6)
    straight = np.abs(kappa) < 1e-3
    peaks, run = [], []
    for i, flag in enumerate(np.append(straight, False)):
        if flag:
            run.append(i)
        elif run:
            if len(run) * step_m >= min_len_m:
                peaks.append(float(np.max(speed_ms[run])))
            run = []
    return float(np.mean(peaks) * 3.6) if peaks else float("nan")


def _with_drag(pv: VehicleParams, d_cda: float) -> VehicleParams:
    from dataclasses import replace

    return replace(pv, cda_m2=max(pv.cda_m2 + d_cda, 0.2),
                   low_drag_cda_m2=None if pv.low_drag_cda_m2 is None else max(pv.low_drag_cda_m2 + d_cda, 0.2))


def match_drag_to_top_speed(base: VehicleParams, s_grid: np.ndarray, kappa: np.ndarray, mask: np.ndarray | None,
                            length: float, dv_kmh: float, lo: float = -0.8, hi: float = 2.5,
                            windows: list | None = None) -> float:
    """Effective drag-area change (m^2) that moves the simulated straight-line peak speed by dv_kmh.

    Peak speed falls monotonically with drag, so bisection converges; the result is clipped
    to [lo, hi] when the requested change is outside what that range can produce.
    """
    step = float(s_grid[1] - s_grid[0])
    v0 = _straight_peaks_kmh(simulate_lap(s_grid, kappa, base, mask, length).speed_ms, kappa, step, windows=windows)
    for _ in range(20):
        mid = 0.5 * (lo + hi)
        dv = _straight_peaks_kmh(simulate_lap(s_grid, kappa, _with_drag(base, mid), mask, length).speed_ms, kappa, step,
                                 windows=windows) - v0
        lo, hi = (mid, hi) if dv > dv_kmh else (lo, mid)
    return 0.5 * (lo + hi)


def deficit_decomposition(events: dict[str, dict], teams: pd.DataFrame,
                          target: str = TARGET_TEAM, n_draws: int = 80, seed: int = 9) -> list[dict[str, Any]]:
    """Account for the target team's qualifying gap to pole at each event with the lap sim.

    The pole car's calibrated simulator is modified by
    (a) the target team's measured grip ratio to the pole team at low and high dynamic
        pressure (two equations for mu and ClA), and
    (b) one effective drag change chosen so the simulated peak speed on the straights moves by
        the *measured* top-speed gap between the two teams. Power and drag are not separately
        identifiable from public data (see modeling/powertrain.py), so a single effective
        parameter matched to an observable is used instead of a two-parameter fit.
    This is an accounting of the gap in physical terms, not an out-of-sample prediction: the
    inputs come from the same laps. Uncertainty propagates the pole car's parameter
    posterior and the grip-ratio intervals.
    """

    rng = np.random.default_rng(seed)
    rows = []
    for e in events.values():
        pole_drv = e["pole"]["driver"]
        if not e.get("geometry_ok") or pole_drv not in e.get("lapsim", {}) or "sandbox" not in e:
            continue
        pole_team = e["pole"]["team"]
        if pole_team == target:
            continue
        t = teams[(teams["season"] == e["season"]) & (teams["round"] == e["round"])].set_index("team")
        if target not in t.index or pole_team not in t.index:
            continue
        a, p = t.loc[target], t.loc[pole_team]
        dv_meas = float(a.straight_speed_delta_kmh - p.straight_speed_delta_kmh)
        if not np.all(np.isfinite([a.grip_low_g, a.grip_high_g, p.grip_low_g, p.grip_high_g, dv_meas])):
            continue
        sb = e["sandbox"]
        ls = e["lapsim"][pole_drv]
        pp = {k: v["median"] for k, v in ls["params"].items()}

        def car(par: dict[str, float]) -> VehicleParams:
            return VehicleParams(
                mass_kg=sb["params"]["mass_kg"], rho_kg_m3=sb["params"]["rho_kg_m3"], crr=sb["params"]["crr"],
                mu=par["mu"], cla_m2=par["cla_m2"], cda_m2=par["cda_m2"], power_w=par["power_w"],
                long_grip_scale=par["long_grip_scale"], low_drag_cda_m2=par.get("low_drag_cda_m2"),
            )

        s_grid = np.asarray(sb["distance_m"])
        kappa = np.asarray(sb["curvature"])
        mask = np.asarray(sb["low_drag_mask"], bool) if sb.get("low_drag_mask") is not None else None
        length = sb["lap_length_m"]
        q_l, q_h = e["track"]["q_low_pa"], e["track"]["q_high_pa"]

        drag = _with_drag

        def sim(pv: VehicleParams):
            return simulate_lap(s_grid, kappa, pv, mask, length)

        base = car(pp)
        windows = sb.get("straight_windows") or None
        d_cda = match_drag_to_top_speed(base, s_grid, kappa, mask, length, dv_meas, windows=windows)

        def components(b: VehicleParams, r_l: float, r_h: float) -> tuple[float, float, float, bool]:
            t0 = sim(b).lap_time_s
            gp, clamped = grip_matched_params(b, r_l, r_h, q_l, q_h)
            return (sim(gp).lap_time_s - t0, sim(drag(b, d_cda)).lap_time_s - t0,
                    sim(drag(gp, d_cda)).lap_time_s - t0, clamped)

        r_low, r_high = a.grip_low_g / p.grip_low_g, a.grip_high_g / p.grip_high_g
        grip_s, str_s, both, clamped = components(base, r_low, r_high)
        se_l = _ratio_se(a.grip_low_g, a.grip_low_lo, a.grip_low_hi, p.grip_low_g, p.grip_low_lo, p.grip_low_hi)
        se_h = _ratio_se(a.grip_high_g, a.grip_high_lo, a.grip_high_hi, p.grip_high_g, p.grip_high_lo, p.grip_high_hi)
        post = _posterior_draws(ls, n_draws, rng)
        sims = np.array([components(car(post[i]), max(rng.normal(r_low, se_l), 0.5), max(rng.normal(r_high, se_h), 0.5))[:3]
                         for i in range(n_draws)])
        rows.append({
            "season": e["season"], "round": e["round"], "event": e["event"], "pole_team": pole_team,
            "actual_gap_s": float(a.lap_time_s - p.lap_time_s),
            "predicted_gap_s": both, "grip_s": grip_s, "straight_s": str_s,
            "predicted_ci90": [float(np.percentile(sims[:, 2], 5)), float(np.percentile(sims[:, 2], 95))],
            "straight_ci90": [float(np.percentile(sims[:, 1], 5)), float(np.percentile(sims[:, 1], 95))],
            "grip_ci90": [float(np.percentile(sims[:, 0], 5)), float(np.percentile(sims[:, 0], 95))],
            "straight_draws": sims[:, 1].tolist(), "predicted_draws": sims[:, 2].tolist(),
            "measured_top_speed_gap_kmh": dv_meas, "effective_d_cda_m2": d_cda,
            "grip_low_ratio": r_low, "grip_high_ratio": r_high, "grip_clamped": clamped,
        })
    return sorted(rows, key=lambda r: (r["season"], r["round"]))


def decomposition_summary(rows: list[dict[str, Any]], n_boot: int = 4000, seed: int = 3) -> dict[str, Any]:
    """Season-level agreement between the physics accounting and the actual gaps."""
    from scipy import stats as st

    out = {}
    df = pd.DataFrame(rows)
    rng = np.random.default_rng(seed)
    for season, g in df.groupby("season"):
        act, pred = g["actual_gap_s"].to_numpy(), g["predicted_gap_s"].to_numpy()
        n = len(g)
        idx = rng.integers(0, n, size=(n_boot, n))
        sd = np.array(g["straight_draws"].tolist())  # events x draws
        pdraw = np.array(g["predicted_draws"].tolist())
        # Resample events and, within each, one draw of the simulation's inputs (pole-car
        # posterior and grip-ratio uncertainty): between-event spread plus each event's own
        pick = rng.integers(0, sd.shape[1], size=(n_boot, n))
        straight_mean_draws = sd[idx, pick].mean(axis=1)
        ratio_boot = pdraw[idx, pick].sum(1) / act[idx].sum(1)
        r = float(np.corrcoef(pred, act)[0, 1]) if n > 2 else float("nan")
        zr, se = np.arctanh(np.clip(r, -0.999, 0.999)), 1 / np.sqrt(max(n - 3, 1))
        out[str(season)] = {
            "n_events": n,
            "mean_actual_s": float(act.mean()), "mean_predicted_s": float(pred.mean()),
            "ratio_of_means": float(pred.sum() / act.sum()),
            "ratio_ci90": list(boot_ci(ratio_boot, n)),
            "ratio_draws_mean": float(np.mean(ratio_boot)),
            "r2_event_level": float(1 - np.sum((act - pred) ** 2) / np.sum((act - act.mean()) ** 2)),
            "mae_s": float(np.mean(np.abs(act - pred))),
            "correlation": r,
            "correlation_ci90": [float(np.tanh(zr - 1.6448536 * se)), float(np.tanh(zr + 1.6448536 * se))],
            "mean_grip_s": float(g["grip_s"].mean()),
            "mean_straight_s": float(g["straight_s"].mean()),
            "straight_ci90": list(boot_ci(straight_mean_draws, n)),
            "spearman": float(st.spearmanr(pred, act).statistic) if n > 2 else float("nan"),
        }
    return out


def upgrade_component_shift(teams: pd.DataFrame, accel: pd.DataFrame, season: int, event: str,
                            target: str = TARGET_TEAM) -> dict[str, Any] | None:
    """What an upgrade changed: cornering grip vs straight-line performance, before vs after.

    Grip is relative to the median of the *other* teams at each event. The uncertainty of a
    period mean is the between-event standard error, and the shift is reported with its
    z-score and event counts, so small samples are visible as such.
    """
    t = teams[teams["season"] == season].copy()
    ev = t[t["event"] == event]
    if ev.empty:
        return None
    r0 = int(ev["round"].iloc[0])

    def rel(col: str) -> pd.DataFrame:
        rows = []
        for rnd, g in t.groupby("round"):
            a, o = g[g["team"] == target], g[g["team"] != target][col].dropna()
            if a.empty or not np.isfinite(a[col].iloc[0]) or len(o) < 4:
                continue
            m = float(o.median())
            lo, hi = a[col.replace("_g", "_lo")].iloc[0], a[col.replace("_g", "_hi")].iloc[0]
            rows.append({"round": int(rnd), "ratio": float(a[col].iloc[0] / m), "se": float((hi - lo) / (2 * 1.6448536) / m)})
        return pd.DataFrame(rows)

    def period(df: pd.DataFrame, after: bool) -> dict[str, float]:
        d = df[(df["round"] >= r0) if after else (df["round"] < r0)]
        n = len(d)
        if n == 0:
            return {"mean": float("nan"), "se": float("nan"), "n": 0}
        # Between-event spread already contains each event's measurement error; with a single
        # event, fall back on that event's own fit uncertainty.
        se = float(d["ratio"].std(ddof=1) / np.sqrt(n)) if n > 1 else float(d["se"].iloc[0])
        return {"mean": float(d["ratio"].mean()), "se": se, "n": n}

    out: dict[str, Any] = {"season": season, "event": event, "round": r0}
    for col, key in (("grip_high_g", "grip_high_rel"), ("grip_low_g", "grip_low_rel")):
        df = rel(col)
        b_, a_ = period(df, False), period(df, True)
        shift = a_["mean"] - b_["mean"]
        se = float(np.hypot(a_["se"], b_["se"]))
        out[key] = {"before": b_, "after": a_, "shift": shift, "shift_se": se,
                    "z": float(shift / se) if se > 0 else float("nan"),
                    "per_event": df.to_dict("records")}
    sp = t[t["team"] == target]
    for label, sel in (("before", sp["round"] < r0), ("after", sp["round"] >= r0)):
        v = sp[sel]["straight_speed_delta_kmh"].dropna()
        out.setdefault("straight_speed_delta_kmh", {})[label] = {"mean": float(v.mean()) if len(v) else float("nan"), "n": int(len(v))}
    return out


SIM_PARAM_KEYS = ("mu", "cla_m2", "cda_m2", "power_w", "long_grip_scale", "low_drag_cda_m2")


def geometry_sim_speeds(events: dict[str, dict], window_m: float = 60.0,
                        train_keys: set[str] | None = None) -> pd.DataFrame:
    """Minimum corner speed from the lap sim on each event's geometry with a nominal car.

    The nominal car for event e is the median of the pole-lap calibrations of the *other*
    events of the same season (restricted to `train_keys` inside cross-validation), so no
    information from event e's speeds is used. Air density and mass are event conditions.
    """
    cal = {}
    for k, e in events.items():
        pole = e["pole"]["driver"]
        if e.get("geometry_ok") and pole in e.get("lapsim", {}) and "sandbox" in e:
            cal[k] = {n: v["median"] for n, v in e["lapsim"][pole]["params"].items()}
    rows = []
    for k, e in events.items():
        if k not in cal:
            continue
        others = [c for kk, c in cal.items() if kk != k and events[kk]["season"] == e["season"]
                  and (train_keys is None or f"{events[kk]['season']}-{events[kk]['event']}" in train_keys)]
        if len(others) < 3:
            continue
        sb = e["sandbox"]
        nominal = {n: float(np.median([o[n] for o in others if o.get(n) is not None]))
                   for n in SIM_PARAM_KEYS if any(o.get(n) is not None for o in others)}
        has_low_drag = sb.get("low_drag_mask") is not None and "low_drag_cda_m2" in nominal
        p = VehicleParams(mass_kg=sb["params"]["mass_kg"], rho_kg_m3=sb["params"]["rho_kg_m3"], crr=sb["params"]["crr"],
                          mu=nominal["mu"], cla_m2=nominal["cla_m2"], cda_m2=nominal["cda_m2"], power_w=nominal["power_w"],
                          long_grip_scale=nominal["long_grip_scale"],
                          low_drag_cda_m2=nominal.get("low_drag_cda_m2") if has_low_drag else None)
        s_grid = np.asarray(sb["distance_m"])
        mask = np.asarray(sb["low_drag_mask"], bool) if has_low_drag else None
        v = simulate_lap(s_grid, np.asarray(sb["curvature"]), p, mask, sb["lap_length_m"]).speed_ms * 3.6
        length = sb["lap_length_m"]
        for c_s, label in zip(e["corners"]["distance_m"], e["corners"]["label"]):
            d = (s_grid - c_s + length / 2) % length - length / 2
            rows.append({"event_key": f"{e['season']}-{e['event']}", "corner_key": label,
                         "v_sim_kmh": float(np.min(v[np.abs(d) <= window_m]))})
    return pd.DataFrame(rows)


def section_rate_summary(sec: pd.DataFrame, n_boot: int = 2000, seed: int = 21,
                         target: str = TARGET_TEAM, min_events: int = 5) -> tuple[dict[str, Any], dict[str, Any]]:
    """Per season and team: time lost to pole in each section as a % of the pole lap's time there.

    Rates are ratios of sums over events (seconds lost / seconds spent), so an event where a
    section is short does not get the same weight as one where it is long. The bootstrap
    resamples events. Also reports how each team's straight-line rate compares with its
    corner rate, which separates a uniform deficit from a section-specific one, and the
    target's straight-line rate over the highest of any other team's on the same tracks
    (`straight_vs_field`).
    """
    rng = np.random.default_rng(seed)
    out: dict[str, Any] = {}
    vs_field: dict[str, Any] = {}
    for season, g in sec.groupby("season"):
        teams_out = {}
        st_boot: dict[str, np.ndarray] = {}
        for team, gt in g.groupby("team"):
            piv_l = gt.pivot_table(index="round", columns="section", values="loss_s", aggfunc="sum")
            piv_r = gt.pivot_table(index="round", columns="section", values="reference_time_s", aggfunc="sum")
            if len(piv_l) < 3:
                continue
            cols = list(piv_l.columns)
            L, R = piv_l.to_numpy(), piv_r.reindex(columns=cols).to_numpy()
            idx = rng.integers(0, len(L), size=(n_boot, len(L)))
            rate = 100 * np.nansum(L, 0) / np.nansum(R, 0)
            boot = 100 * np.nansum(L[idx], 1) / np.nansum(R[idx], 1)
            lap_rate = 100 * np.nansum(L) / np.nansum(R)
            corners = [i for i, c in enumerate(cols) if c != "straights"]
            st_i = cols.index("straights") if "straights" in cols else None
            lo, hi = boot_ci_columns(boot, len(L))
            row = {"sections": cols, "rate_pct": rate.tolist(), "ci_lo": np.asarray(lo).tolist(), "ci_hi": np.asarray(hi).tolist(),
                   "lap_rate_pct": float(lap_rate), "n_events": int(len(L))}
            if st_i is not None and corners:
                corner_rate = 100 * np.nansum(L[:, corners]) / np.nansum(R[:, corners])
                b_corner = 100 * np.nansum(L[idx][:, :, corners], (1, 2)) / np.nansum(R[idx][:, :, corners], (1, 2))
                ratio = boot[:, st_i] / np.where(np.abs(b_corner) > 1e-9, b_corner, np.nan)
                row.update({"corner_rate_pct": float(corner_rate),
                            "straight_to_corner_ratio": float(rate[st_i] / corner_rate) if corner_rate else float("nan"),
                            "straight_to_corner_ci90": list(boot_ci(ratio, len(L)))})
            if st_i is not None and len(L) >= min_events:
                st_boot[team] = boot[:, st_i]
            teams_out[team] = row
        if target in st_boot and len(st_boot) > 1:
            vs_field[str(season)] = straight_vs_field(g, target, [t for t in st_boot if t != target], n_boot, seed, int(season))
        out[str(season)] = _r(teams_out, 4)
    return out, vs_field


def straight_vs_field(sec: pd.DataFrame, target: str, rivals: list[str], n_boot: int = 2000, seed: int = 21,
                      season: int = 0) -> dict[str, Any]:
    """The target's straight-line loss rate over the highest of any rival's, on the same tracks.

    Every team is summed over the events where the target has a passing lap, so the track mix
    is the same for all, and the bootstrap resamples those events once for every team (paired).
    The maximum over rivals is taken inside each draw, so the interval covers "than any other
    team". A rival with no passing lap at an event has no row there and drops out of that
    event's sums. The draws come from their own random stream, so adding this comparison does
    not move any other interval.
    """
    st = sec[sec["section"] == "straights"]
    piv_l = st.pivot_table(index="round", columns="team", values="loss_s", aggfunc="sum")
    piv_r = st.pivot_table(index="round", columns="team", values="reference_time_s", aggfunc="sum")
    rounds = piv_l.index[piv_l[target].notna()]
    teams = [target] + list(rivals)
    L = piv_l.reindex(index=rounds, columns=teams).to_numpy()
    R = np.where(np.isnan(L), np.nan, piv_r.reindex(index=rounds, columns=teams).to_numpy())
    point = 100 * np.nansum(L, 0) / np.nansum(R, 0)
    idx = np.random.default_rng([seed, season]).integers(0, len(rounds), size=(n_boot, len(rounds)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = 100 * np.nansum(L[idx], 1) / np.nansum(R[idx], 1)
    best = np.nanmax(boot[:, 1:], axis=1)
    ratio_b = boot[:, 0] / np.where(best > 1e-9, best, np.nan)
    j = int(np.nanargmax(point[1:]))
    return _r({
        "next_team": teams[1 + j], "next_rate_pct": float(point[1 + j]), "target_rate_pct": float(point[0]),
        "ratio": float(point[0] / point[1 + j]) if point[1 + j] > 0 else float("nan"),
        "ratio_ci90": list(boot_ci(ratio_b, len(rounds))),
        "p_ratio_above_2": float(np.nanmean(ratio_b > 2)),
        "n_rivals": len(rivals), "n_events": int(len(rounds)),
    }, 4)


def analyse(out_dir: Path = PROCESSED_DIR, upgrades_csv: Path = UPGRADES_CSV) -> dict[str, Any]:
    tables = load_tables(out_dir)
    events = {p.stem: json.loads(p.read_text()) for p in sorted((out_dir / "events").glob("*.json"))}
    # Wet qualifying (most laps on intermediates or wets) says little about the dry car: such
    # events are left out of everything built on qualifying; their dry races still count
    wet = {k: e for k, e in events.items() if e.get("wet_session")}
    wet_keys = {(e["season"], e["round"]) for e in wet.values()}
    events = {k: e for k, e in events.items() if k not in wet}
    for name, t in tables.items():
        if name != "race_pace" and not t.empty and {"season", "round"} <= set(t.columns):
            tables[name] = t[[(sr, rd) not in wet_keys for sr, rd in zip(t["season"], t["round"])]]
    drivers = tables["drivers"]
    drivers = drivers[drivers["passed_checks"].astype(bool)]
    result: dict[str, Any] = {"n_events": len(events),
                              "wet_events_excluded": [f"{e['event']} {e['season']}" for e in wet.values()]}
    # Events where the telemetry reference (fastest lap that passes every check) is not the
    # fastest lap of qualifying, because that lap's data failed a check
    result["reference_not_fastest"] = [
        {"season": e["season"], "event": e["event"], "reference": e["pole"]["driver"], "fastest": e["fastest_lap"]["driver"],
         "gap_s": _r(e["pole"]["lap_time_s"] - e["fastest_lap"]["lap_time_s"], 3)}
        for e in sorted(events.values(), key=lambda e: (e["season"], e["round"]))
        if e.get("fastest_lap") and e["pole"]["driver"] != e["fastest_lap"]["driver"]]

    # Supertimes and AMR changepoints
    # Pace analyses use official timing for every driver, not only laps with usable telemetry
    timing = tables["timing"] if not tables["timing"].empty else drivers
    # FIA 107% rule: slower laps (crash, red flag, a wet session segment) are not pace
    best_all = timing.groupby(["season", "round"])["lap_time_s"].transform("min")
    result["laps_outside_107pct"] = int((timing["lap_time_s"] > 1.07 * best_all).sum())
    timing = timing[timing["lap_time_s"] <= 1.07 * best_all]
    st = supertime_table(timing)
    result["supertimes"] = _r(st.to_dict("records"), 3)
    teams = tables["teams"]
    # Track character (share of the pole lap in fast corners) is an event property
    event_track_x = teams.groupby(["season", "round"], as_index=False)["track_x"].first()
    cps = {}
    for season, g in st[st["team"] == TARGET_TEAM].groupby("season"):
        g = g.sort_values("round")
        x = event_track_x[event_track_x["season"] == season].set_index("round")["track_x"].reindex(g["round"])
        xv = x.fillna(x.mean()).to_numpy()
        yv = g["gap_pct"].to_numpy()
        cp = bayesian_changepoint(yv, xv, list(g["event"]), g["round"].to_numpy())
        sens = {str(gg): float(bayesian_changepoint(yv, xv, g=gg).p_no_change) for gg in (1.0, 10.0, 100.0)}
        # Sensitivity to both prior choices: the coefficient prior scale g and P(no change)
        grid = []
        for gg in (1.0, 10.0, 100.0):
            for p0 in (0.25, 0.5, 0.75):
                c2 = bayesian_changepoint(yv, xv, list(g["event"]), g=gg, prior_no_change=p0)
                grid.append({"g": gg, "prior_no_change": p0, "p_no_change": c2.p_no_change,
                             "map_event": c2.events[c2.map_index] if c2.map_index is not None else None,
                             "map_probability": c2.map_probability})
        count = changepoint_count_evidence(yv, xv)
        pair = count.get("map_pair_index")
        cps[str(season)] = {
            "map_probability": _r(cp.map_probability, 4), "p_no_change_by_prior_g": _r(sens, 4),
            "prior_sensitivity": _r(grid, 4),
            "rounds": _r(cp.rounds), "events": cp.events, "gap_pct": _r(yv, 3),
            "posterior_tau": _r(cp.posterior_tau, 4), "p_no_change": _r(cp.p_no_change, 4),
            "map_event": cp.events[cp.map_index] if cp.map_index is not None else None,
            "effect_pct": _r(cp.effect_mean_pct, 3), "effect_ci90_pct": _r(cp.effect_ci90_pct, 3),
            "effect_avg_pct": _r(cp.effect_avg_pct, 3), "effect_avg_ci90_pct": _r(cp.effect_avg_ci90_pct, 3),
            "bf_two_vs_one": _r(count["bf_two_vs_one"], 3), "bf_one_vs_none": _r(count["bf_one_vs_none"], 3),
            "two_change_events": [cp.events[i] for i in pair] if isinstance(pair, list) else None,  # type: ignore[union-attr]
            "two_change_steps_pct": _r(count.get("map_pair_steps"), 3),
            "two_change_pair_probability": _r(count.get("map_pair_probability"), 4),
        }
    result["changepoints"] = cps

    # Car vs driver
    result["variance_split"] = {}
    for season, g in timing.groupby("season"):
        vs = car_vs_driver_variance(g[["season", "round", "team", "driver", "lap_time_s"]])
        result["variance_split"][str(season)] = _r(vs.__dict__, 4)
    best_t = timing.groupby(["season", "round"])["lap_time_s"].transform("min")
    amr = timing.assign(gap_pct=(timing["lap_time_s"] / best_t - 1) * 100)
    amr = amr[amr["team"] == TARGET_TEAM]
    h2h = amr.pivot_table(index=["season", "round"], columns="driver", values="gap_pct")
    result["amr_teammates"] = {str(s): _r({c: float(g[c].mean()) for c in g.columns if g[c].notna().sum() > 2}, 3)
                               for s, g in h2h.groupby(level=0)}

    # Upgrades (DiD with placebo inference)
    if upgrades_csv.exists():
        ups = pd.read_csv(upgrades_csv)
        major = ups[ups["major_performance_upgrade"].isin(["major", "partial"])]
        panel = st.merge(event_track_x, on=["season", "round"], how="left")
        effects = upgrade_effects(panel, major[["season", "grand_prix"]].rename(columns={"grand_prix": "event"}), TARGET_TEAM)
        def holm(ps: list[float]) -> np.ndarray:
            # Holm step-down adjustment across the declared upgrades tested
            order, adj, running = np.argsort(ps), np.zeros(len(ps)), 0.0
            for rank, i in enumerate(order):
                running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
                adj[i] = running
            return adj

        holm_team, holm_lead = holm([e.team_placebo_p for e in effects]), holm([e.lead_p for e in effects])
        lead_floor = [1.0 / (1 + (e.n_time_placebos if e.lead_test == "time" else e.n_team_placebos)) for e in effects]
        result["upgrades"] = {
            "declared": _r(ups.to_dict("records")),
            "effects": [_r({**e.__dict__, "team_placebo_p_holm": float(holm_team[i]), "lead_p_holm": float(holm_lead[i])}, 4)
                        for i, e in enumerate(effects)],
            # Smallest Holm-adjusted p any of these tests could reach (number of tests x p floor):
            # above 0.10 means no single upgrade can be declared significant after adjustment
            "holm_floor_team": _r(len(effects) * min(e.p_floor for e in effects), 4) if effects else None,
            "holm_floor_lead": _r(len(effects) * min(lead_floor), 4) if effects else None,
        }

    # Corner model, team deficits, wind, Shapley
    corners = tables["corners"]
    corners = corners[corners["geometry_ok"].astype(bool) & corners["team"].notna()]
    if "speed_ok" in corners:  # minimum speeds the GPS cross-check rejects (stuck speed channel)
        corners = corners[corners["speed_ok"].fillna(True).astype(bool)]
    corners = corners.merge(drivers[["season", "round", "driver"]], on=["season", "round", "driver"])
    corners["circuit"] = corners["circuit_corner"].str.rsplit("-", n=1).str[0]
    sims = geometry_sim_speeds(events)
    if not sims.empty:
        corners = corners.merge(sims, on=["event_key", "corner_key"], how="left")
        # Corner class from geometry (simulated nominal car), not from an observed lap
        geo_cls = corners["v_sim_kmh"].map(lambda v: corner_speed_class(v) if np.isfinite(v) else None)
        corners["speed_class"] = geo_cls.fillna(corners["speed_class"])
    rep = cross_validate(corners, group_col="circuit", sim_fn=lambda keys: geometry_sim_speeds(events, train_keys=keys))
    cov_ev = np.array(list(rep.coverage_by_event.values()))
    result["corner_model"] = {
        "metrics": _r(rep.metrics.to_dict("records"), 3),
        "conformal_coverage": _r(rep.conformal_coverage, 3), "conformal_target": 0.9,
        "conformal_halfwidth_kmh": _r(rep.conformal_halfwidth_kmh, 2),
        "coverage_by_class": _r(rep.coverage_by_class, 3),
        "coverage_by_event": {"min": _r(float(cov_ev.min()), 3), "p10": _r(float(np.percentile(cov_ev, 10)), 3),
                              "median": _r(float(np.median(cov_ev)), 3), "share_below_80pct": _r(float(np.mean(cov_ev < 0.8)), 3)},
        "n_circuits": int(corners["circuit"].nunique()), "cv_groups": "circuit",
        "physics_params": {"a_mu_g": _r(rep.physics_params[0], 3), "b": _r(rep.physics_params[1], 6)},
        "n_rows": len(corners), "n_events": int(corners["event_key"].nunique()),
        "n_corners": int(corners[["event_key", "corner_key"]].drop_duplicates().shape[0]),
        "share_with_sim": _r(float(corners["v_sim_kmh"].notna().mean()) if "v_sim_kmh" in corners else 0.0, 3),
        "scatter": _r(rep.oof.sample(min(3000, len(rep.oof)), random_state=0)[
            ["v_min_kmh", "pred_steady", "pred_physics", "pred_ml", "pred_hybrid", "speed_class", "team", "season"]].to_dict("list"), 1),
    }
    deficit_by_season = []
    for s, g in rep.oof.groupby("season"):
        dd = team_corner_deficit(g)
        dd["season"] = s
        deficit_by_season.append(dd)
    result["team_corner_deficit"] = {str(s): _r(d.drop(columns="season").to_dict("records"), 3)
                                     for s, d in pd.concat(deficit_by_season).groupby("season")}
    cr = corners.reset_index(drop=True)
    amr_rows = np.flatnonzero((cr["team"] == TARGET_TEAM).to_numpy())
    phi, names = hybrid_shapley(cr, amr_rows)
    phi["speed_class"] = cr.loc[cr["v_sim_kmh"].notna()].reset_index(drop=True).loc[phi.index, "speed_class"].to_numpy()
    result["shapley"] = {
        "features": names,
        "mean_abs": _r({n: float(phi[n].abs().mean()) for n in names}, 3),
        "mean_by_class": _r(phi.groupby("speed_class")[names].mean().to_dict("index"), 3),
        "n_rows": len(phi),
    }

    # Where the target team's qualifying gap to pole goes, by corner class (model-free)
    gb = []
    for e in events.values():
        c = e.get("comparison")
        if not c:
            continue
        for r in c["class_summary"]:
            gb.append({"season": e["season"], "round": e["round"], "event": e["event"],
                       "class": r["speed_class"], "time_s": r["time_s"], "total_s": c["total_delta_s"]})
    gbd = pd.DataFrame(gb)
    result["gap_by_class"] = {}
    if not gbd.empty:
        rng_g = np.random.default_rng(12)
        for season, g in gbd.groupby("season"):
            piv = g.pivot_table(index="round", columns="class", values="time_s")
            arr = piv.to_numpy()
            boots = np.nanmean(arr[rng_g.integers(0, len(arr), size=(2000, len(arr)))], axis=1)
            g_lo, g_hi = boot_ci_columns(boots, len(arr))
            result["gap_by_class"][str(season)] = _r({
                "classes": list(piv.columns), "mean_s": np.nanmean(arr, axis=0).tolist(),
                "ci_lo": np.asarray(g_lo).tolist(), "ci_hi": np.asarray(g_hi).tolist(),
                "mean_total_s": float(g.groupby("round")["total_s"].first().mean()), "n_events": int(len(piv)),
                "per_event": g[["round", "event", "class", "time_s"]].to_dict("records"),
            }, 4)

    # Loss rate to pole by section for every team (normalised by the pole lap's time there)
    sec = tables.get("sections", pd.DataFrame())
    result["section_rates"], result["straight_vs_field"] = {}, {}
    if not sec.empty:
        result["section_rates"], result["straight_vs_field"] = section_rate_summary(sec)

    # Where along the straights each team gains or loses speed (model-free, position-matched)
    prof = tables.get("profile", pd.DataFrame())
    result["straight_profile"] = {}
    if not prof.empty:
        for season, g in prof.groupby("season"):
            per_team = {}
            for team in sorted(g["team"].unique()):
                sp_ = speed_gap_profile(g, team)
                if sp_.empty:
                    continue
                per_team[team] = {"bins": sp_.to_dict("records"), **{k: (list(v) if isinstance(v, tuple) else v) for k, v in sp_.attrs.items()}}
            result["straight_profile"][str(season)] = _r(per_team, 3)
    result["target_relative"] = {
        str(s_): {c: _r(relative_metric(g, TARGET_TEAM, c), 4) for c in
                  ("clip_time_loss_s", "clip_speed_drop_kmh", "clip_decel_distance_m", "straight_speed_delta_kmh", "gap_pct")}
        for s_, g in teams.groupby("season")
    }

    # Straight-line power/drag, and the physics accounting of the target team's gap to pole
    result["powertrain"] = powertrain_analysis(tables["accel"])
    decomp = deficit_decomposition(events, teams)
    result["deficit_summary"] = _r(decomposition_summary(decomp), 4) if decomp else {}
    result["deficit_decomposition"] = _r([{k: v for k, v in r.items() if not k.endswith("_draws")} for r in decomp], 4)
    if upgrades_csv.exists():
        majors = pd.read_csv(upgrades_csv)
        majors = majors[majors["major_performance_upgrade"] == "major"]
        result["upgrade_components"] = [
            _r(x, 4) for x in (upgrade_component_shift(teams, tables["accel"], int(r.season), r.grand_prix)
                               for r in majors.itertuples()) if x is not None
        ]

    tt = teams.copy()
    tt["grip_high_rel"] = rel_to_other_teams(tt, "grip_high_g")
    tt["grip_low_rel"] = rel_to_other_teams(tt, "grip_low_g")
    result["amr_component_series"] = {
        str(s_): _r(g.sort_values("round")[["round", "event", "gap_pct", "grip_high_rel", "grip_low_rel",
                                             "straight_speed_delta_kmh", "clip_time_loss_s"]].to_dict("records"), 4)
        for s_, g in tt[tt["team"] == TARGET_TEAM].groupby("season")
    }

    # Aero map, sensitivities, energy, race pace
    result["aero_map"] = aero_map(teams, events)
    result["circuit_sensitivities"] = _r(circuit_sensitivities(events), 4)
    result["calibration_accuracy"] = _r(sorted(
        [{"season": e["season"], "round": e["round"], "event": e["event"], "driver": d, "team": ls["team"],
          "is_pole": d == e["pole"]["driver"], "rmse_kmh": ls["rmse_kmh"], "lap_time_error_s": ls["lap_time_error_s"],
          "posterior_lap_time_sd_s": ls["posterior_lap_time_sd_s"]}
         for e in events.values() for d, ls in e.get("lapsim", {}).items()],
        key=lambda r: (r["season"], r["round"])), 4)
    energy = teams.groupby(["season", "team"])[["clip_speed_drop_kmh", "clip_decel_distance_m", "clip_power_deficit_kw", "clip_time_loss_s"]].mean().reset_index()
    result["energy"] = _r(energy.to_dict("records"), 3)
    result["energy_by_event"] = _r(teams[["season", "round", "event", "team", "clip_speed_drop_kmh", "clip_time_loss_s"]].to_dict("records"), 3)
    rp = tables["race_pace"]
    if not rp.empty:
        result["race_pace"] = _r(rp.groupby(["season", "team"])["gap_s"].agg(["mean", "median", "count"]).reset_index().to_dict("records"), 3)
        result["race_pace_by_event"] = _r(rp[["season", "round", "event", "team", "gap_s", "ci_lo", "ci_hi"]].to_dict("records"), 3)

    # Wind frame check across windy sessions
    wt = [e["wind_rotation_test"] for e in events.values() if e.get("wind_rotation_test")]
    if wt:
        angles = sorted(int(a) for a in wt[0]["relative_sse"])
        mean_rel = {a: float(np.mean([w["relative_sse"][str(a)] if str(a) in w["relative_sse"] else w["relative_sse"][a] for w in wt])) for a in angles}
        result["wind_rotation_test"] = _r({
            "n_events": len(wt), "mean_relative_sse": mean_rel,
            "best_rotation_by_event": [w["best_rotation_deg"] for w in wt],
            "share_events_assumed_orientation_best": float(np.mean([w["best_rotation_deg"] == 0 for w in wt])),
            "assumed_orientation_vs_ground": mean_rel.get(0),
        }, 4)

    # Data quality overview
    d_all = tables["drivers"]
    result["data_quality"] = {
        "laps_total": int(len(d_all)), "laps_passed": int(d_all["passed_checks"].sum()),
        "events_geometry_failed": sorted({e["event"] + f" {e['season']}" for e in events.values() if not e["geometry_ok"]}),
        "gps_lag_s_median": _r(float(d_all["q_gps_lag_s"].median()), 3),
        "projection_rms_m_median": _r(float(d_all["q_projection_rms_m"].median()), 2),
    }
    if "q_sector_time_error_s" in d_all:
        # Independent check of the alignment: aligned clock vs official sector times, passing laps
        e = d_all.loc[d_all["passed_checks"].astype(bool), "q_sector_time_error_s"].dropna().abs()
        result["data_quality"].update({
            "sector_time_error_median_s": _r(float(e.median()), 4), "sector_time_error_rms_s": _r(float(np.sqrt((e ** 2).mean())), 4),
            "sector_time_error_p95_s": _r(float(e.quantile(0.95)), 4), "sector_time_error_max_s": _r(float(e.max()), 4),
            "n_laps_sector_checked": int(len(e)),
        })
        ok = d_all[d_all["passed_checks"].astype(bool)]
        gap = ok[["q_start_line_gap_m", "q_finish_line_gap_m"]].abs().max(axis=1)
        if len(gap):
            top = ok.loc[gap.idxmax()]
            result["data_quality"].update({"max_clock_offset_m": _r(float(gap.max()), 1),
                                           "max_clock_offset_lap": f"{top['driver']} at the {top['season']} {top['event']}"})
    skipped_path = out_dir / "skipped.json"
    result["skipped_events"] = json.loads(skipped_path.read_text()) if skipped_path.exists() else []
    (out_dir / "season.json").write_text(json.dumps(_r(result, 6), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return result
