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
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from amr_aerotwin.data.repository import DEFAULT_CACHE_DIR, DataUnavailableError, TelemetryRepository
from amr_aerotwin.domain import TARGET_TEAM
from amr_aerotwin.modeling.corner_model import (
    cross_validate,
    hybrid_shapley,
    team_corner_deficit,
    wind_sensitivity,
)
from amr_aerotwin.modeling.season import (
    bayesian_changepoint,
    car_vs_driver_variance,
    supertime_table,
    upgrade_effects,
)
from amr_aerotwin.modeling.powertrain import acceleration_deficit, power_deficit_summary, power_or_drag_signature
from amr_aerotwin.physics.lapsim import VehicleParams, simulate_lap
from amr_aerotwin.pipeline.event import _r, prefetch_event, safe_process_event

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[4]
PROCESSED_DIR = ROOT / "data" / "processed"
UPGRADES_CSV = ROOT / "data" / "reference" / "amr_upgrades.csv"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def event_calendar(repo: TelemetryRepository, years: list[int]) -> pd.DataFrame:
    """Events that have a qualifying session, ordered by date, with round numbers."""
    rows = []
    for y in years:
        for ev in repo.list_events(y):
            try:
                laps = repo.session_laps(y, ev, "Qualifying")
            except DataUnavailableError:
                continue
            date = laps["lSD"].dropna().min() if "lSD" in laps else None
            if date is None or laps["time"].notna().sum() < 10:
                continue
            rows.append({"season": y, "event": ev, "date": str(date)[:10]})
    cal = pd.DataFrame(rows).sort_values(["season", "date"]).reset_index(drop=True)
    cal["round"] = cal.groupby("season").cumcount() + 1
    return cal


def fetch(years: list[int], cache_dir: Path = DEFAULT_CACHE_DIR, workers: int = 6) -> pd.DataFrame:
    repo = TelemetryRepository(cache_dir, offline=False)
    cal = event_calendar(repo, years)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(prefetch_event, repo, r.season, r.event): r for r in cal.itertuples()}
        for f in as_completed(futs):
            r = futs[f]
            try:
                f.result()
                log.info("fetched %s %s", r.season, r.event)
            except Exception as err:  # noqa: BLE001
                log.warning("fetch failed %s %s: %s", r.season, r.event, err)
    return cal


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
    (out_dir / "events").mkdir(parents=True, exist_ok=True)
    for stale in (out_dir / "events").glob("*.json"):  # never mix outputs of different builds
        stale.unlink()
    jobs = [(str(cache_dir), int(r.season), r.event, int(r.round), run_mcmc) for r in cal.itertuples()]
    outputs = []
    skipped = []
    n_proc = processes or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=n_proc) as pool:
        for job, res in zip(jobs, pool.map(_worker, jobs)):
            if isinstance(res, str):
                log.warning("skipped %s %s: %s", job[1], job[2], res)
                skipped.append({"season": job[1], "event": job[2], "reason": res})
                continue
            outputs.append(res)
            path = out_dir / "events" / f"{job[1]}-{slug(job[2])}.json"
            path.write_text(json.dumps(res.summary, separators=(",", ":")), encoding="utf-8")
            log.info("built %s %s", job[1], job[2])

    tables = {
        "drivers": pd.concat([o.driver_rows for o in outputs], ignore_index=True),
        "teams": pd.concat([o.team_rows for o in outputs], ignore_index=True),
        "corners": pd.concat([o.corner_rows for o in outputs], ignore_index=True),
        "race_pace": pd.concat([o.race_rows for o in outputs if not o.race_rows.empty], ignore_index=True),
        "accel": pd.concat([o.accel_rows for o in outputs if not o.accel_rows.empty], ignore_index=True),
    }
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv.gz", index=False)
    cal.to_csv(out_dir / "calendar.csv", index=False)
    (out_dir / "skipped.json").write_text(json.dumps(skipped, indent=1), encoding="utf-8")
    return tables


def load_tables(out_dir: Path = PROCESSED_DIR) -> dict[str, pd.DataFrame]:
    return {n: pd.read_csv(out_dir / f"{n}.csv.gz") for n in ("drivers", "teams", "corners", "race_pace", "accel")}


# --------------------------------------------------------------------------- analyses
def _bootstrap_mean(values: np.ndarray, n_boot: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = [rng.choice(v, len(v)).mean() for _ in range(n_boot)]
    return float(v.mean()), float(np.percentile(boots, 5)), float(np.percentile(boots, 95))


def aero_map(teams: pd.DataFrame, events: dict[str, dict]) -> dict[str, Any]:
    """Per season: each team's high-speed grip and straight-line speed relative to the field.

    Converted to ClA- and CdA-equivalent % so lap-time sensitivity lines can be overlaid:
      dClA% ~ dGrip_high% / aero_share  (grip_high = mu (g + q ClA / m))
      dCdA% ~ -3 dV%                     (drag-limited speed  v ~ CdA^(-1/3))
    """
    t = teams[teams["geometry_ok"].astype(bool)].copy()
    med = t.groupby(["season", "round"])["grip_high_g"].transform("median")
    share = t.groupby(["season", "round"])["aero_share_high"].transform("median")
    t["d_grip_pct"] = (t["grip_high_g"] / med - 1) * 100
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
    out: dict[str, Any] = {}
    for season, g in accel.groupby("season"):
        teams = {}
        for team in sorted(g["team"].unique()):
            d = acceleration_deficit(g, team)
            if d.empty:
                continue
            high = d[d["band_kmh"] >= 200]  # above the traction-limited range
            summ = power_deficit_summary(g, team)
            teams[team] = {
                "bands": _r(d.to_dict("records"), 3),
                **_r(power_or_drag_signature(d), 3),
                "power_deficit_kw_200plus": _r(summ["mean_kw"], 2),
                "power_deficit_ci90": _r([summ["lo"], summ["hi"]], 2),
                "n_events_200plus": summ["n_events"],
            }
        out[str(season)] = teams
    return out


def grip_matched_params(pole: VehicleParams, r_low: float, r_high: float, q_low: float, q_high: float) -> VehicleParams:
    """Scale (mu, ClA) of the pole car so its grip at q_low and q_high changes by r_low, r_high.

    Lap-sim grip is mu (g + q ClA / m). Two reference points give two equations:
      mu' (g + q_l c') = r_l mu (g + q_l c),   mu' (g + q_h c') = r_h mu (g + q_h c),  c = ClA/m
    whose solution is c' = g (R - 1) / (q_h - R q_l) with R = (r_h / r_l)(g + q_h c)/(g + q_l c).
    """
    from dataclasses import replace

    from amr_aerotwin.domain import GRAVITY_ACCEL as G

    c = pole.cla_m2 / pole.mass_kg
    big_r = (r_high / r_low) * (G + q_high * c) / (G + q_low * c)
    c_new = G * (big_r - 1) / (q_high - big_r * q_low)
    mu_new = r_low * pole.mu * (G + q_low * c) / (G + q_low * c_new)
    return replace(pole, mu=float(mu_new), cla_m2=float(max(c_new, 0.0) * pole.mass_kg))


def deficit_decomposition(events: dict[str, dict], teams: pd.DataFrame, powertrain: dict[str, Any],
                          target: str = TARGET_TEAM) -> list[dict[str, Any]]:
    """Explain the target team's qualifying gap to pole at each event with the calibrated lap sim.

    The pole car's calibrated simulator is modified by (a) the target team's measured grip
    ratio at low and high dynamic pressure and (b) its season power-equivalent deficit
    relative to the pole team. Predicted and actual gaps are then compared.
    """
    from dataclasses import replace

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
        if not np.all(np.isfinite([a.grip_low_g, a.grip_high_g, p.grip_low_g, p.grip_high_g])):
            continue
        sb = e["sandbox"]
        pp = e["lapsim"][pole_drv]["params"]
        base = VehicleParams(
            mass_kg=sb["params"]["mass_kg"], rho_kg_m3=sb["params"]["rho_kg_m3"], crr=sb["params"]["crr"],
            mu=pp["mu"]["median"], cla_m2=pp["cla_m2"]["median"], cda_m2=pp["cda_m2"]["median"],
            power_w=pp["power_w"]["median"], long_grip_scale=pp["long_grip_scale"]["median"],
            low_drag_cda_m2=pp["low_drag_cda_m2"]["median"] if "low_drag_cda_m2" in pp else None,
        )
        s_grid = np.asarray(sb["distance_m"])
        kappa = np.asarray(sb["curvature"])
        mask = np.asarray(sb["low_drag_mask"], bool) if sb.get("low_drag_mask") is not None else None
        length = sb["lap_length_m"]

        def lap(pv: VehicleParams) -> float:
            return simulate_lap(s_grid, kappa, pv, mask, length).lap_time_s

        q_l, q_h = e["track"]["q_low_pa"], e["track"]["q_high_pa"]
        grip_p = grip_matched_params(base, a.grip_low_g / p.grip_low_g, a.grip_high_g / p.grip_high_g, q_l, q_h)
        mech_p = replace(base, mu=base.mu * a.grip_low_g / p.grip_low_g)
        pt = powertrain.get(str(e["season"]), {})
        d_kw = (pt.get(target, {}).get("power_deficit_kw_200plus") or 0.0) - (pt.get(pole_team, {}).get("power_deficit_kw_200plus") or 0.0)
        power_p = replace(base, power_w=base.power_w + d_kw * 1000.0)
        both_p = replace(grip_p, power_w=base.power_w + d_kw * 1000.0)
        t0 = lap(base)
        rows.append({
            "season": e["season"], "round": e["round"], "event": e["event"], "pole_team": pole_team,
            "actual_gap_s": float(a.lap_time_s - p.lap_time_s),
            "predicted_gap_s": lap(both_p) - t0,
            "grip_s": lap(grip_p) - t0,
            "mechanical_grip_s": lap(mech_p) - t0,
            "power_s": lap(power_p) - t0,
            "power_deficit_kw": d_kw,
            "grip_low_ratio": float(a.grip_low_g / p.grip_low_g),
            "grip_high_ratio": float(a.grip_high_g / p.grip_high_g),
        })
    return sorted(rows, key=lambda r: (r["season"], r["round"]))


def upgrade_component_shift(teams: pd.DataFrame, accel: pd.DataFrame, season: int, event: str,
                            target: str = TARGET_TEAM, n_boot: int = 2000, seed: int = 8) -> dict[str, Any] | None:
    """Which part of the car an upgrade changed: cornering grip vs straight-line performance.

    Compares the target team's events before and after `event` on: high- and low-speed grip
    relative to the event's field median, straight-line peak-speed delta, and the
    power-equivalent acceleration deficit. Bootstrap over events within each period.
    """
    t = teams[teams["season"] == season].copy()
    ev = t[t["event"] == event]
    if ev.empty:
        return None
    r0 = int(ev["round"].iloc[0])
    t["grip_high_rel"] = t["grip_high_g"] / t.groupby("round")["grip_high_g"].transform("median")
    t["grip_low_rel"] = t["grip_low_g"] / t.groupby("round")["grip_low_g"].transform("median")
    a = t[t["team"] == target]
    rng = np.random.default_rng(seed)

    def stat(v: pd.Series) -> dict[str, float]:
        v = v.dropna().to_numpy()
        if len(v) < 2:
            return {"mean": float(np.mean(v)) if len(v) else np.nan, "lo": np.nan, "hi": np.nan, "n": int(len(v))}
        boots = [rng.choice(v, len(v)).mean() for _ in range(n_boot)]
        return {"mean": float(v.mean()), "lo": float(np.percentile(boots, 5)), "hi": float(np.percentile(boots, 95)), "n": int(len(v))}

    out: dict[str, Any] = {"season": season, "event": event, "round": r0}
    for label, sel in (("before", a["round"] < r0), ("after", a["round"] >= r0)):
        part = a[sel]
        acc = accel[(accel["season"] == season) & ((accel["round"] < r0) if label == "before" else (accel["round"] >= r0))]
        out[label] = {
            "grip_high_rel": stat(part["grip_high_rel"]), "grip_low_rel": stat(part["grip_low_rel"]),
            "straight_speed_delta_kmh": stat(part["straight_speed_delta_kmh"]), "gap_pct": stat(part["gap_pct"]),
            "power_deficit": power_deficit_summary(acc, target) if not acc.empty else None,
        }
    return out


SIM_PARAM_KEYS = ("mu", "cla_m2", "cda_m2", "power_w", "long_grip_scale", "low_drag_cda_m2")


def geometry_sim_speeds(events: dict[str, dict], window_m: float = 60.0) -> pd.DataFrame:
    """Minimum corner speed from the lap sim on each event's geometry with a nominal car.

    The nominal car for event e is the median of the pole-lap calibrations of the *other*
    events of the same season, so no information from event e's speeds is used. Air
    density and mass are event conditions, not outcomes.
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
        others = [c for kk, c in cal.items() if kk != k and events[kk]["season"] == e["season"]]
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


def analyse(out_dir: Path = PROCESSED_DIR, upgrades_csv: Path = UPGRADES_CSV) -> dict[str, Any]:
    tables = load_tables(out_dir)
    events = {p.stem: json.loads(p.read_text()) for p in sorted((out_dir / "events").glob("*.json"))}
    drivers = tables["drivers"]
    drivers = drivers[drivers["passed_checks"].astype(bool)]
    result: dict[str, Any] = {"n_events": len(events)}

    # Supertimes and AMR changepoints
    st = supertime_table(drivers.rename(columns={"lap_time_s": "lap_time_s"}))
    result["supertimes"] = _r(st.to_dict("records"), 3)
    teams = tables["teams"]
    cps = {}
    for season, g in st[st["team"] == TARGET_TEAM].groupby("season"):
        g = g.sort_values("round")
        x = teams[(teams["season"] == season) & (teams["team"] == TARGET_TEAM)].set_index("round")["track_x"].reindex(g["round"])
        cp = bayesian_changepoint(g["gap_pct"].to_numpy(), x.fillna(x.mean()).to_numpy(), list(g["event"]), g["round"].to_numpy())
        cps[str(season)] = {
            "rounds": _r(cp.rounds), "events": cp.events, "gap_pct": _r(g["gap_pct"].to_numpy(), 3),
            "posterior_tau": _r(cp.posterior_tau, 4), "p_no_change": _r(cp.p_no_change, 4),
            "map_event": cp.events[cp.map_index] if cp.map_index is not None else None,
            "effect_pct": _r(cp.effect_mean_pct, 3), "effect_ci90_pct": _r(cp.effect_ci90_pct, 3),
        }
    result["changepoints"] = cps

    # Car vs driver
    result["variance_split"] = {}
    for season, g in drivers.groupby("season"):
        vs = car_vs_driver_variance(g[["season", "round", "team", "driver", "lap_time_s"]])
        result["variance_split"][str(season)] = _r(vs.__dict__, 4)
    amr = drivers[drivers["team"] == TARGET_TEAM]
    h2h = amr.pivot_table(index=["season", "round"], columns="driver", values="gap_pct")
    result["amr_teammates"] = {str(s): _r({c: float(g[c].mean()) for c in g.columns if g[c].notna().sum() > 2}, 3)
                               for s, g in h2h.groupby(level=0)}

    # Upgrades (DiD with placebo inference)
    if upgrades_csv.exists():
        ups = pd.read_csv(upgrades_csv)
        major = ups[ups["major_performance_upgrade"].isin(["major", "partial"])]
        panel = st.merge(teams[["season", "round", "team", "track_x"]], on=["season", "round", "team"], how="left")
        effects = upgrade_effects(panel, major[["season", "grand_prix"]].rename(columns={"grand_prix": "event"}), TARGET_TEAM)
        result["upgrades"] = {
            "declared": _r(ups.to_dict("records")),
            "effects": [_r({k: v for k, v in e.__dict__.items()}, 4) for e in effects],
        }

    # Corner model, team deficits, wind, Shapley
    corners = tables["corners"]
    corners = corners[corners["geometry_ok"].astype(bool) & corners["team"].notna()]
    corners = corners.merge(drivers[["season", "round", "driver"]], on=["season", "round", "driver"])
    sims = geometry_sim_speeds(events)
    if not sims.empty:
        corners = corners.merge(sims, on=["event_key", "corner_key"], how="left")
    rep = cross_validate(corners)
    result["corner_model"] = {
        "metrics": _r(rep.metrics.to_dict("records"), 3),
        "conformal_coverage": _r(rep.conformal_coverage, 3), "conformal_target": 0.9,
        "conformal_halfwidth_kmh": _r(rep.conformal_halfwidth_kmh, 2),
        "coverage_by_class": _r(rep.coverage_by_class, 3),
        "physics_params": {"a_mu_g": _r(rep.physics_params[0], 3), "b": _r(rep.physics_params[1], 6)},
        "n_rows": len(corners), "n_events": int(corners["event_key"].nunique()),
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
    result["wind_sensitivity"] = _r(wind_sensitivity(corners).to_dict("records"), 4)
    amr_rows = np.flatnonzero((corners["team"] == TARGET_TEAM).to_numpy())
    phi, names = hybrid_shapley(corners.reset_index(drop=True), amr_rows)
    phi["speed_class"] = corners["speed_class"].to_numpy()[amr_rows]
    phi["season"] = corners["season"].to_numpy()[amr_rows]
    result["shapley"] = {
        "features": names,
        "mean_abs": _r({n: float(phi[n].abs().mean()) for n in names}, 3),
        "mean_by_class": _r(phi.groupby("speed_class")[names].mean().to_dict("index"), 3),
        "n_rows": len(phi),
    }

    # Power vs drag, and the physics decomposition of the target team's gap to pole
    result["powertrain"] = powertrain_analysis(tables["accel"])
    decomp = deficit_decomposition(events, teams, result["powertrain"])
    result["deficit_decomposition"] = _r(decomp, 4)
    if decomp:
        dd = pd.DataFrame(decomp)
        summ = {}
        for season, g in dd.groupby("season"):
            r = float(np.corrcoef(g["predicted_gap_s"], g["actual_gap_s"])[0, 1]) if len(g) > 2 else np.nan
            summ[str(season)] = {
                "n_events": len(g), "mean_actual_s": g["actual_gap_s"].mean(), "mean_predicted_s": g["predicted_gap_s"].mean(),
                "mean_grip_s": g["grip_s"].mean(), "mean_mechanical_s": g["mechanical_grip_s"].mean(),
                "mean_power_s": g["power_s"].mean(), "correlation": r,
                "explained_share": g["predicted_gap_s"].sum() / g["actual_gap_s"].sum(),
            }
        result["deficit_summary"] = _r(summ, 3)

    if upgrades_csv.exists():
        majors = pd.read_csv(upgrades_csv)
        majors = majors[majors["major_performance_upgrade"] == "major"]
        result["upgrade_components"] = [
            _r(x, 4) for x in (upgrade_component_shift(teams, tables["accel"], int(r.season), r.grand_prix)
                               for r in majors.itertuples()) if x is not None
        ]

    tt = teams.copy()
    tt["grip_high_rel"] = tt["grip_high_g"] / tt.groupby(["season", "round"])["grip_high_g"].transform("median")
    tt["grip_low_rel"] = tt["grip_low_g"] / tt.groupby(["season", "round"])["grip_low_g"].transform("median")
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

    # Data quality overview
    d_all = tables["drivers"]
    result["data_quality"] = {
        "laps_total": int(len(d_all)), "laps_passed": int(d_all["passed_checks"].sum()),
        "events_geometry_failed": sorted({e["event"] + f" {e['season']}" for e in events.values() if not e["geometry_ok"]}),
        "gps_lag_s_median": _r(float(d_all["q_gps_lag_s"].median()), 3),
        "projection_rms_m_median": _r(float(d_all["q_projection_rms_m"].median()), 2),
    }
    skipped_path = out_dir / "skipped.json"
    result["skipped_events"] = json.loads(skipped_path.read_text()) if skipped_path.exists() else []
    (out_dir / "season.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    return result
