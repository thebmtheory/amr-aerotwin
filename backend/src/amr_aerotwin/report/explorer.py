"""Per-track, per-driver data for the report's track-by-track and track-detail views.

At every event, each Aston Martin driver's fastest qualifying lap that passed the data checks
is compared with the event's reference lap (the fastest lap that passes every check), and the
other teams' fastest passing laps form the field. Section and corner times come from the
timing channel on a shared distance grid, so they add up to the gap between the two laps.
Corner minimum speeds are used only where the speed channel agrees with GPS; straights are
the reference lap's full-throttle runs.

Two outputs:
- an index, loaded with the page, holding everything the multi-track views add up (lap
  times and ranks, section losses of every team, corner-class and straight-line speed
  differences as sums and counts, race pace). Sums rather than means, so any set of tracks
  combines exactly in the browser.
- one file per event, loaded when that track is opened, with the single-track detail (speed
  traces, track map, corner table, straight speeds, team order).
"""

from __future__ import annotations

import ast
import json
import logging
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from amr_aerotwin.data.repository import DataUnavailableError, TelemetryRepository
from amr_aerotwin.domain import TARGET_TEAM
from amr_aerotwin.modeling.lap_compare import compare_laps, cumulative_gap, segment_time_loss
from amr_aerotwin.modeling.validation import check_lap, corner_min_speeds, flag_corner_speeds
from amr_aerotwin.physics.dynamics import HIGH_SPEED_MIN_KMH, LOW_SPEED_MAX_KMH, estimate_vehicle_state, lap_curvature
from amr_aerotwin.physics.kinematics import consensus_curvature
from amr_aerotwin.physics.vehicle_params import straight_segments
from amr_aerotwin.pipeline.event import QUALI, _load_quali_laps, _r, corner_positions
from amr_aerotwin.report.build import _clean

log = logging.getLogger(__name__)

SECTIONS = ["straights", "high", "medium", "low"]
CLASSES = ["high", "medium", "low"]
FULL_THROTTLE_PCT = 98.0
TRACE_STEP = 2  # every 2nd point of the 5 m grid (10 m)
STRAIGHT_STEP = 2  # straights are short; 10 m as well
REPRESENTATIVE = 1.07  # laps slower than 107% of the fastest are not pace
STRAIGHT_MIN_M = 400.0  # the straights shown: full-throttle runs at least this long

# Official turn numbers come from the timing archive; names are the circuit's own.
CORNER_NAMES: dict[str, dict[str, str]] = {
    "Silverstone": {
        "T1": "Abbey", "T2": "Farm", "T3": "Village", "T4": "The Loop", "T5": "Aintree", "T6": "Brooklands",
        "T7": "Luffield", "T8": "Woodcote", "T9": "Copse", "T10": "Maggotts", "T11": "Maggotts",
        "T12": "Becketts", "T13": "Becketts", "T14": "Chapel", "T15": "Stowe", "T16": "Vale", "T17": "Vale",
        "T18": "Club",
    },
}
# Straights are named by the corner they leave
STRAIGHT_NAMES: dict[str, dict[str, str]] = {"Silverstone": {"T5": "Wellington Straight", "T14": "Hangar Straight"}}

# Short reader-facing names for the lap checks (modeling.validation.LAP_CHECKS)
CHECK_LABELS = {
    "projection_rms_m": "GPS trace off the track line", "finish_line_gap_m": "GPS position at the line",
    "start_line_gap_m": "GPS position at the line", "line_gap_mismatch_m": "lap clock mismatch",
    "sector_time_error_s": "sector times do not match", "speed_time_consistency_pct": "speed and timing channels disagree",
    "gps_speed_rms_ms": "GPS and wheel speed disagree", "max_sample_gap_m": "telemetry dropout",
    "speed_trap_minus_max_kmh": "speed trap above telemetry peak", "frozen_run_m": "frozen telemetry",
    "car_data_stall_kmh": "car-data stall",
}


def slug(event: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", event.lower()).strip("-")


def full_throttle_speed_loss(v_kmh: np.ndarray, throttle: np.ndarray) -> float:
    """Largest drop below the running peak speed while still at full throttle (km/h).

    At constant drive power a car below its terminal speed only accelerates on a level
    straight: drag alone flattens the speed, it does not make it fall. A grade can (uphill),
    but every car meets the same grade at the same place, so a fall that the other cars do not
    show means this car's drive power fell (energy deployment ended or the car is harvesting).
    """
    peak = np.maximum.accumulate(v_kmh)
    drop = np.where(throttle >= FULL_THROTTLE_PCT, peak - v_kmh, 0.0)
    return float(np.max(drop)) if len(drop) else float("nan")


def straight_metrics(v_kmh: np.ndarray, throttle: np.ndarray) -> dict[str, float]:
    return {"entry_kmh": float(v_kmh[0]), "peak_kmh": float(np.max(v_kmh)), "end_kmh": float(v_kmh[-1]),
            "full_throttle_loss_kmh": full_throttle_speed_loss(v_kmh, throttle),
            "full_throttle_share": float(np.mean(throttle >= FULL_THROTTLE_PCT))}


def no_telemetry_reason(driver: str, warnings: list[str]) -> str:
    """Why a driver with an official lap time has no usable telemetry, from the event warnings."""
    for w in warnings:
        if w.startswith(f"{driver} failed data checks:"):
            try:
                keys = list(ast.literal_eval(w.split(":", 1)[1].strip()))
            except (ValueError, SyntaxError):
                keys = []
            labels = list(dict.fromkeys(CHECK_LABELS.get(k, k) for k in keys))
            return "failed data checks: " + ", ".join(labels) if labels else "failed data checks"
    # Anything else (no telemetry file, a lap that could not be read or aligned)
    return "no usable telemetry"


def _round(a: np.ndarray, nd: int) -> np.ndarray:
    return np.round(np.asarray(a, dtype=float), nd)


def explorer_event(ev: dict[str, Any], timing: pd.DataFrame, sections: pd.DataFrame, repo: TelemetryRepository,
                   target: str = TARGET_TEAM) -> tuple[dict[str, Any], dict[str, Any]]:
    """(index entry, single-track detail) for one event.

    `timing`: official fastest lap of every driver (season table); `sections`: every team's
    section losses to the reference lap (season table, from the same comparison as here).
    """
    year, event = int(ev["season"]), str(ev["event"])
    key = f"{year}-{slug(event)}"
    warnings = list(ev.get("warnings", []))
    laps, ref, _, _ = _load_quali_laps(repo, year, event)
    good = {d: lp for d, lp in laps.items() if check_lap(lp).passed}
    ref_drv = ev["pole"]["driver"]
    ref_lap = good[ref_drv]
    kappa = consensus_curvature([lap_curvature(lp, ev["gps_smoothing_lam"]) for lp in good.values()])
    states = {d: estimate_vehicle_state(lp, curvature_inv_m=kappa) for d, lp in good.items()}
    # The exact marker positions of the event build (its summary stores them rounded), so the
    # corner/straight split matches the season tables cell for cell
    corner_s, labels = corner_positions(repo, year, event, ref)
    circuit = (ev.get("circuit") or {}).get("circuit_name", "") or event
    names = CORNER_NAMES.get(circuit, {})

    team_of = {d: lp.meta.team for d, lp in good.items()}
    team_best: dict[str, str] = {}
    for d in sorted(good, key=lambda x: good[x].meta.lap_time_s):
        team_best.setdefault(team_of[d], d)
    field = [d for t, d in team_best.items() if t != target]
    amr = sorted(d for d in good if team_of[d] == target)

    # Corner minimum speeds, each checked against GPS relative to every passing lap there
    vmin = {d: corner_min_speeds(st, corner_s) for d, st in states.items()}
    flag_corner_speeds(vmin)
    ref_cmp = compare_laps(ref_lap, ref_lap, corner_s, labels)
    classes = [str(c) for c in ref_cmp.corner_table["speed_class"]]
    ref_cs = ref_cmp.class_summary.set_index("speed_class")
    ref_time = {s: float(ref_cs.loc[s, "reference_time_s"]) for s in SECTIONS}
    corners: list[dict[str, Any]] = []
    for i, lab in enumerate(labels):
        fm = [vmin[d][i]["wheel_kmh"] for d in field if vmin[d][i]["ok"]]
        corners.append({"label": lab, "name": names.get(lab, ""), "distance_m": float(corner_s[i]), "speed_class": classes[i],
                        "pole_kmh": vmin[ref_drv][i]["wheel_kmh"], "pole_ok": bool(vmin[ref_drv][i]["ok"]),
                        "field_median_kmh": float(np.median(fm)) if fm else None, "n_field": len(fm)})

    # Straights: the reference lap's full-throttle runs of 400 m or more, clear of the timing line
    ref_state = states[ref_drv]
    n = len(ref_lap.distance_m)
    straights: list[dict[str, Any]] = []
    for seg in straight_segments(ref_state, min_length_m=STRAIGHT_MIN_M, trim_m=0.0, drop_line_cut=True):
        lo, hi = int(seg[0]), int(min(seg[-1] + 4, n - 1))  # +20 m past the reference's lift
        sl = slice(lo, hi + 1)
        speed = {d: states[d].speed_smooth_ms[sl] * 3.6 for d in dict.fromkeys(field + amr + [ref_drv])}
        mets = {d: straight_metrics(speed[d], good[d].throttle_pct[sl]) for d in speed}
        before = [lab for lab, cs in zip(labels, corner_s) if cs < ref_lap.distance_m[lo]]
        after = before[-1] if before else labels[-1]
        fstack = np.vstack([speed[d] for d in field]) if field else None
        straights.append({
            "name": STRAIGHT_NAMES.get(circuit, {}).get(after, f"Straight after {after}"), "after_corner": after,
            "start_m": float(ref_lap.distance_m[lo]), "end_m": float(ref_lap.distance_m[hi]),
            "distance_m": _round(ref_lap.distance_m[sl][::STRAIGHT_STEP], 1),
            "pole_kmh": _round(speed[ref_drv][::STRAIGHT_STEP], 1),
            "field_median_kmh": _round(np.median(fstack, axis=0)[::STRAIGHT_STEP], 1) if fstack is not None else None,
            "field_min_kmh": _round(np.min(fstack, axis=0)[::STRAIGHT_STEP], 1) if fstack is not None else None,
            "field_max_kmh": _round(np.max(fstack, axis=0)[::STRAIGHT_STEP], 1) if fstack is not None else None,
            "field": {k: float(np.median([mets[d][k] for d in field])) if field else None
                      for k in ("entry_kmh", "peak_kmh", "end_kmh", "full_throttle_loss_kmh")},
            "teams": {team_of[d]: {k: mets[d][k] for k in ("entry_kmh", "peak_kmh", "end_kmh", "full_throttle_loss_kmh")} for d in field},
            "drivers": {d: {**mets[d], "speed_kmh": _round(speed[d][::STRAIGHT_STEP], 1),
                            "throttle": _round(good[d].throttle_pct[sl][::STRAIGHT_STEP], 0)} for d in amr},
        })

    # Each Aston Martin driver against the reference lap
    drivers: dict[str, Any] = {}
    agg: dict[str, Any] = {}
    k100 = int(round(100.0 / ref.step_m))
    for d in amr:
        cmp = compare_laps(good[d], ref_lap, corner_s, labels)
        ct = cmp.corner_table.reset_index(drop=True)
        cs = cmp.class_summary.set_index("speed_class")
        cell = segment_time_loss(good[d], ref_lap)
        loss_100 = np.convolve(np.concatenate([cell[-k100:], cell, cell[:k100]]), np.ones(k100), mode="same")[k100:-k100]
        crow = [{"entry_s": float(ct.loc[i, "entry_s"]), "apex_s": float(ct.loc[i, "apex_s"]), "exit_s": float(ct.loc[i, "exit_s"]),
                 "total_s": float(ct.loc[i, "total_s"]), "min_kmh": vmin[d][i]["wheel_kmh"], "ok": bool(vmin[d][i]["ok"])}
                for i in range(len(labels))]
        sections_s = {s: float(cs.loc[s, "time_s"]) for s in SECTIONS}
        drivers[d] = {
            "lap_time_s": good[d].meta.lap_time_s, "compound": good[d].meta.compound, "tyre_life": good[d].meta.tyre_life_laps,
            "sections_s": sections_s, "corners": crow,
            "trace": {"speed_kmh": _round(states[d].speed_smooth_ms[::TRACE_STEP] * 3.6, 1),
                      "throttle": _round(good[d].throttle_pct[::TRACE_STEP], 0), "brake": _round(good[d].brake[::TRACE_STEP], 2),
                      "delta_s": _round(cumulative_gap(cell)[:n][::TRACE_STEP], 3)},
            "loss_per_100m_s": _round(loss_100[::TRACE_STEP], 4),
        }
        # Sums and counts, so the browser can combine any set of tracks exactly
        cls_sum = {c: [0.0, 0] for c in CLASSES}
        for i, c in enumerate(classes):
            fmed = corners[i]["field_median_kmh"]
            if crow[i]["ok"] and fmed is not None and c in cls_sum:
                cls_sum[c][0] += crow[i]["min_kmh"] - fmed
                cls_sum[c][1] += 1
        st_sum: dict[str, float] = {"entry_kmh": 0.0, "peak_kmh": 0.0, "end_kmh": 0.0, "full_throttle_loss_kmh": 0.0,
                                    "field_full_throttle_loss_kmh": 0.0, "n": 0}
        for st in straights:
            me, fld = st["drivers"][d], st["field"]
            if fld["entry_kmh"] is None:
                continue
            for k in ("entry_kmh", "peak_kmh", "end_kmh"):
                st_sum[k] += me[k] - fld[k]
            st_sum["full_throttle_loss_kmh"] += me["full_throttle_loss_kmh"]
            st_sum["field_full_throttle_loss_kmh"] += fld["full_throttle_loss_kmh"]
            st_sum["n"] += 1
        agg[d] = {"sections_s": sections_s, "corner_class_kmh": {c: {"sum": v[0], "n": v[1]} for c, v in cls_sum.items()},
                  "straights": st_sum}

    # Official timing: every driver's fastest lap; a team is its faster driver
    tm = timing[(timing["season"] == year) & (timing["event"] == event)].sort_values(["lap_time_s", "driver"]).reset_index(drop=True)
    fastest = float(tm["lap_time_s"].min())
    order: list[dict[str, Any]] = []
    for team, g in tm.groupby("team", sort=False):
        r = g.iloc[0]
        order.append({"team": str(team), "driver": str(r["driver"]), "lap_time_s": float(r["lap_time_s"]),
                      "gap_s": float(r["lap_time_s"]) - fastest, "gap_pct": 100 * (float(r["lap_time_s"]) / fastest - 1),
                      "telemetry_driver": team_best.get(str(team))})
    order.sort(key=lambda r: r["lap_time_s"])
    for i, r in enumerate(order):
        r["position"] = i + 1
    team_pos = next((r["position"] for r in order if r["team"] == target), None)
    fgap = [float(r["gap_pct"]) for r in order if r["team"] != target]
    amr_timing = {}
    for i, r in tm.iterrows():
        if r["team"] == target:
            d = str(r["driver"])
            amr_timing[d] = {"lap_time_s": float(r["lap_time_s"]), "gap_s": float(r["lap_time_s"]) - fastest,
                             "gap_pct": 100 * (float(r["lap_time_s"]) / fastest - 1), "rank": int(i) + 1, "n_drivers": int(len(tm)),
                             # FIA 107% rule, as in the season analysis: a slower lap (crash, red flag) is not pace
                             "representative": bool(float(r["lap_time_s"]) <= REPRESENTATIVE * fastest),
                             "segment": None if pd.isna(r.get("segment")) else str(r["segment"]),
                             "telemetry": d in drivers, "reason": None if d in drivers else no_telemetry_reason(d, warnings)}

    sec = sections[(sections["season"] == year) & (sections["event"] == event)]
    team_sections = {str(t): {s: float(v) for s, v in g.set_index("section")["loss_s"].reindex(SECTIONS).fillna(0.0).items()}
                     for t, g in sec.groupby("team")}

    try:
        drv = repo.drivers(year, event, QUALI)
        driver_names = {str(r.driver): str(r.name) for r in drv.itertuples() if r.team == target and r.name}
    except DataUnavailableError:
        driver_names = {}

    rp = ev.get("race_pace") or {}
    race, race_teams = None, []
    if rp.get("team_pace"):
        tp = sorted(rp["team_pace"], key=lambda r: r["gap_s"])
        race_teams = [{k: r.get(k) for k in ("team", "pace_s", "gap_s", "ci_lo", "ci_hi")} for r in tp]
        mine = next((r for r in tp if r["team"] == target), None)
        dp = {r["driver"]: r for r in rp.get("driver_pace", []) if r.get("team") == target}
        single = set(rp.get("single_stint_drivers", []))
        race = {"fastest_team": tp[0]["team"], "n_laps": rp.get("n_laps"), "n_teams": len(tp),
                "team_gap_s": mine["gap_s"] if mine else None, "team_ci": [mine["ci_lo"], mine["ci_hi"]] if mine else None,
                "team_rank": (tp.index(mine) + 1) if mine else None,
                "drivers": {x: {**{k: r.get(k) for k in ("pace_s", "gap_s", "gap_lo", "gap_hi", "n_laps")}, "single_stint": x in single}
                            for x, r in dp.items()}}
    race_note = next((w for w in warnings if w.startswith(("race pace", "race data"))), None)

    fl = ev.get("fastest_lap") or {}
    op = ev.get("official_pole") or {}
    index = {
        "key": key, "season": year, "round": int(ev["round"]), "event": event, "circuit": circuit,
        "location": (ev.get("circuit") or {}).get("location"), "date": ev.get("date"), "wet": bool(ev.get("wet_session")),
        "fastest_lap": {"driver": fl.get("driver"), "team": fl.get("team"), "lap_time_s": fl.get("lap_time_s"), "segment": fl.get("segment"),
                        "is_pole": bool(op) and fl.get("driver") == op.get("driver") and fl.get("segment", "Q3") == "Q3"},
        "reference": {"driver": ref_drv, "team": ref_lap.meta.team, "lap_time_s": ref_lap.meta.lap_time_s},
        "n_teams": len(order), "team_position": team_pos,
        "field_gap_pct": {"p25": float(np.percentile(fgap, 25)), "p50": float(np.median(fgap)), "p75": float(np.percentile(fgap, 75))} if fgap else None,
        "timing": amr_timing, "ref_time_s": ref_time, "team_sections_s": team_sections, "drivers": agg,
        "race": race, "race_note": race_note, "names": driver_names,
    }
    detail = {
        "key": key, "season": year, "event": event, "circuit": circuit, "lap_length_m": ev.get("lap_length_m"),
        "distance_m": _round(ref_lap.distance_m[::TRACE_STEP], 1),
        "map": {"x": _round(ref.x_m[:n][::TRACE_STEP], 1), "y": _round(ref.y_m[:n][::TRACE_STEP], 1)},
        "reference_trace": {"speed_kmh": _round(ref_state.speed_smooth_ms[::TRACE_STEP] * 3.6, 1),
                            "throttle": _round(ref_lap.throttle_pct[::TRACE_STEP], 0), "brake": _round(ref_lap.brake[::TRACE_STEP], 2)},
        "order": order, "corners": corners, "straights": straights, "drivers": drivers, "race_teams": race_teams,
        # A flag means this car's speed-channel-minus-GPS reading is out of line with the other cars' at that corner
        "flagged_corners": [{"driver": d, "corner": labels[i], "name": names.get(labels[i], ""), "wheel_kmh": v["wheel_kmh"],
                             "gps_kmh": v["gps_kmh"], "residual_kmh": v["residual_kmh"],
                             "field_offset_kmh": v["wheel_kmh"] - v["gps_kmh"] - v["residual_kmh"]}
                            for d in amr for i, v in enumerate(vmin[d]) if not v["ok"]],
        "straight_min_m": STRAIGHT_MIN_M,
    }
    return index, detail


def _job(args: tuple[str, str, str | None]) -> tuple[str, Any, Any]:
    ev_path, processed_dir, cache_dir = args
    ev = json.loads(Path(ev_path).read_text())
    timing = pd.read_csv(Path(processed_dir) / "timing.csv.gz")
    sections = pd.read_csv(Path(processed_dir) / "sections.csv.gz")
    repo = TelemetryRepository(Path(cache_dir)) if cache_dir else TelemetryRepository()
    try:
        index, detail = explorer_event(ev, timing, sections, repo)
    except Exception as err:  # noqa: BLE001  (one event must not stop the build; it is reported)
        return Path(ev_path).stem, None, {"key": Path(ev_path).stem, "season": int(ev["season"]), "round": int(ev["round"]),
                                          "event": str(ev["event"]), "error": f"{type(err).__name__}: {err}"}
    return Path(ev_path).stem, index, detail


def js_assign(var: str, payload: Any, key: str | None = None, nd: int = 4) -> str:
    """`window.<var>=...;` (or `window.<var>[key]=...;`) with strict JSON, NaN as null."""
    data = json.dumps(_clean(_r(payload, nd)), separators=(",", ":"), allow_nan=False)
    if key is None:
        return f"window.{var}={data};\n"
    return f"window.{var}=window.{var}||{{}};window.{var}[{json.dumps(key)}]={data};\n"


def build_explorer(processed_dir: Path, site_dir: Path, workers: int = 8, target: str = TARGET_TEAM,
                   cache_dir: Path | None = None) -> int:
    """Write `site/data/explorer/index.js` and one file per event; returns the number of events.

    Needs the telemetry cache (`cache_dir`, default the repository's). An event that fails is
    listed in the index with the reason, so the page can show it; if every event fails the
    build stops, since that means the cache is missing rather than one bad event.
    """
    processed_dir, site_dir = Path(processed_dir), Path(site_dir)
    out = site_dir / "data" / "explorer"
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(processed_dir), str(cache_dir) if cache_dir else None) for p in sorted((processed_dir / "events").glob("*.json"))]
    index: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for key, idx, detail in pool.map(_job, jobs):
            if idx is None:
                failed.append(detail)
                log.warning("explorer: %s failed: %s", key, detail["error"])
                continue
            index.append(idx)
            (out / f"{key}.js").write_text(js_assign("EXPLORER", detail, key=key), encoding="utf-8")
    if jobs and not index:
        raise RuntimeError(f"per-track data failed for every event (first: {failed[0]['error']}); is the telemetry cache there?")
    index.sort(key=lambda e: (e["season"], e["round"]))
    failed.sort(key=lambda e: (e["season"], e["round"]))
    seasons = sorted({e["season"] for e in index})
    drivers = {str(y): sorted({d for e in index if e["season"] == y for d in e["timing"]}) for y in seasons}
    names = {d: n for e in index for d, n in e.pop("names").items()}
    # Six decimals: the page adds and differences these, then rounds once for display
    (out / "index.js").write_text(js_assign("EXPLORER_INDEX", {
        "team": target, "events": index, "drivers": drivers, "names": names, "failed": failed,
        "class_thresholds_kmh": [LOW_SPEED_MAX_KMH, HIGH_SPEED_MIN_KMH],
    }, nd=6), encoding="utf-8")
    return len(index)
