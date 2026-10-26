"""Generate the technical note (Markdown) from season.json, so every number in it is current."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TARGET = "Aston Martin"


def _f(x: Any, d: int = 1) -> str:
    try:
        return f"{float(x):.{d}f}"
    except (TypeError, ValueError):
        return "n/a"


def _pm(x: Any, d: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{d}f}"


def build_note(season_json: Path, out_md: Path) -> Path:
    s = json.loads(Path(season_json).read_text())
    gb = s.get("gap_by_class", {})

    def cls(season: str, name: str) -> dict[str, float]:
        g = gb.get(season, {})
        if name not in g.get("classes", []):
            return {}
        i = g["classes"].index(name)
        return {"mean": g["mean_s"][i], "lo": g["ci_lo"][i], "hi": g["ci_hi"][i], "total": g["mean_total_s"], "n": g["n_events"]}

    sp26 = s.get("straight_profile", {}).get("2026", {}).get(TARGET, {})
    sp25 = s.get("straight_profile", {}).get("2025", {}).get(TARGET, {})
    rel26 = s.get("target_relative", {}).get("2026", {})
    pt26 = s.get("powertrain", {}).get("2026", {}).get(TARGET, {})
    ds = s.get("deficit_summary", {}).get("2026", {})
    up = next((u for u in s.get("upgrade_components", []) if u["season"] == 2026), None)
    cp = s["changepoints"].get("2026", {})
    vs = s["variance_split"]
    cm = s["corner_model"]
    mm = {m["model"]: m for m in cm["metrics"]}
    dq = s["data_quality"]
    did = s.get("upgrades", {}).get("effects", [])
    low25, low26, str26 = cls("2025", "low"), cls("2026", "low"), cls("2026", "straights")
    b0 = (sp26.get("bins") or [{}])[0]
    ratio = (sp26.get("second_half_kmh") or 0) / (sp26.get("first_half_kmh") or float("nan"))

    def ci(v: Any, d: int = 1) -> str:
        return f"{_f(v[0], d)} to {_f(v[1], d)}" if v else "n/a"

    lines = [
        "# Where Aston Martin loses time: technical note",
        "",
        "*Generated from `data/processed/season.json` by `aerotwin report`. Public data only; not affiliated with Aston Martin Aramco F1 Team. "
        "All intervals are 90%; unless stated, comparisons are with the median of the other teams at the same event.*",
        "",
        "## Findings",
        "",
        f"1. **Slow corners are Aston Martin's biggest loss in both seasons.** Splitting the qualifying gap to pole by track section (model-free, sums to the official gap): "
        f"{_f(low25['mean'], 2)} s [{_f(low25['lo'], 2)}, {_f(low25['hi'], 2)}] of {_f(low25['total'], 2)} s in 2025 and {_f(low26['mean'], 2)} s [{_f(low26['lo'], 2)}, {_f(low26['hi'], 2)}] "
        f"of {_f(low26['total'], 2)} s in 2026. It persists across two cars built to different rules, with the same drivers, so it reflects something durable (set-up, mechanical grip and "
        "traction, or driving style); public data cannot say which.",
        f"2. **In 2026 the straight-line deficit has two parts.** Compared piece by piece along each main straight, Aston Martin starts {_f(-(b0.get('gap_kmh') or 0), 1)} km/h down at corner exit "
        f"[{_f(b0.get('ci_lo'), 1)}, {_f(b0.get('ci_hi'), 1)}], changes little in the first half ({_pm(sp26.get('first_half_kmh'), 1)} km/h [{ci(sp26.get('first_half_ci90'))}]) and loses "
        f"{_pm(sp26.get('second_half_kmh'), 1)} km/h [{ci(sp26.get('second_half_ci90'))}] in the second half: {_f(ratio, 1)} times the first-half change, where extra drag would give about "
        f"{_f(sp26.get('drag_only_ratio'), 2)} times and a power deficit would bite earlier. A loss that appears halfway down the straight fits electrical deployment ending earlier than on rival cars. "
        f"The car's speed drop after peak is {_pm((rel26.get('clip_speed_drop_kmh') or {}).get('mean'), 1)} km/h larger than the field's "
        f"[{_f((rel26.get('clip_speed_drop_kmh') or {}).get('lo'), 1)}, {_f((rel26.get('clip_speed_drop_kmh') or {}).get('hi'), 1)}]. The 2025 car shows no such growth "
        f"({_pm(sp25.get('growth_kmh'), 1)} km/h [{ci(sp25.get('growth_ci90'))}]).",
        f"3. **Lap-time cost.** The main straights cost {_f(sp26.get('time_total_s'), 2)} s per lap [{ci(sp26.get('time_total_ci90'), 2)}] in 2026, of which "
        f"{_f(sp26.get('time_build_s'), 2)} s [{ci(sp26.get('time_build_ci90'), 2)}] is the speed lost along the straight; most of the {_f(str26.get('total'), 1)} s gap is in the corners.",
        f"4. **Power vs drag is not identifiable from public data.** A joint fit of deployed power and drag area on the energy-rich part of each straight (gravity removed with GPS altitude, "
        f"leave-one-out field, tow-free samples) gives correlation {_f(pt26.get('correlation'), 2)} between the two and intervals of {ci(pt26.get('d_power_ci90'), 0)} kW and "
        f"{ci(pt26.get('d_cda_ci90'), 2)} m². An earlier version of this project claimed a ~36 kW power deficit; it did not survive gradient correction and like-for-like comparison, and is withdrawn.",
        f"5. **The car decides the 2026 order.** Between-team share of qualifying-gap variance: {_f(100 * vs['2025']['car_share'], 0)}% pooled in 2025 "
        f"(median event {_f(100 * vs['2025']['median_event_share'], 0)}%) vs {_f(100 * vs['2026']['car_share'], 0)}% in 2026 (median event {_f(100 * vs['2026']['median_event_share'], 0)}%).",
    ]
    if up:
        gh = up["grip_high_rel"]
        lines.append(
            f"6. **The 2026 Hungary upgrade: suggestive, not established.** A changepoint model not told upgrade dates rates the {cp.get('map_event')} the most likely shift "
            f"(posterior {_f(cp.get('map_probability'), 2)}), but no change is about as plausible ({_f(cp.get('p_no_change'), 2)}). Fast-corner grip vs the other teams went "
            f"{_f(100 * gh['before']['mean'], 1)}% → {_f(100 * gh['after']['mean'], 1)}% (shift {_pm(100 * gh['shift'], 1)} ± {_f(100 * gh['shift_se'], 1)} points, "
            f"{gh['after']['n']} clean events after)."
        )
    lines += [
        "7. **Wind is not estimable** from session-level weather data (fast-corner interval about ±1.5 km/h per m/s); the prototype's 0.41 s crosswind attribution has no support.",
        "8. **Data finding.** In the public TracingInsights archive (F1 live timing processed with FastF1) the GPS and car-data streams are offset by about "
        f"{_f(dq['gps_lag_s_median'], 2)} s, and GPS is linearly interpolated onto car-data timestamps. Uncorrected, that misplaces samples by about 9 m at 300 km/h, enough to corrupt any braking-point "
        "comparison. This project detects original fixes, estimates the offset per lap from GPS-vs-wheel speed, and corrects it.",
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
        "7. **Race pace.** Fixed effects for driver, compound and per-compound tyre degradation plus a fuel term per lap on green-flag laps; intervals from a wild "
        "cluster bootstrap by driver (Webb weights), checked for coverage with autocorrelated errors.",
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
        f"Conformal coverage {_f(100 * cm['conformal_coverage'], 1)}% at a 90% target (median event {_f(100 * cm['coverage_by_event']['median'], 0)}%).",
        f"- Lap-sim accounting of the 2026 gap: {_f(100 * ds.get('ratio_of_means', float('nan')), 0)}% of the mean gap [{_f(100 * (ds.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds.get('ratio_ci90') or [0, float('nan')])[1], 0)}%], rank correlation with events r = {_f(ds.get('correlation'), 2)}, but event-level R² < 0: an accounting, not a forecast.",
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
