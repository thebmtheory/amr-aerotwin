"""Generate the technical note (Markdown) from season.json, so every number in it is current."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TARGET = "Aston Martin"
README_BLOCKS = ("findings", "gates")


def _f(x: Any, d: int = 1) -> str:
    """Fixed decimals with a typographic minus; 'n/a' for missing values."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if v != v:
        return "n/a"
    out = f"{v:.{d}f}"
    return "−" + out[1:] if out.startswith("-") and any(c not in "-0." for c in out) else out.lstrip("-")


def _pm(x: Any, d: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{d}f}"


def _sec(rates: dict[str, Any], season: str, team: str, name: str) -> dict[str, float]:
    r = rates.get(season, {}).get(team, {})
    if name not in r.get("sections", []):
        return {}
    i = r["sections"].index(name)
    return {"v": r["rate_pct"][i], "lo": r["ci_lo"][i], "hi": r["ci_hi"][i]}


def _others(rates: dict[str, Any], season: str, off_pace: bool = False) -> dict[str, dict[str, Any]]:
    """Other teams with five or more events; off_pace keeps those at least 1% off pole over a
    lap, where the straights-to-corners ratio is stable (near the front its denominator is ~0)."""
    return {t: v for t, v in rates.get(season, {}).items()
            if t != TARGET and v.get("n_events", 0) >= 5 and (not off_pace or v.get("lap_rate_pct", 0) >= 1)}


def build_note(season_json: Path, out_md: Path) -> Path:
    s = json.loads(Path(season_json).read_text())
    rates = s.get("section_rates", {})

    def sec(season: str, team: str, name: str) -> dict[str, float]:
        return _sec(rates, season, team, name)

    def others(season: str, off_pace: bool = False) -> list[dict[str, Any]]:
        return list(_others(rates, season, off_pace).values())

    a26, a25, cad = rates.get("2026", {}).get(TARGET, {}), rates.get("2025", {}).get(TARGET, {}), rates.get("2026", {}).get("Cadillac", {})
    st26, cad_st = sec("2026", TARGET, "straights"), sec("2026", "Cadillac", "straights")
    o_st = [sec("2026", t, "straights")["v"] for t, v in rates.get("2026", {}).items() if v in others("2026")]
    o_ratio = [v["straight_to_corner_ratio"] for v in others("2026", off_pace=True)]
    vf = s.get("straight_vs_field", {}).get("2026", {})
    fer, fer_st = rates.get("2026", {}).get("Ferrari", {}), sec("2026", "Ferrari", "straights")
    sp26 = s.get("straight_profile", {}).get("2026", {}).get(TARGET, {})
    sp25 = s.get("straight_profile", {}).get("2025", {}).get(TARGET, {})
    b0 = (sp26.get("bins") or [{}])[0]
    ds = s.get("deficit_summary", {}).get("2026", {})
    ds25 = s.get("deficit_summary", {}).get("2025", {})
    up = next((u for u in s.get("upgrade_components", []) if u["season"] == 2026), None)
    cp = s["changepoints"].get("2026", {})
    vs = s["variance_split"]
    cm = s["corner_model"]
    mm = {m["model"]: m for m in cm["metrics"]}
    dq = s["data_quality"]
    did = s.get("upgrades", {}).get("effects", [])
    wt = s.get("wind_rotation_test") or {}

    def ci(v: Any, d: int = 1) -> str:
        return f"{_f(v[0], d)} to {_f(v[1], d)}" if v else "n/a"

    lines = [
        "# Where Aston Martin loses time: technical note",
        "",
        "*Generated from `data/processed/season.json` by `aerotwin report`. Public data only; not affiliated with Aston Martin Aramco F1 Team. "
        "Intervals are 90% bootstrap intervals over events unless stated.*",
        "",
        "## Findings",
        "",
        f"1. **In 2026 Aston Martin loses time on the straights at about twice the rate of any other team.** Loss rate = time lost to the pole lap "
        f"in a section ÷ the pole lap's time there, summed over events. Aston Martin's 2026 straight-line rate is {_f(st26.get('v'), 2)}% "
        f"[{_f(st26.get('lo'), 2)}, {_f(st26.get('hi'), 2)}] against {_f(a26.get('corner_rate_pct'), 2)}% in the corners, a ratio of "
        f"{_f(a26.get('straight_to_corner_ratio'), 2)} [{ci(a26.get('straight_to_corner_ci90'), 2)}]. Every other team's straight-line rate is between "
        f"{_f(min(o_st), 2)}% and {_f(max(o_st), 2)}%; Aston Martin's is {_f(vf.get('ratio'), 2)} times the highest of them ({vf.get('next_team', 'n/a')}) "
        f"[{ci(vf.get('ratio_ci90'), 2)}, the maximum over rivals taken inside each bootstrap draw], so \"twice\" is the central estimate, not a lower bound "
        f"({_f(100 * (vf.get('p_ratio_above_2') or 0), 0)}% of bootstrap draws exceed 2). Teams at least 1% off pole over a lap have straights-to-corners ratios between "
        f"{_f(min(o_ratio), 2)} and {_f(max(o_ratio), 2)}. Cadillac, as slow over a lap "
        f"({_f(cad.get('lap_rate_pct'), 2)}% vs {_f(a26.get('lap_rate_pct'), 2)}%), loses {_f(cad_st.get('v'), 2)}% on the straights. Nearer the front the ratio is unstable "
        f"because the corner deficit is close to zero; Ferrari is the one front-runner that loses more on the straights ({_f(fer_st.get('v'), 2)}%) than in the corners "
        f"({_f(fer.get('corner_rate_pct'), 2)}%), at a much lower level than Aston Martin. In 2025 Aston Martin's ratio was "
        f"{_f(a25.get('straight_to_corner_ratio'), 2)} [{ci(a25.get('straight_to_corner_ci90'), 2)}], in line with the field. Raw seconds by corner type are misleading "
        "here: cars spend the most time in slow corners, so slow corners carry the most seconds for almost every team.",
        f"2. **Where on the straight.** Compared piece by piece along the main straights (those clear of the timing line), Aston Martin starts {_f(-(b0.get('gap_kmh') or 0), 1)} km/h "
        f"down, holds that through the first half ({_pm(sp26.get('first_half_kmh'), 1)} km/h [{ci(sp26.get('first_half_ci90'))}]) and loses {_f(-(sp26.get('second_half_kmh') or 0), 1)} km/h more "
        f"in the second half [{ci(sp26.get('second_half_ci90'))}], at full throttle, on {sp26.get('n_straights_losing_late')} of {sp26.get('n_straights')} straights at {sp26.get('n_events')} events. "
        "The shape does not identify the cause: a point-mass simulation reproduces it with extra drag alone, and energy deployment ending earlier or harvesting at "
        "full throttle fit it as well. "
        f"The 2025 car shows no growth ({_pm(sp25.get('growth_kmh'), 1)} km/h [{ci(sp25.get('growth_ci90'))}]). Main straights cost {_f(sp26.get('time_total_s'), 2)} s per lap "
        f"[{ci(sp26.get('time_total_ci90'), 2)}] in 2026.",
        "3. **Power vs drag is not identifiable from public timing data.** Over one straight the two terms are collinear; fits need at least 200 m of clean straight and a "
        "60 km/h speed range and are reported only where that holds. An earlier version of this project claimed a ~36 kW power deficit; it came from not correcting for "
        "gradient and comparing cars on different stretches of track, and is withdrawn.",
        f"4. **The car decides the 2026 order.** In the median event the between-team share of qualifying-gap variance is {_f(100 * vs['2025']['median_event_share'], 0)}% "
        f"in 2025 and {_f(100 * vs['2026']['median_event_share'], 0)}% in 2026 (laps outside 107% of the best excluded).",
        f"5. **Physics accounting.** Giving the pole car's calibrated simulator Aston Martin's measured grip and top-speed gap accounts for "
        f"{_f(100 * (ds.get('ratio_of_means') or float('nan')), 0)}% of its mean 2026 gap [{_f(100 * (ds.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds.get('ratio_ci90') or [0, float('nan')])[1], 0)}%] over the {ds.get('n_events')} events where the geometry check passes and both teams have grip and top-speed measurements "
        f"(event-level R² {_f(ds.get('r2_event_level'), 2)}). The same accounting for 2025, when the gap is a quarter as large, gives "
        f"{_f(100 * (ds25.get('ratio_of_means') or float('nan')), 0)}% [{_f(100 * (ds25.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds25.get('ratio_ci90') or [0, float('nan')])[1], 0)}%] with event-level R² {_f(ds25.get('r2_event_level'), 1)} over {ds25.get('n_events')} events. "
        "It is an accounting of a large deficit, not a forecast of small ones.",
    ]
    if up:
        gh = up["grip_high_rel"]
        lines.append(
            f"6. **The 2026 Hungary upgrade: suggestive, not established.** A changepoint model not told upgrade dates rates the {cp.get('map_event')} the most likely shift "
            f"(posterior {_f(cp.get('map_probability'), 2)} vs {_f(cp.get('p_no_change'), 2)} for no change), step {_pm(cp.get('effect_pct'), 2)}% [{ci(cp.get('effect_ci90_pct'), 2)}]. "
            f"Fast-corner grip vs the other teams went {_f(100 * gh['before']['mean'], 1)}% → {_f(100 * gh['after']['mean'], 1)}% ({gh['before']['n']} events before, "
            f"{gh['after']['n']} after). The placebo-based test cannot reach p < {_f(min(e['p_floor'] for e in did), 2)} with ten rivals, so it cannot settle this."
        )
    lines += [
        f"7. **Wind is left out, on evidence.** Rotating the wind direction through 360° across {wt.get('n_events', 0)} windy sessions, no orientation improves the "
        f"acceleration fit by more than a few percent and the assumed one was best in {_f(100 * (wt.get('share_events_assumed_orientation_best') or 0), 0)}% of them (chance: 8%). "
        "Session-level wind readings are not informative enough, so dynamic pressure uses ground speed. Earlier wind claims are withdrawn.",
        f"8. **Data note.** Placing car data by GPS position needs a per-lap timing correction in this archive (median {_f(dq['gps_lag_s_median'], 2)} s, about 9 m at 300 km/h); "
        "the archive's odometer distance is unaffected. Frozen car-data stretches (e.g. Baku 2026), car-data stalls (speed, throttle and brake held for 0.5–1.5 s "
        "while GPS shows the car braking, then an impossible jump) and the feed's 104% throttle marker are detected and handled.",
        "",
        "## Data",
        "",
        f"Fastest valid qualifying lap of every driver at {s['n_events']} Grands Prix (2025 and 2026 to date), plus every lap of each race, from the public "
        "TracingInsights archive of F1 live timing. Car data (speed, throttle, brake, gear, rpm) arrives at roughly 4–10 Hz and GPS at about 4 Hz. "
        f"{dq['laps_passed']} of {dq['laps_total']} laps pass the automated data checks. Excluded events and reasons are listed in the report. "
        "Regulation figures (minimum mass, MGU-K taper) and Aston Martin's declared upgrades come from FIA documents (data/reference/SOURCES.md).",
        "",
        "## Method",
        "",
        "1. **Alignment.** Each lap is projected onto the pole lap's path. The archive linearly interpolates GPS onto car-data timestamps; original fixes are "
        f"identified (whole-decimetre coordinates) and the clock offset between the GPS and car-data streams (median {_f(dq['gps_lag_s_median'], 2)} s) is estimated per lap "
        "by matching GPS-derived speed to wheel speed. Time comes from the measured timing channel, pinned to zero at the line and the official lap time at the end.",
        "2. **Geometry.** Curvature is a smoothing spline of x(t), y(t) through raw fixes (time-domain, so position noise does not scale with speed), with the "
        "smoothing level chosen per event by the GPS-speed cross-check, then the median across all drivers. Integrated curvature must match the circuit's turn count "
        "(one for most circuits, zero for figure-of-eight Suzuka).",
        "3. **Lap simulator.** Quasi-steady point mass: grip μ(g + qC<sub>L</sub>A/m) on a friction ellipse, power limit, drag and rolling resistance, closed-lap "
        "forward/backward passes. Calibrated to each measured lap by MAP with weak log-normal priors; Laplace posterior with an AR(1) effective sample size; "
        "checked against a Metropolis sampler; a Gaussian process on the residual shows where point-mass physics fails.",
        "4. **Grip.** One near-limit point per corner (flat-out corners excluded) gives a line of limit acceleration against dynamic pressure; it is read only at "
        "two event-wide reference pressures because tyre load sensitivity makes absolute μ and C<sub>L</sub>A unidentifiable from public data.",
        "5. **Straights.** Main straights from the pole lap are split into ten equal pieces; each team's speed in each piece is compared with the other teams' median. "
        "Joint power and drag fits use the acceleration phase only (up to the field-median peak), gravity removed with GPS altitude, tow-free samples, 2026 speeds below the MGU-K taper.",
        "6. **Corner model.** Minimum corner speed at unseen circuits, cross-validated by whole circuit. Physics baseline: the lap simulator on the held-out track with a "
        "nominal car from the training events' calibrations only. Hybrid: gradient boosting on its residual. Split-conformal intervals; exact baseline Shapley values of the reported model.",
        "7. **Race pace.** Fixed effects for driver, compound and per-compound tyre degradation plus a fuel term per lap on green-flag laps; intervals from a "
        "delete-one-stint jackknife, checked for coverage of the fuel effect and of team gaps with autocorrelated errors.",
        "8. **Season.** Supertime gaps; per-event one-way random-effects variance split; single-changepoint model with exact normal-inverse-gamma evidence, effect averaged "
        "over the changepoint posterior and prior sensitivity reported; upgrade difference-in-differences (team and event fixed effects, team-specific track-type slopes) with "
        "permutation p-values (team and time placebos), Holm adjustment and minimum detectable effect.",
        "",
        "## Validation",
        "",
        "- Automated tests (backend/tests): analytic physics (constant-radius circle, terminal speed, braking distance), parameter recovery and interval coverage on "
        "synthetic data, leakage guards, exact Shapley efficiency, JavaScript–Python simulator parity, and an end-to-end run on real Silverstone data.",
        f"- Corner model, out of sample by whole circuit: steady-state formula R² {_f(mm.get('steady', {}).get('r2'), 2)}, lap sim on GPS geometry alone R² {_f(mm['physics']['r2'], 2)}, "
        f"gradient boosting R² {_f(mm['ml']['r2'], 2)}, hybrid R² {_f(mm['hybrid']['r2'], 2)} (RMSE {_f(mm['hybrid']['rmse_kmh'], 1)} km/h); within-corner R² ≈ 0 for all models. "
        f"Conformal coverage {_f(100 * cm['conformal_coverage'], 1)}% at a 90% target (median event {_f(100 * cm['coverage_by_event']['median'], 0)}%, worst {_f(100 * cm['coverage_by_event']['min'], 0)}%).",
        f"- Lap-sim accounting of the 2026 gap: {_f(100 * ds.get('ratio_of_means', float('nan')), 0)}% of the mean gap [{_f(100 * (ds.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds.get('ratio_ci90') or [0, float('nan')])[1], 0)}%], correlation across its {ds.get('n_events')} events r = {_f(ds.get('correlation'), 2)} "
        f"(Spearman {_f(ds.get('spearman'), 2)}), event-level R² {_f(ds.get('r2_event_level'), 2)}; in 2025, R² {_f(ds25.get('r2_event_level'), 1)}. "
        "With five events this is an accounting, not a forecast.",
        "- Upgrade effects (difference-in-differences, 4 events either side):",
    ]
    for e in did:
        lines.append(f"  - {e['season']} {e['event']}: {_pm(e['effect_pct'], 2)}% (detectable ≥ {_f(e['mde_pct'], 2)}%; team placebo p = {_f(e['team_placebo_p'], 2)}, "
                     f"Holm-adjusted {_f(e['team_placebo_p_holm'], 2)}; time placebo p = {_f(e['time_placebo_p'], 2)}; {e['n_pre']}/{e['n_post']} events)")
    lines += [
        "",
        "## Limitations",
        "",
        "- Public telemetry has no ride heights, suspension, tyre temperatures, fuel loads or ERS state. Grip and aero figures are effective point-mass values.",
        "- Energy deployment is inferred from speed; the ERS state is not published, so the late-straight loss could also reflect harvesting strategy or top-end drag in active-aero straight mode.",
        "- Laps are set at different times in a session (a car knocked out in Q1 sets its best lap on a greener track than pole). Track evolution mostly adds grip, so it inflates corner loss rates more than straight-line ones.",
        "- Upgrade windows are short (four events) and tracks differ; placebo tests guard against chance but not against every confounder. "
        "Overlapping windows (Hungary and Dutch GP 2026) are not independent.",
        "- Mass is the regulation minimum plus an assumed 5 kg of qualifying fuel; a 2 kg error moves C<sub>L</sub>A estimates by about 0.25%.",
        "",
        "## What this would look like with team data",
        "",
        "With ERS state-of-charge, MGU-K torque and engine maps, the power-equivalent deficit could be split into ICE output, deployment strategy and harvesting losses. "
        "With ride-height and aero-map data, the grip-vs-dynamic-pressure line becomes a direct track-to-tunnel correlation check. "
        "The calibration and discrepancy framework is built so that higher-fidelity simulation outputs can replace the point-mass model without changing the rest of the pipeline.",
        "",
    ]
    out_md = Path(out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def readme_blocks(s: dict[str, Any]) -> dict[str, str]:
    """The README paragraphs that quote results, generated so they cannot drift from season.json."""
    rates = s.get("section_rates", {})
    a26, a25 = rates.get("2026", {}).get(TARGET, {}), rates.get("2025", {}).get(TARGET, {})
    st26 = _sec(rates, "2026", TARGET, "straights")
    vf = s.get("straight_vs_field", {}).get("2026", {})
    nxt = vf.get("next_team", "n/a")
    nxt_lap = rates.get("2026", {}).get(nxt, {}).get("lap_rate_pct")
    off = _others(rates, "2026", off_pace=True)
    ratios = [v["straight_to_corner_ratio"] for v in off.values()]
    sp26 = s.get("straight_profile", {}).get("2026", {}).get(TARGET, {})
    b0 = (sp26.get("bins") or [{}])[0]
    vs = s["variance_split"]
    findings = "\n".join([
        "- **In 2026 Aston Martin loses time on the straights at about twice the rate of any other team.** Measured as time lost to the pole lap per second spent "
        f"in each part of the lap, it loses {_f(st26.get('v'), 1)}% on the straights against at most {_f(vf.get('next_rate_pct'), 1)}% for any other team ({nxt}, "
        f"{_f(nxt_lap, 2)}% off pole over a lap against Aston Martin's {_f(a26.get('lap_rate_pct'), 2)}%): {_f(vf.get('ratio'), 1)} times as much, 90% interval "
        f"{_f((vf.get('ratio_ci90') or [None])[0], 1)} to {_f((vf.get('ratio_ci90') or [None, None])[1], 1)}. Every other team more than 1% off pole loses less per second "
        f"on the straights than in the corners (ratios {_f(min(ratios), 2)} to {_f(max(ratios), 2)}, against {_f(a26.get('straight_to_corner_ratio'), 2)} for Aston Martin), "
        f"as did Aston Martin in 2025 ({_f(a25.get('straight_to_corner_ratio'), 2)}).",
        f"- **The straight-line loss builds late.** Along each main straight the car starts {_f(-(b0.get('gap_kmh') or 0), 1)} km/h down, holds that through the first half "
        f"and loses {_f(-(sp26.get('second_half_kmh') or 0), 1)} km/h more in the second half (90% interval {_f(-(sp26.get('second_half_ci90') or [0, 0])[1], 1)} to "
        f"{_f(-(sp26.get('second_half_ci90') or [0, 0])[0], 1)}), at full throttle, on {sp26.get('n_straights_losing_late')} of {sp26.get('n_straights')} straights at "
        f"{sp26.get('n_events')} events. Extra drag, deployment ending earlier and harvesting at full throttle all fit that shape; public timing data cannot tell them apart.",
        f"- **The car decides the 2026 qualifying order:** in the median event, between-team differences explain {_f(100 * vs['2026']['median_event_share'], 0)}% of the "
        f"variance in qualifying gaps, against {_f(100 * vs['2025']['median_event_share'], 0)}% in 2025.",
        "- **What did not survive review is withdrawn, not hidden.** An early 36 kW power-deficit claim (an artefact of road gradient and unlike-for-like comparison), "
        "a \"slow corners are the biggest loss\" claim (cars simply spend most time there) and two wind claims (wind data proved uninformative) are documented as "
        "withdrawn in the technical note.",
    ])
    dq = s["data_quality"]
    skipped = s.get("skipped_events", [])
    gaps = [f"{e['event'].replace(' Grand Prix', '')} {e['season']}" for e in skipped if "passed checks" in e.get("reason", "")]
    missing = [f"{e['event'].replace(' Grand Prix', '')} {e['season']}" for e in skipped if "unavailable" in e.get("reason", "")]
    other = [e for e in skipped if "passed checks" not in e.get("reason", "") and "unavailable" not in e.get("reason", "")]
    gates = (
        "Every lap is checked against limits that real broken laps fail: GPS distance to the reference line, GPS position vs the timing line at both ends, "
        "consistency of speed with the timing channel, GPS speed vs wheel speed, sample gaps, speed trap vs peak speed, frozen car data (speed and rpm stuck for over "
        "100 m, as on both Aston Martins at Baku 2026) and car-data stalls (speed, throttle and brake held for 0.5–1.5 s while GPS shows the car braking, then a "
        "jump no car can make). The feed's 104% \"invalid throttle\" marker is repaired rather than rejected. Every event's curvature must integrate to the "
        f"circuit's own turn count (zero for the figure-of-eight at Suzuka). {dq['laps_passed']} of {dq['laps_total']} laps pass. Events that fail are listed with "
        "reasons in the report"
        + (f"; {len(gaps)} ({', '.join(gaps)}) have too few laps that pass, because of telemetry dropouts" if gaps else "")
        + (f", and {len(missing)} ({', '.join(missing)}) have source files missing from the archive" if missing else "")
        + (f"; {len(other)} more fail for other reasons" if other else "")
        + "."
    )
    return {"findings": findings, "gates": gates}


def update_readme(season_json: Path, readme: Path) -> bool:
    """Rewrite the generated blocks of the README in place; True if anything changed."""
    s = json.loads(Path(season_json).read_text())
    text = Path(readme).read_text(encoding="utf-8")
    new = text
    for name, body in readme_blocks(s).items():
        start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
        i, j = new.find(start), new.find(end)
        if i < 0 or j < i:
            raise ValueError(f"README is missing the {start} ... {end} markers")
        new = new[: i + len(start)] + "\n" + body + "\n" + new[j:]
    if new != text:
        Path(readme).write_text(new, encoding="utf-8")
    return new != text
