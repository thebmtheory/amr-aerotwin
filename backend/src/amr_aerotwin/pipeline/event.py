"""Process one Grand Prix end to end: qualifying laps, physics, lap sim, comparisons, race pace.

Every stage that can fail independently is isolated, and failures are recorded in
`summary["warnings"]` rather than aborting the season build.
"""

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from amr_aerotwin.data.alignment import align_lap, build_reference_line, parse_raw_lap, project_onto_reference
from amr_aerotwin.data.repository import (
    DataUnavailableError,
    TelemetryRepository,
    fastest_valid_lap,
    lap_ambient,
)
from amr_aerotwin.domain import TARGET_TEAM, AlignedLap, LapMeta, regulations_for
from amr_aerotwin.modeling.calibration import (
    calibrate_lapsim,
    fit_discrepancy_gp,
    metropolis_posterior,
    posterior_lap_times,
)
from amr_aerotwin.modeling.energy import lap_energy_summary, straight_energy_metrics, straight_speed_profile
from amr_aerotwin.modeling.lap_compare import compare_laps
from amr_aerotwin.modeling.pod import PODReducedOrderModel
from amr_aerotwin.modeling.powertrain import event_power_drag_rows
from amr_aerotwin.modeling.race_pace import fit_race_pace
from amr_aerotwin.modeling.validation import check_lap, expected_turn_count, geometry_ok
from amr_aerotwin.physics.dynamics import (
    HIGH_SPEED_CORNER,
    STRAIGHT,
    VehicleState,
    corner_speed_class,
    estimate_vehicle_state,
    lap_curvature,
)
from amr_aerotwin.physics.kinematics import consensus_curvature, select_gps_smoothing, turning_number
from amr_aerotwin.physics.lapsim import VehicleParams, iso_lap_time_grid, lap_time_sensitivities
from amr_aerotwin.physics.vehicle_params import (
    corner_limit_points,
    fit_grip_vs_q,
    limit_points_for_fit,
    straight_segments,
)

log = logging.getLogger(__name__)
QUALI = "Qualifying"
RACE = "Race"
EXPORT_STEP = 2  # export every 2nd grid point (10 m) to the report


@dataclass
class EventOutput:
    summary: dict[str, Any]
    driver_rows: pd.DataFrame
    team_rows: pd.DataFrame
    corner_rows: pd.DataFrame
    race_rows: pd.DataFrame
    accel_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    profile_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)


def _r(x: Any, nd: int = 3) -> Any:
    """Round floats (and NaN/inf to None) recursively through arrays, lists and dicts."""
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (np.ndarray, list, tuple)):
        return [_r(v, nd) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else round(float(x), nd)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def prefetch_event(repo: TelemetryRepository, year: int, event: str, workers: int = 8) -> None:
    """Download (or confirm cached) everything one event needs."""
    for sess in (QUALI, RACE):
        for name in ("session_laptimes.json", "drivers.json", "corners.json", "weather.json"):
            try:
                repo.fetch_json(year, f"{event}/{sess}/{name}")
            except DataUnavailableError:
                if sess == QUALI:
                    raise
    laps = repo.session_laps(year, event, QUALI)
    jobs = []
    for drv in laps["drv"].dropna().unique():
        row = fastest_valid_lap(laps, drv)
        if row is not None:
            jobs.append((drv, int(row["lap"])))

    def get(job: tuple[str, int]) -> None:
        try:
            repo.lap_telemetry(year, event, QUALI, job[0], job[1])
        except DataUnavailableError:
            pass

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(get, jobs))


def _load_quali_laps(repo: TelemetryRepository, year: int, event: str) -> tuple[dict[str, AlignedLap], Any, pd.DataFrame, list[str]]:
    laps = repo.session_laps(year, event, QUALI)
    amb = repo.session_ambient(year, event, QUALI)
    try:
        drv = repo.drivers(year, event, QUALI)
        colors = dict(drv[["driver", "color"]].itertuples(index=False)) if not drv.empty else {}
    except DataUnavailableError:
        colors = {}
    valid = laps[laps["time"].notna() & ~laps["del"]]
    warnings: list[str] = []
    pole_row = None
    for _, row in valid.sort_values("time").iterrows():  # pole lap with usable telemetry
        try:
            raw = parse_raw_lap(repo.lap_telemetry(year, event, QUALI, row["drv"], int(row["lap"])))
            pole_row, ref = row, build_reference_line(raw, float(row["time"]))
            break
        except (DataUnavailableError, ValueError) as err:
            warnings.append(f"reference candidate {row['drv']} unusable: {err}")
    if pole_row is None:
        raise DataUnavailableError(f"No usable qualifying telemetry for {year} {event}")

    out: dict[str, AlignedLap] = {}
    for drv in sorted(valid["drv"].unique()):
        r = fastest_valid_lap(laps, drv)
        try:
            raw = parse_raw_lap(repo.lap_telemetry(year, event, QUALI, drv, int(r["lap"])))
            meta = LapMeta(
                season=year, event=event, session=QUALI, driver=drv, team=str(r["team"]),
                lap_number=int(r["lap"]), lap_time_s=float(r["time"]), compound=str(r["compound"]),
                tyre_life_laps=int(r["life"]) if pd.notna(r["life"]) else 1,
                sector_times_s=tuple(float(r[c]) if pd.notna(r[c]) else np.nan for c in ("s1", "s2", "s3")),
                speed_trap_kmh=float(r["vst"]) if pd.notna(r["vst"]) else np.nan,
                team_color=colors.get(drv, "#777777"),
            )
            out[drv] = align_lap(raw, meta, lap_ambient(r, amb), ref)
        except (DataUnavailableError, ValueError) as err:
            warnings.append(f"{drv}: {err}")
    return out, ref, laps, warnings


def _export_trace(arr: np.ndarray, nd: int = 2) -> list:
    return _r(np.asarray(arr)[::EXPORT_STEP], nd)


def _straight_speed_deltas(states: dict[str, VehicleState], ref_state: VehicleState) -> tuple[dict[str, float], float]:
    """Each car's peak speed on the main straights vs the field median (km/h, averaged).

    Also returns the field-median peak speed (km/h) averaged over the straights.
    """
    segs = straight_segments(ref_state, min_length_m=350.0, trim_m=0.0)
    if not segs:
        return {}, float("nan")
    peaks = {}
    for d, st in states.items():
        vals = []
        for seg in segs:
            lo, hi = seg[0], min(seg[-1] + 20, len(st.speed_smooth_ms) - 1)  # include braking point
            vals.append(float(np.max(st.speed_smooth_ms[lo:hi + 1]) * 3.6))
        peaks[d] = np.array(vals)
    med = np.median(np.vstack(list(peaks.values())), axis=0)
    return {d: float(np.mean(v - med)) for d, v in peaks.items()}, float(np.mean(med))


def _calibrate(state: VehicleState, kappa: np.ndarray, use_low_drag: bool, mh: bool) -> dict[str, Any]:
    lap = state.lap
    base = VehicleParams(state.mass_kg, 4.5, 1.3, 1.8, 650e3, state.rho_kg_m3,
                         low_drag_cda_m2=1.0 if use_low_drag else None)
    mask = lap.drs > 0.5 if use_low_drag else None
    cal = calibrate_lapsim(lap.distance_m, kappa, lap.speed_ms, base, lap.meta.lap_time_s, mask, lap.lap_length_m)
    disc = fit_discrepancy_gp(lap.distance_m, lap.speed_ms - cal.sim.speed_ms)
    lt = posterior_lap_times(cal, lap.distance_m, kappa, mask, lap.lap_length_m, n_draws=120)
    sens = lap_time_sensitivities(lap.distance_m, kappa, cal.params, mask, lap.lap_length_m)
    out: dict[str, Any] = {
        "driver": lap.meta.driver,
        "team": lap.meta.team,
        "params": {n: {"median": _r(m, 4), "lo": _r(lo, 4), "hi": _r(hi, 4)} for n, (m, lo, hi) in cal.ci90().items()},
        "param_names": list(cal.names),
        "correlation": _r(cal.correlation(), 3),
        "rmse_kmh": _r(cal.rmse_kmh, 2),
        "lap_time_error_s": _r(cal.lap_time_error_s, 3),
        "posterior_lap_time_sd_s": _r(float(np.std(lt)), 3),
        "noise_sigma_kmh": _r(cal.noise_sigma_ms * 3.6, 2),
        "lag1_autocorr": _r(cal.lag1_autocorr, 3),
        "n_effective": _r(cal.n_effective, 1),
        "converged": cal.converged,
        "sensitivities": {k: _r(v, 4) for k, v in sens.items()},
        "trace": {
            "observed_kmh": _export_trace(lap.speed_ms * 3.6, 1),
            "sim_kmh": _export_trace(cal.sim.speed_ms * 3.6, 1),
            "limit": _export_trace(cal.sim.limit, 0),
            "disc_mean_kmh": _export_trace(disc.mean_kmh, 2),
            "disc_sd_kmh": _export_trace(disc.std_kmh, 2),
        },
        "discrepancy_length_scale_m": _r(disc.length_scale_m, 1),
        "_params_obj": cal.params,
    }
    if mh:
        samples, acc = metropolis_posterior(cal, lap.distance_m, kappa, mask, lap.lap_length_m, n_steps=1500, burn_in=300)
        out["mcmc_check"] = {
            "acceptance": _r(acc, 3),
            "laplace_sd_log": _r(np.sqrt(np.diag(cal.cov_log)), 4),
            "mcmc_sd_log": _r(samples.std(axis=0), 4),
            "mcmc_minus_map_log": _r(samples.mean(axis=0) - cal.theta_map, 4),
        }
    return out


def process_event(repo: TelemetryRepository, year: int, event: str, round_no: int, run_mcmc: bool = True) -> EventOutput:
    warns: list[str] = []
    regs = regulations_for(year)
    laps, ref, session_laps, w = _load_quali_laps(repo, year, event)
    warns += w

    checks = {d: check_lap(lp) for d, lp in laps.items()}
    good = {d: lp for d, lp in laps.items() if checks[d].passed}
    for d, c in checks.items():
        if not c.passed:
            warns.append(f"{d} failed data checks: {c.failures}")
    if len(good) < 8:
        raise DataUnavailableError(f"Only {len(good)} laps passed checks for {year} {event}")

    lam, lam_scores = select_gps_smoothing(
        [(lp.gps_time_s, lp.gps_x_m, lp.gps_y_m, lp.meta.lap_time_s, lp.time_s, lp.speed_ms) for lp in good.values() if len(lp.gps_time_s) > 50]
    )
    kappa = consensus_curvature([lap_curvature(lp, lam) for lp in good.values()])
    tn = turning_number(kappa, ref.step_m)
    n_turns = expected_turn_count(ref.x_m, ref.y_m)
    geo_ok = geometry_ok(tn, n_turns)
    if not geo_ok:
        warns.append(f"geometry check failed (turning number {tn:.3f}, expected {n_turns}); curvature-based fits skipped")

    states = {d: estimate_vehicle_state(lp, curvature_inv_m=kappa) for d, lp in good.items()}
    pole_drv = min(good, key=lambda d: good[d].meta.lap_time_s)
    pole = good[pole_drv]
    pole_state = states[pole_drv]
    fastest = min(lp.meta.lap_time_s for lp in laps.values())

    # Corners on the reference line
    corners = repo.corners(year, event)
    c_s, _ = project_onto_reference(corners["x_m"].to_numpy(), corners["y_m"].to_numpy(), ref)
    order = np.argsort(c_s)
    c_s = c_s[order]
    c_lab = [f"T{n}{lp}" for n, lp in zip(corners["number"].to_numpy()[order], corners["letter"].to_numpy()[order])]
    info = repo.circuit_info(year, event)

    # ------------------------------------------------------------------ grip per team
    team_of = {d: lp.meta.team for d, lp in good.items()}
    color_of = {lp.meta.team: lp.meta.team_color for lp in good.values()}
    pts = {}
    for d, st in states.items():
        p = corner_limit_points(st, c_s)
        p["driver"], p["team"], p["corner_key"] = d, team_of[d], p["corner_index"]
        pts[d] = p
    all_pts = pd.concat(pts.values(), ignore_index=True)
    lim = limit_points_for_fit(all_pts)
    q_low, q_high = (float(np.percentile(lim["q_pa"], 15)), float(np.percentile(lim["q_pa"], 85))) if len(lim) else (np.nan, np.nan)
    grip = {}
    if geo_ok:
        for team in sorted(set(team_of.values())):
            g = fit_grip_vs_q(all_pts[all_pts["team"] == team], q_low, q_high, n_boot=200)
            if g is not None:
                grip[team] = g
    straight_delta, straight_peak_kmh = _straight_speed_deltas(states, pole_state)

    # ------------------------------------------------------------------ energy + acceleration bands
    energy = {d: lap_energy_summary(st) for d, st in states.items()}
    accel_rows = event_power_drag_rows(states, pole_state)
    accel_rows["season"], accel_rows["round"], accel_rows["event"] = year, round_no, event
    profile_rows = straight_speed_profile(list(states.values()), pole_state)
    if not profile_rows.empty:
        profile_rows["season"], profile_rows["round"], profile_rows["event"] = year, round_no, event

    # ------------------------------------------------------------------ driver + team tables
    drows = []
    for d, lp in laps.items():
        e = energy.get(d, {})
        drows.append({
            "season": year, "round": round_no, "event": event, "driver": d, "team": lp.meta.team,
            "color": lp.meta.team_color, "lap_number": lp.meta.lap_number, "lap_time_s": lp.meta.lap_time_s,
            "gap_pct": (lp.meta.lap_time_s / fastest - 1) * 100, "compound": lp.meta.compound,
            "tyre_life": lp.meta.tyre_life_laps, "passed_checks": checks[d].passed,
            "straight_speed_delta_kmh": straight_delta.get(d, np.nan),
            "clip_speed_drop_kmh": e.get("speed_drop_kmh", np.nan),
            "clip_decel_distance_m": e.get("decel_distance_m", np.nan),
            "clip_power_deficit_kw": e.get("power_deficit_kw", np.nan),
            "clip_time_loss_s": e.get("time_loss_s", np.nan),
            **{f"q_{k}": v for k, v in lp.quality.items()},
        })
    driver_rows = pd.DataFrame(drows)

    trows = []
    for team, g in driver_rows[driver_rows["passed_checks"]].groupby("team"):
        best = g.loc[g["lap_time_s"].idxmin()]
        gf = grip.get(team)
        trows.append({
            "season": year, "round": round_no, "event": event, "team": team, "color": color_of.get(team, "#777"),
            "best_driver": best["driver"], "lap_time_s": best["lap_time_s"], "gap_pct": best["gap_pct"],
            "grip_low_g": gf.grip_low_g if gf else np.nan, "grip_low_lo": gf.grip_low_ci90[0] if gf else np.nan,
            "grip_low_hi": gf.grip_low_ci90[1] if gf else np.nan,
            "grip_high_g": gf.grip_high_g if gf else np.nan, "grip_high_lo": gf.grip_high_ci90[0] if gf else np.nan,
            "grip_high_hi": gf.grip_high_ci90[1] if gf else np.nan,
            "aero_share_high": gf.aero_share_high if gf else np.nan,
            "straight_speed_delta_kmh": g["straight_speed_delta_kmh"].mean(),
            "clip_speed_drop_kmh": g["clip_speed_drop_kmh"].mean(),
            "clip_decel_distance_m": g["clip_decel_distance_m"].mean(),
            "clip_power_deficit_kw": g["clip_power_deficit_kw"].mean(),
            "clip_time_loss_s": g["clip_time_loss_s"].mean(),
        })
    team_rows = pd.DataFrame(trows)

    # ------------------------------------------------------------------ track character
    high_share = float(np.mean(pole_state.regime == HIGH_SPEED_CORNER))
    full_throttle = float(np.mean(pole.throttle_pct >= 98.0))
    straight_share = float(np.mean(pole_state.regime == STRAIGHT))
    team_rows["track_x"] = high_share
    team_rows["straight_peak_kmh"] = straight_peak_kmh
    team_rows["geometry_ok"] = geo_ok

    # ------------------------------------------------------------------ corner rows
    crows = []
    length = ref.length_m
    prev = np.roll(c_s, 1)
    approach = (c_s - prev) % length
    pole_min = {}
    for i, cs in enumerate(c_s):
        dd = (pole.distance_m - cs + length / 2) % length - length / 2
        pole_min[i] = float(np.min(pole_state.speed_smooth_ms[np.abs(dd) <= 60]) * 3.6)
    for d, st in states.items():
        lp = st.lap
        for i, cs in enumerate(c_s):
            dd = (lp.distance_m - cs + length / 2) % length - length / 2
            win = np.abs(dd) <= 60
            near = np.abs(dd) <= 30
            if win.sum() < 5:
                continue
            idx = np.flatnonzero(win)[np.argmin(st.speed_smooth_ms[win])]
            crows.append({
                "season": year, "round": round_no, "event": event, "event_key": f"{year}-{event}",
                "circuit_corner": f"{info.get('circuit_name')}-{c_lab[i]}", "corner_key": c_lab[i],
                "driver": d, "team": lp.meta.team, "v_min_kmh": float(st.speed_smooth_ms[idx] * 3.6),
                "radius_m": float(1.0 / max(np.max(np.abs(kappa[near])), 1e-4)),
                "turn_angle_deg": float(np.degrees(abs(np.sum(kappa[win]) * ref.step_m))),
                "approach_m": float(approach[i]), "rho_kg_m3": st.rho_kg_m3,
                "headwind_ms": float(st.v_headwind_ms[idx]), "track_temp_c": lp.ambient.track_temp_c,
                "tyre_life": lp.meta.tyre_life_laps, "season_2026": float(year >= 2026),
                "speed_class": corner_speed_class(pole_min[i]), "geometry_ok": geo_ok,
            })
    corner_rows = pd.DataFrame(crows)

    # ------------------------------------------------------------------ lap comparison (AMR vs pole)
    summary: dict[str, Any] = {
        "season": year, "event": event, "round": round_no,
        "date": str(session_laps["lSD"].dropna().min())[:10] if "lSD" in session_laps else None,
        "circuit": info, "lap_length_m": _r(length, 1), "gps_smoothing_lam": lam,
        "gps_smoothing_scores": {str(k): _r(v, 3) for k, v in lam_scores.items()},
        "turning_number": _r(tn, 4), "expected_turns": n_turns, "geometry_ok": geo_ok, "distance_scale": _r(ref.scale, 4),
        "pole": {"driver": pole_drv, "team": pole.meta.team, "lap_time_s": pole.meta.lap_time_s},
        "track": {"high_speed_share": _r(high_share), "full_throttle_share": _r(full_throttle),
                  "straight_share": _r(straight_share), "q_low_pa": _r(q_low, 0), "q_high_pa": _r(q_high, 0),
                  "straight_peak_kmh": _r(straight_peak_kmh, 1)},
        "regulations": {"mass_kg": regs.quali_min_mass_kg + regs.quali_fuel_kg, "has_drs": regs.has_drs},
        "n_laps": len(laps), "n_passed": len(good),
        "corners": {"distance_m": _r(c_s, 1), "label": c_lab},
        "map": {"x": _export_trace(pole.x_m, 1), "y": _export_trace(pole.y_m, 1),
                "distance_m": _export_trace(pole.distance_m, 0), "curvature": _export_trace(kappa, 5)},
        "grip_points": _r(lim[["team", "driver", "q_pa", "a_comb_ms2", "speed_kmh"]].to_dict("list"), 2) if len(lim) else {},
    }

    amr = {d: lp for d, lp in good.items() if lp.meta.team == TARGET_TEAM}
    amr_best = min(amr, key=lambda d: amr[d].meta.lap_time_s) if amr else None
    if amr_best:
        cmp_ = compare_laps(good[amr_best], pole, c_s, c_lab)
        summary["comparison"] = {
            "target": amr_best, "reference": pole_drv,
            "target_speed_kmh": _export_trace(good[amr_best].speed_ms * 3.6, 1),
            "reference_speed_kmh": _export_trace(pole.speed_ms * 3.6, 1),
            "target_throttle": _export_trace(good[amr_best].throttle_pct, 0),
            "reference_throttle": _export_trace(pole.throttle_pct, 0),
            "target_brake": _export_trace(good[amr_best].brake, 0),
            "reference_brake": _export_trace(pole.brake, 0),
            "delta_s": _export_trace(cmp_.delta_s, 3),
            "corners": _r(cmp_.corner_table.to_dict("records"), 3),
            "class_summary": _r(cmp_.class_summary.to_dict("records"), 3),
            "total_delta_s": _r(cmp_.total_delta_s, 3),
        }

    # ------------------------------------------------------------------ lap sim calibration + sensitivities
    sims = {}
    if geo_ok:
        for d in dict.fromkeys([pole_drv, amr_best]):
            if d is None:
                continue
            try:
                sims[d] = _calibrate(states[d], kappa, regs.has_drs, mh=run_mcmc and d == amr_best)
            except Exception as err:  # noqa: BLE001 - one failed fit must not drop the event
                warns.append(f"lap sim calibration failed for {d}: {err}")
    if sims:
        key = amr_best if amr_best in sims else pole_drv
        p_obj: VehicleParams = sims[key]["_params_obj"]
        mask = good[key].drs > 0.5 if regs.has_drs else None
        cla_pct = np.linspace(-10, 10, 9)
        cda_pct = np.linspace(-10, 10, 9)
        grid = iso_lap_time_grid(pole.distance_m, kappa, p_obj, cla_pct, cda_pct, mask, length)
        summary["iso_lap_time"] = {"cla_pct": _r(cla_pct, 1), "cda_pct": _r(cda_pct, 1), "delta_s": _r(grid, 4), "car": key}
        summary["sandbox"] = {
            "car": key, "distance_m": _r(pole.distance_m, 1), "curvature": _r(kappa, 6),
            "low_drag_mask": _r(mask.astype(int), 0) if mask is not None else None,
            "lap_length_m": _r(length, 2), "observed_lap_time_s": good[key].meta.lap_time_s,
            "params": {k: getattr(p_obj, k) for k in ("mass_kg", "cla_m2", "cda_m2", "mu", "power_w",
                                                     "rho_kg_m3", "crr", "low_drag_cda_m2", "long_grip_scale")},
        }
    summary["lapsim"] = {d: {k: v for k, v in s.items() if not k.startswith("_")} for d, s in sims.items()}

    # ------------------------------------------------------------------ POD across the field
    try:
        snap_d = sorted(good, key=lambda d: good[d].meta.lap_time_s)
        snap = np.vstack([good[d].speed_ms * 3.6 for d in snap_d])
        pod = PODReducedOrderModel(n_modes=3).fit_transform(snap)
        summary["pod"] = {
            "drivers": snap_d, "teams": [good[d].meta.team for d in snap_d],
            "explained": _r(pod.explained_variance_ratio[:6], 4),
            "modes": [_export_trace(m, 4) for m in pod.spatial_modes],
            "mean_kmh": _export_trace(pod.mean_trace, 1),
            "coefficients": _r(pod.modal_coefficients, 2),
            "lap_time_s": [good[d].meta.lap_time_s for d in snap_d],
            "reconstruction_rmse_kmh": _r(pod.reconstruction_rmse, 2),
            "loo_rmse_kmh": _r(pod.loo_reconstruction_rmse, 2),
        }
    except Exception as err:  # noqa: BLE001
        warns.append(f"POD failed: {err}")

    # ------------------------------------------------------------------ energy straights (AMR + pole)
    summary["energy"] = {
        d: _r(straight_energy_metrics(states[d]).to_dict("list"), 2) for d in dict.fromkeys([pole_drv, amr_best]) if d
    }
    summary["energy_speed"] = {
        d: _export_trace(states[d].speed_smooth_ms * 3.6, 1) for d in dict.fromkeys([pole_drv, amr_best]) if d
    }

    # ------------------------------------------------------------------ race pace
    race_rows = pd.DataFrame()
    try:
        rl = repo.session_laps(year, event, RACE)
        rp = fit_race_pace(rl, dict(zip(rl["drv"], rl["team"])))
        if rp is not None:
            race_rows = rp.team_pace.assign(season=year, round=round_no, event=event)
            summary["race_pace"] = {
                "fuel_s_per_lap": _r(rp.fuel_s_per_lap, 4), "fuel_ci90": _r(rp.fuel_ci90, 4),
                "deg_s_per_lap": _r(rp.deg_s_per_lap, 4), "deg_ci90": {k: _r(v, 4) for k, v in rp.deg_ci90.items()},
                "reference_compound": rp.reference_compound, "n_laps": rp.n_laps,
                "residual_sd_s": _r(rp.residual_sd_s, 3),
                "team_pace": _r(rp.team_pace.to_dict("records"), 3),
            }
        else:
            warns.append("race pace skipped (wet or insufficient green-flag slick running)")
    except DataUnavailableError as err:
        warns.append(f"race data unavailable: {err}")
    except Exception as err:  # noqa: BLE001
        warns.append(f"race pace failed: {err}")

    summary["warnings"] = warns
    summary["driver_table"] = _r(driver_rows.drop(columns=[c for c in driver_rows if c.startswith("q_")]).to_dict("records"), 4)
    summary["team_table"] = _r(team_rows.to_dict("records"), 4)
    summary["data_checks"] = {
        d: {"passed": c.passed, "failures": _r(c.failures, 2),
            "metrics": _r({k: laps[d].quality[k] for k in laps[d].quality}, 3)} for d, c in checks.items()
    }
    return EventOutput(summary, driver_rows, team_rows, corner_rows, race_rows, accel_rows, profile_rows, warns)


def safe_process_event(repo: TelemetryRepository, year: int, event: str, round_no: int, run_mcmc: bool = True) -> EventOutput | str:
    """Process an event; on failure return the reason as a string instead of raising."""
    try:
        return process_event(repo, year, event, round_no, run_mcmc)
    except Exception as err:  # noqa: BLE001
        log.error("event %s %s failed:\n%s", year, event, traceback.format_exc())
        return f"{type(err).__name__}: {err}"
