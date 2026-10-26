"""One circuit, every team: the data behind a single-event report.

Team results use each team's fastest lap that passed the data checks (the laps behind the
season tables) and the fastest clean lap as the common reference. Section and corner times
come from the timing channel on a shared distance grid, so they add up to the official gap.
Two things need the aligned laps themselves and are read offline from the telemetry cache:
corner minimum speeds, each checked against GPS-derived speed, and speed and throttle along
the straights.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from amr_aerotwin.data.repository import TelemetryRepository
from amr_aerotwin.domain import TARGET_TEAM, AlignedLap
from amr_aerotwin.modeling.lap_compare import compare_laps, cumulative_gap, segment_time_loss
from amr_aerotwin.modeling.validation import check_lap
from amr_aerotwin.physics.dynamics import VehicleState, estimate_vehicle_state, lap_curvature
from amr_aerotwin.physics.kinematics import consensus_curvature, corner_windows, gps_spline_kinematics
from amr_aerotwin.physics.vehicle_params import straight_segments
from amr_aerotwin.pipeline.event import _load_quali_laps, _r
from amr_aerotwin.pipeline.season import PROCESSED_DIR, UPGRADES_CSV, load_tables
from amr_aerotwin.report.build import _clean

STATIC = Path(__file__).parent / "static"
SECTIONS = ["straights", "high", "medium", "low"]
CORNER_WINDOW_M = 60.0
# A corner's minimum speed is reported only when the wheel-speed channel and GPS-derived
# speed agree on it. The smoothed GPS path reads low in fast corners for every car, so each
# car's wheel-minus-GPS difference is compared with the field's median at that corner; a
# stuck or stepping speed channel (2026 British GP: STR at Aintree) misses by 20 km/h or more.
# On the clean laps at Silverstone the residual stays within +-14 km/h.
WHEEL_GPS_TOL_KMH = 15.0
FULL_THROTTLE_PCT = 98.0
TRACE_STEP = 2  # export every 2nd 5 m grid point

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


def slug(event: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", event.lower()).strip("-")


def corner_min_speeds(state: VehicleState, corner_s: np.ndarray) -> list[dict[str, float]]:
    """Minimum speed in +-60 m of each corner from the wheel-speed channel and from GPS.

    GPS speed comes from the same time-domain spline of raw fixes used for curvature, so it
    is independent of the car-data stream. See `flag_corner_speeds` for the check.
    """
    lap = state.lap
    out = []
    # Disjoint windows: two corners closer than 120 m (Vale, T16-T17) do not share a minimum
    for win in corner_windows(lap.distance_m, corner_s, lap.lap_length_m, CORNER_WINDOW_M):
        v_wheel = float(np.min(state.speed_smooth_ms[win]) * 3.6)
        if len(lap.gps_time_s) > 50:
            _, v_gps = gps_spline_kinematics(lap.gps_time_s, lap.gps_x_m, lap.gps_y_m, lap.meta.lap_time_s, lap.time_s[win])
            g = float(np.min(v_gps) * 3.6)
        else:
            g = float("nan")
        out.append({"wheel_kmh": v_wheel, "gps_kmh": g})
    return out


def flag_corner_speeds(vmin: dict[str, list[dict[str, float]]]) -> None:
    """Set `ok` on every (car, corner): wheel-minus-GPS within WHEEL_GPS_TOL_KMH of the field median."""
    n = len(next(iter(vmin.values())))
    for i in range(n):
        diffs = {t: v[i]["wheel_kmh"] - v[i]["gps_kmh"] for t, v in vmin.items()}
        med = float(np.nanmedian(list(diffs.values())))
        for t, v in vmin.items():
            v[i]["residual_kmh"] = diffs[t] - med
            v[i]["ok"] = bool(np.isfinite(diffs[t]) and abs(diffs[t] - med) <= WHEEL_GPS_TOL_KMH)


def full_throttle_speed_loss(v_kmh: np.ndarray, throttle: np.ndarray) -> float:
    """Largest drop below the running peak speed while still at full throttle (km/h).

    At constant drive power a car below its terminal speed can only accelerate, so speed
    falling at full throttle on a level straight means drive power fell (energy deployment
    ended or the car is harvesting); drag or gradient alone would show as a flattening, not
    a fall, and gradient is shared by every car on the same piece of track.
    """
    peak = np.maximum.accumulate(v_kmh)
    drop = np.where(throttle >= FULL_THROTTLE_PCT, peak - v_kmh, 0.0)
    return float(np.max(drop)) if len(drop) else float("nan")


def _team_best(team_table: list[dict[str, Any]]) -> dict[str, str]:
    return {r["team"]: r["best_driver"] for r in team_table}


def season_block(
    year: int,
    event: str,
    ev: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    season: dict[str, Any],
    upgrades: pd.DataFrame,
    repo: TelemetryRepository,
    target: str = TARGET_TEAM,
) -> dict[str, Any]:
    """Everything the report shows for one season of one event."""
    laps, ref, _, _ = _load_quali_laps(repo, year, event)
    best = _team_best(ev["team_table"])
    pole_drv = ev["pole"]["driver"]
    pole_team = ev["pole"]["team"]
    # Gaps are to the fastest lap of the session, which is the Q3 pole at every event bar one
    # (2025 Hungary: a Q2 lap); `pole.is_pole` says which it is
    fl = ev.get("fastest_lap") or ev["official_pole"]
    pole_time = float(fl["lap_time_s"])
    is_pole = bool(ev.get("official_pole") and fl["driver"] == ev["official_pole"]["driver"] and fl.get("segment", "Q3") == "Q3")
    # Same curvature as the event build: consensus over every lap that passed the checks
    kappa = consensus_curvature([lap_curvature(lp, ev["gps_smoothing_lam"]) for lp in laps.values() if check_lap(lp).passed])
    states = {t: estimate_vehicle_state(laps[d], curvature_inv_m=kappa) for t, d in best.items()}
    pole_lap: AlignedLap = laps[pole_drv]
    corner_s = np.asarray(ev["corners"]["distance_m"], dtype=float)
    labels = list(ev["corners"]["label"])
    circuit = (ev.get("circuit") or {}).get("circuit_name", "")
    names = CORNER_NAMES.get(circuit, {})

    # Qualifying order (official timing for every driver, team = its faster driver)
    timing = tables["timing"]
    timing = timing[(timing["season"] == year) & (timing["event"] == event)]
    order = []
    for team, g in timing.groupby("team"):
        g = g.sort_values("lap_time_s")
        order.append({"team": team, "driver": g["driver"].iloc[0], "lap_time_s": float(g["lap_time_s"].iloc[0]),
                      "teammate": g["driver"].iloc[1] if len(g) > 1 else None,
                      "teammate_time_s": float(g["lap_time_s"].iloc[1]) if len(g) > 1 else None})
    order.sort(key=lambda r: r["lap_time_s"])
    for i, r in enumerate(order):
        r["position"] = i + 1
        r["gap_s"] = r["lap_time_s"] - pole_time
        r["gap_pct"] = 100 * (r["lap_time_s"] / pole_time - 1)
        r["telemetry_driver"] = best.get(r["team"])
    pos = {r["team"]: r["position"] for r in order}
    tgt_pos = pos.get(target)
    # The team directly ahead that has a lap with usable telemetry (its trace is drawn)
    ahead = [r["team"] for r in order if tgt_pos and r["position"] < tgt_pos and r["team"] in best]
    rival = ahead[-1] if ahead else None

    # Sections and corners: each team's best lap against the pole lap
    sections, corner_time = {}, {}
    for team, d in best.items():
        if d == pole_drv:
            sections[team] = {s: 0.0 for s in SECTIONS}
            corner_time[team] = [0.0] * len(labels)
            continue
        cmp = compare_laps(laps[d], pole_lap, corner_s, labels)
        cs = cmp.class_summary.set_index("speed_class")
        sections[team] = {s: float(cs.loc[s, "time_s"]) for s in SECTIONS}
        ct = cmp.corner_table.set_index("corner")
        corner_time[team] = [float(ct.loc[lab, "total_s"]) for lab in labels]
    cmp_ref = compare_laps(laps[best[target]], pole_lap, corner_s, labels) if target in best else None
    ref_time = {s: float(cmp_ref.class_summary.set_index("speed_class").loc[s, "reference_time_s"]) for s in SECTIONS} if cmp_ref else {}
    rates = {t: {s: 100 * v[s] / ref_time[s] for s in SECTIONS} for t, v in sections.items()} if ref_time else {}

    # Corner minimum speeds, every team's best lap, checked against GPS
    vmin = {t: corner_min_speeds(st, corner_s) for t, st in states.items()}
    flag_corner_speeds(vmin)
    corners = []
    for i, lab in enumerate(labels):
        others = [vmin[t][i]["wheel_kmh"] for t in vmin if t != target and vmin[t][i]["ok"]]
        tv = vmin.get(target, [{}] * len(labels))[i]
        pv = vmin[pole_team][i]
        corners.append({
            "label": lab, "name": names.get(lab, ""), "distance_m": float(corner_s[i]),
            "speed_class": cmp_ref.corner_table["speed_class"].iloc[i] if cmp_ref else None,
            "pole_kmh": pv["wheel_kmh"], "field_median_kmh": float(np.median(others)) if others else None,
            "target_kmh": tv.get("wheel_kmh"), "target_gps_kmh": tv.get("gps_kmh"), "target_ok": tv.get("ok"),
            "target_time_s": float(cmp_ref.corner_table["total_s"].iloc[i]) if cmp_ref else None,
            "target_entry_s": float(cmp_ref.corner_table["entry_s"].iloc[i]) if cmp_ref else None,
            "target_apex_s": float(cmp_ref.corner_table["apex_s"].iloc[i]) if cmp_ref else None,
            "target_exit_s": float(cmp_ref.corner_table["exit_s"].iloc[i]) if cmp_ref else None,
            "n_flagged": int(sum(not vmin[t][i]["ok"] for t in vmin)),
        })
    flagged = [{"team": t, "driver": best[t], "corner": labels[i], "name": names.get(labels[i], ""), "wheel_kmh": v["wheel_kmh"],
                "gps_kmh": v["gps_kmh"], "residual_kmh": v["residual_kmh"]}
               for t in vmin for i, v in enumerate(vmin[t]) if not v["ok"]]

    # Traces: target vs pole and vs the team directly ahead
    def trace(team: str) -> dict[str, Any]:
        lap = laps[best[team]]
        st = states[team]
        return {"team": team, "driver": best[team], "speed_kmh": st.speed_smooth_ms[::TRACE_STEP] * 3.6,
                "throttle": lap.throttle_pct[::TRACE_STEP], "brake": lap.brake[::TRACE_STEP],
                "delta_s": cumulative_gap(segment_time_loss(lap, pole_lap))[::TRACE_STEP] if best[team] != pole_drv else np.zeros(len(lap.distance_m))[::TRACE_STEP]}

    traces = {"distance_m": pole_lap.distance_m[::TRACE_STEP], "pole": trace(pole_team)}
    if target in best:
        traces["target"] = trace(target)
    if rival:
        traces["rival"] = trace(rival)

    # Track map coloured by where the target loses time (s per 100 m, centred window)
    track = {"x": ref.x_m[::TRACE_STEP], "y": ref.y_m[::TRACE_STEP]}
    if target in best:
        cell = segment_time_loss(laps[best[target]], pole_lap)
        k = int(round(100.0 / ref.step_m))
        loss_100 = np.convolve(np.concatenate([cell[-k:], cell, cell[:k]]), np.ones(k), mode="same")[k:-k]
        track["target_loss_s_per_100m"] = loss_100[::TRACE_STEP]

    # Straights: the pole lap's full-throttle runs of 400 m or more, every team's best lap
    straights = []
    for k, seg in enumerate(straight_segments(states[pole_team], min_length_m=400.0, trim_m=0.0, drop_line_cut=True)):
        lo, hi = int(seg[0]), int(min(seg[-1] + 4, len(pole_lap.distance_m) - 1))  # +20 m past the pole's lift
        sl = slice(lo, hi + 1)
        teams = {}
        for t, st in states.items():
            v = st.speed_smooth_ms[sl] * 3.6
            thr = st.lap.throttle_pct[sl]
            teams[t] = {"speed_kmh": v[::2], "throttle": thr[::2],
                        "full_throttle_share": float(np.mean(thr >= FULL_THROTTLE_PCT)),
                        "full_throttle_loss_kmh": full_throttle_speed_loss(v, thr),
                        "entry_kmh": float(v[0]), "peak_kmh": float(np.max(v)), "end_kmh": float(v[-1])}
        before = [lab for lab, cs in zip(labels, corner_s) if cs < pole_lap.distance_m[lo]]
        after = before[-1] if before else labels[-1]
        straights.append({"index": k, "start_m": float(pole_lap.distance_m[lo]), "end_m": float(pole_lap.distance_m[hi]),
                          "after_corner": after, "name": STRAIGHT_NAMES.get(circuit, {}).get(after, f"Straight after {after}"),
                          "distance_m": pole_lap.distance_m[sl][::2], "teams": teams})

    # Grip and straight-line speed from the event build
    grip = [{k: r[k] for k in ("team", "grip_low_g", "grip_low_lo", "grip_low_hi", "grip_high_g", "grip_high_lo",
                               "grip_high_hi", "straight_speed_delta_kmh")} for r in ev["team_table"]]

    declared = upgrades[(upgrades["season"] == year) & (upgrades["grand_prix"] == event)].to_dict("records")
    did = next((u for u in season.get("upgrades", {}).get("effects", []) if u["season"] == year and u["event"] == event), None)

    return {
        "season": year, "round": ev["round"], "date": ev["date"], "circuit": circuit,
        "lap_length_m": ev["lap_length_m"], "regulations": ev["regulations"], "track": ev["track"],
        "pole": {"driver": fl["driver"], "team": fl["team"], "lap_time_s": pole_time, "is_pole": is_pole, "segment": fl.get("segment")},
        "reference_driver": pole_drv, "n_laps": ev["n_laps"], "n_passed": ev["n_passed"], "warnings": ev["warnings"],
        "order": order, "target_position": tgt_pos, "n_teams": len(order), "rival": rival,
        "sections": sections, "section_rates": rates, "reference_section_time_s": ref_time,
        "corners": corners, "corner_time_s": corner_time, "flagged_corner_speeds": flagged,
        "traces": traces, "track_map": track, "straights": straights, "grip": grip,
        "race_pace": ev.get("race_pace"),
        "declared_upgrades": declared,
        "upgrade_test": {k: did[k] for k in ("effect_pct", "team_placebo_p", "time_placebo_p", "p_floor", "mde_pct",
                                              "n_pre", "n_post", "team_placebo_p_holm")} if did else None,
    }


def season_context(tables: dict[str, pd.DataFrame], target: str = TARGET_TEAM) -> list[dict[str, Any]]:
    """Target's qualifying gap and team position at every event, from the official timing."""
    t = tables["timing"]
    best_all = t.groupby(["season", "round"])["lap_time_s"].transform("min")
    t = t.assign(gap_pct=100 * (t["lap_time_s"] / best_all - 1))
    team_best = t.groupby(["season", "round", "event", "team"], as_index=False)["gap_pct"].min()
    team_best["position"] = team_best.groupby(["season", "round"])["gap_pct"].rank(method="min").astype(int)
    team_best["n_teams"] = team_best.groupby(["season", "round"])["team"].transform("size")
    tr = tables["teams"][["season", "round", "track_x"]]
    out = team_best[team_best["team"] == target].merge(tr.drop_duplicates(["season", "round"]), on=["season", "round"], how="left")
    return out.sort_values(["season", "round"]).to_dict("records")


def event_report_data(
    event: str,
    seasons: tuple[int, ...] = (2025, 2026),
    processed_dir: Path = PROCESSED_DIR,
    repo: TelemetryRepository | None = None,
    target: str = TARGET_TEAM,
) -> dict[str, Any]:
    repo = repo or TelemetryRepository()
    tables = load_tables(processed_dir)
    season = json.loads((processed_dir / "season.json").read_text())
    upgrades = pd.read_csv(UPGRADES_CSV) if UPGRADES_CSV.exists() else pd.DataFrame(columns=["season", "grand_prix"])
    blocks = {}
    for year in seasons:
        p = processed_dir / "events" / f"{year}-{slug(event)}.json"
        if p.exists():
            blocks[str(year)] = season_block(year, event, json.loads(p.read_text()), tables, season, upgrades, repo, target)
    return {"event": event, "target": target, "seasons": blocks, "context": season_context(tables, target),
            "season_rates": {y: season.get("section_rates", {}).get(y, {}).get(target) for y in blocks}}


def report_events(reports_dir: Path, processed_dir: Path = PROCESSED_DIR) -> list[str]:
    """Events that already have a report page in `reports_dir` (by slug), from the calendar."""
    cal = processed_dir / "calendar.csv"
    if not Path(reports_dir).is_dir() or not cal.exists():
        return []
    have = {f.stem for f in Path(reports_dir).glob("*.html")}
    return sorted({e for e in pd.read_csv(cal)["event"].astype(str) if slug(e) in have})


def render_event_report(data: dict[str, Any]) -> str:
    """The page body (title, styles, markup, scripts) with the data embedded."""
    page = (STATIC / "event_report.html").read_text(encoding="utf-8")
    payload = json.dumps(_clean(_r(data, 4)), separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return page.replace("/*REPORT_DATA*/null", payload)


def build_event_report(event: str, out_dir: Path, processed_dir: Path = PROCESSED_DIR, repo: TelemetryRepository | None = None) -> Path:
    """Write `<out_dir>/<event-slug>.html`, a standalone page that works from file://."""
    body = render_event_report(event_report_data(event, processed_dir=processed_dir, repo=repo))
    head, sep, rest = body.partition("</style>")
    doc = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
           f"{head}{sep}\n</head>\n<body>\n{rest}\n</body>\n</html>\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug(event)}.html"
    out.write_text(doc, encoding="utf-8")
    return out
