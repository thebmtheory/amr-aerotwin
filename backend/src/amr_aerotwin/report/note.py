"""Generate the technical note (Markdown) from season.json, so every number in it is current.

The README's result blocks and the page headline come from here too.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from amr_aerotwin.report.author import AUTHOR

TARGET = "Aston Martin"
README_BLOCKS = ("findings", "gates")
CARDINALS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


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
    """Other teams with five or more events; `off_pace` keeps only those at least 1% off pole over a lap.

    Near the front the corner loss rate is about zero, so the straights-to-corners ratio is unstable there.
    """
    return {t: v for t, v in rates.get(season, {}).items()
            if t != TARGET and v.get("n_events", 0) >= 5 and (not off_pace or v.get("lap_rate_pct", 0) >= 1)}


def first_half_phrase(sp: dict[str, Any]) -> str:
    """How the gap changes over the first half of the straights, worded by whether its interval includes zero."""
    v, lo_hi = sp.get("first_half_kmh"), sp.get("first_half_ci90") or [float("nan")] * 2
    rng = f"[{_f(lo_hi[0], 1)} to {_f(lo_hi[1], 1)}]"
    if v is None:
        return "n/a"
    if lo_hi[0] <= 0 <= lo_hi[1]:
        return f"holds that through the first half ({_pm(v, 1)} km/h {rng})"
    return f"{'loses' if v < 0 else 'gains'} {_f(abs(v), 1)} km/h over the first half {rng}"


def multiple_words(h: float) -> str:
    """A multiple that is a whole or half number, in words: 2 -> 'twice', 2.5 -> 'two and a half times'."""
    whole, half = int(h), h % 1 == 0.5
    if whole >= len(CARDINALS):
        return f"{h:g} times"
    if half:
        return f"{CARDINALS[whole]} and a half times"
    return {1: "once", 2: "twice"}.get(whole, f"{CARDINALS[whole]} times")


def straight_multiple(vf: dict[str, Any]) -> tuple[float, str] | None:
    """The paired straight-line ratio to the nearest half and in words ('about twice' covers 1.75 to 2.25).

    None unless the ratio's 90% interval excludes 1 and it rounds to at least 1.5, so the words never
    claim a multiple the data do not support.
    """
    r, lo = vf.get("ratio"), (vf.get("ratio_ci90") or [float("nan")])[0]
    if r is None or not math.isfinite(r) or lo is None or not lo > 1:
        return None
    h = math.floor(2 * r + 0.5) / 2
    return (h, multiple_words(h)) if h >= 1.5 else None


def pace_words(other: Any, target: Any, tol: float = 0.10) -> str:
    """How another team's lap deficit compares with the target's: 'about as slow' within 10%, else faster or slower."""
    try:
        o, t = float(other), float(target)
    except (TypeError, ValueError):
        return "n/a"
    if not (math.isfinite(o) and math.isfinite(t)) or t == 0:
        return "n/a"
    return "about as slow" if abs(o / t - 1) <= tol else "faster" if o < t else "slower"


def headline(s: dict[str, Any]) -> str:
    """The report's one-line finding, worded from the latest season's paired straight-line ratio.

    Used for the line under the page's title, the technical note and the README, so the claim
    follows the data instead of being typed by hand.
    """
    vfs = s.get("straight_vs_field") or {}
    vf = vfs.get(max(vfs), {}) if vfs else {}
    r, lo = vf.get("ratio"), (vf.get("ratio_ci90") or [float("nan")])[0]
    if r is None or not math.isfinite(r) or lo is None:
        return f"Where {TARGET} loses time: public timing data, track by track."
    season, m = max(vfs), straight_multiple(vf)
    if m:
        return f"In {season} {TARGET} loses time on the straights at about {m[1]} the rate of any other team."
    if lo > 1:
        return f"In {season} {TARGET} loses time on the straights faster than any other team."
    if r > 1:
        return f"In {season} {TARGET} has the highest straight-line loss rate of any team, though not by a clear margin."
    return f"In {season} {TARGET} does not lose time on the straights faster than every other team."


PARAM_LABELS = {"mu": "μ", "cla_m2": "C<sub>L</sub>A", "cda_m2": "C<sub>D</sub>A", "power_w": "power"}


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return " and ".join(items) if len(items) < 3 else ", ".join(items[:-1]) + " and " + items[-1]


def coverage_words(mean: Any, ci: Any, nominal: float = 0.9) -> str:
    """Interval coverage against its nominal level, worded by whether the 90% interval over events includes it."""
    try:
        m, lo, hi = float(mean), float(ci[0]), float(ci[1])
    except (TypeError, ValueError, IndexError):
        return "n/a"
    level = f"the nominal {_f(100 * nominal, 0)}%"
    if hi < nominal:
        return f"fewer than {level}, so the intervals are {'somewhat ' if m >= nominal - 0.1 else ''}too narrow"
    if lo > nominal:
        return f"more than {level}, so the intervals are conservative"
    return f"in line with {level}"


def emulator_paragraph(s: dict[str, Any]) -> str:
    """Method item on the GP lap-time emulator and how well it and the linear surrogate predict held-out runs.

    Every number and comparison comes from season.json's surrogate_summary.
    """
    ss = s.get("surrogate_summary") or {}
    yrs = sorted(ss, reverse=True)  # latest season first
    b = [ss[y] for y in yrs]
    d0 = b[0] if b else {}
    params = list(d0.get("sobol_first") or PARAM_LABELS)
    h = d0.get("half_range")
    text = (
        "**Lap-time emulator.** The 1% sensitivities, extended linearly, are a surrogate of the simulator that holds only near the calibrated car. "
        f"A Gaussian-process emulator (constant × anisotropic RBF kernel plus white noise, on log factors) is fitted at each event to {d0.get('n_train', 'n/a')} "
        f"simulator runs on a Latin hypercube of factors on {_and([PARAM_LABELS.get(p, p) for p in params])}, each within ±{_f(100 * h, 0) if h else 'n/a'}%, "
        f"for the car used for the what-ifs (Aston Martin's best clean lap, else the pole lap), and tested on {d0.get('n_test', 'n/a')} independent runs. A simulator run "
        "is already cheap, so speed is not the point: the emulator gives the lap-time response over the whole range with an uncertainty checked out of sample, "
        "and splits its variance between the parameters."
    )
    rows = [dict(r, season=y) for y in yrs for r in ss[y].get("events", [])]
    if not rows:
        return text
    worst = max(rows, key=lambda r: r["max_abs_err_s"])
    low = min(rows, key=lambda r: r["coverage90"])
    all_better = all(x["n_gp_rmse_below_linear"] == x["n_events"] for x in b)
    factor = min(r["linear_rmse_s"] / r["rmse_s"] for r in rows) if all(r["rmse_s"] > 0 for r in rows) else float("nan")
    inter = [max(0.0, 1.0 - sum(x["sobol_first"].values())) for x in b]
    # What the linear surrogate misses is curvature, not interaction, when the interactions' share of the
    # lap-time variance is small next to its squared error (ANOVA terms are orthogonal)
    curvature = all(i * x["spread_s"] ** 2 < 0.25 * x["linear_rmse_s"] ** 2 for i, x in zip(inter, b))
    order = sorted(params, key=lambda p: -d0["sobol_first"][p])

    def shares(x: dict[str, Any]) -> str:
        return _and([f"{PARAM_LABELS.get(p, p)} {_f(100 * x['sobol_first'][p], 0)}%" for p in order])

    def pct(v: float) -> str:
        return "under 0.1%" if v < 0.0005 else f"{_f(100 * v, 1)}%"

    def where(r: dict[str, Any]) -> str:
        return f"the {r['season']} {r['event']}"

    def per_season(fmt: Callable[[str, dict[str, Any]], str]) -> str:
        return _and([fmt(y, x) for y, x in zip(yrs, b)])

    def cover(i: int, y: str, x: dict[str, Any]) -> str:
        ci, m = x["coverage90_mean_ci90"], x["coverage90_mean"]
        head = f"{_f(100 * m, 0)}% of held-out runs in {y}" if i == 0 else f"in {y}, {_f(100 * m, 0)}%"
        return f"{head} [{_f(100 * ci[0], 0)}, {_f(100 * ci[1], 0)}], {coverage_words(m, ci)}"

    gp_rmse = per_season(lambda y, x: f"{_f(x['rmse_s'], 3)} s in {y} ({x['n_events']} events)")
    spread = per_season(lambda y, x: f"{_f(x['spread_s'], 2)} s")
    gp_max = per_season(lambda y, x: f"{_f(x['max_abs_err_s'], 3)} s")
    lin_rmse = per_season(lambda y, x: f"{_f(x['linear_rmse_s'], 2)} s in {y}")
    lin_max = per_season(lambda y, x: f"{_f(x['linear_max_abs_err_s'], 2)} s")
    rest_v = [pct(i) for i in inter]
    rest = (f"{rest_v[0]} in {'both seasons' if len(b) == 2 else 'every season'}" if len(b) > 1 and len(set(rest_v)) == 1
            else _and([f"{v} in {y}" for v, y in zip(rest_v, yrs)]))
    better = (f"at every event{' of both seasons' if len(b) == 2 else ''}, by a factor of {math.floor(factor)} or more" if all_better and factor >= 1
              else per_season(lambda y, x: f"at {x['n_gp_rmse_below_linear']} of {x['n_events']} events in {y}"))
    additive = "almost additively" if max(inter) < 0.05 else "mostly additively" if max(inter) < 0.2 else "far from additively"
    return text + (
        f" On held-out runs its median RMS error is {gp_rmse}, while the held-out lap times themselves have a median standard deviation of {spread}; "
        f"its worst error is {gp_max} at the median event and {_f(worst['max_abs_err_s'], 3)} s at most ({where(worst)}). "
        f"Its 90% predictive intervals cover {'; '.join(cover(i, y, x) for i, (y, x) in enumerate(zip(yrs, b)))}. "
        f"Coverage at a single event is noisy: the lowest is {_f(100 * low['coverage90'], 0)}% ({where(low)}). "
        f"The linear surrogate's median RMS error on the same runs is {lin_rmse} (median worst error {lin_max}); the emulator's error is lower {better}. "
        f"Averaged over events, its first-order Sobol indices (the tests check them against indices computed with the simulator itself, on a synthetic "
        f"track) give {shares(d0)} of the {yrs[0]} lap-time variance" + "".join(f" ({y}: {shares(x)})" for y, x in zip(yrs[1:], b[1:]))
        + f"; these shares follow from giving every parameter the same ±{_f(100 * h, 0) if h else 'n/a'}% range, not from what a development step "
        f"could achieve. Interactions carry the remaining {rest}, so the four parameters act {additive} over this range"
        + (", and the linear surrogate's error is mainly the curvature of each parameter's own effect." if curvature else ".")
    )


def build_note(season_json: Path, out_md: Path) -> Path:
    s = json.loads(Path(season_json).read_text())
    rates = s.get("section_rates", {})

    def sec(season: str, team: str, name: str) -> dict[str, float]:
        return _sec(rates, season, team, name)

    def others(season: str, off_pace: bool = False) -> list[dict[str, Any]]:
        return list(_others(rates, season, off_pace).values())

    vf = s.get("straight_vs_field", {}).get("2026", {})
    nxt = vf.get("next_team", "n/a")
    a26, a25, cad = rates.get("2026", {}).get(TARGET, {}), rates.get("2025", {}).get(TARGET, {}), rates.get("2026", {}).get(nxt, {})
    st26 = sec("2026", TARGET, "straights")
    # Whole-lap rates on the same tracks as the ratio, else each team's rate over its own events
    nl, al = vf.get("next_lap_rate_pct", cad.get("lap_rate_pct")), vf.get("target_lap_rate_pct", a26.get("lap_rate_pct"))
    o_st = [sec("2026", t, "straights")["v"] for t, v in rates.get("2026", {}).items() if v in others("2026")]
    o_ratio = [v["straight_to_corner_ratio"] for v in others("2026", off_pace=True)]
    mult = straight_multiple(vf)
    central = (f', so "{mult[1]}" is the central estimate, not a lower bound'
               + (f" ({_f(100 * (vf.get('p_ratio_above_2') or 0), 0)}% of bootstrap draws exceed 2)" if mult[0] == 2 else "")) if mult else ""
    # Front-runners (under 1% off pole) that lose more per second on the straights than in the corners
    front = {t: v for t, v in _others(rates, "2026").items() if v.get("lap_rate_pct", 9) < 1 and v.get("corner_rate_pct", 0) > 0
             and sec("2026", t, "straights").get("v", 0) > v["corner_rate_pct"]}
    front_sentence = "".join(
        f"; {t} is a front-runner that loses more on the straights ({_f(sec('2026', t, 'straights')['v'], 2)}%) than in the corners "
        f"({_f(v['corner_rate_pct'], 2)}%), at a much lower level than Aston Martin" for t, v in front.items())
    r25 = [v["straight_to_corner_ratio"] for v in others("2025", off_pace=True)]
    a25r = a25.get("straight_to_corner_ratio", float("nan"))
    where25 = "below" if r25 and a25r < min(r25) else "above" if r25 and a25r > max(r25) else "in line with"
    field25 = f"{where25} the teams at least 1% off pole ({_f(min(r25), 2)} to {_f(max(r25), 2)})" if r25 else ""
    sp26 = s.get("straight_profile", {}).get("2026", {}).get(TARGET, {})
    sp25 = s.get("straight_profile", {}).get("2025", {}).get(TARGET, {})
    b0 = (sp26.get("bins") or [{}])[0]
    prof26 = {t: v for t, v in s.get("straight_profile", {}).get("2026", {}).items() if t != TARGET and v.get("second_half_kmh") is not None}
    late_team = min(prof26, key=lambda t: prof26[t]["second_half_kmh"]) if prof26 else "n/a"
    late_kmh = -prof26[late_team]["second_half_kmh"] if prof26 else float("nan")
    start_gaps = {t: abs((v.get("bins") or [{}])[0].get("gap_kmh") or 0) for t, v in prof26.items()}
    start_team = max(start_gaps, key=lambda t: start_gaps[t]) if start_gaps else "n/a"
    max_start = start_gaps.get(start_team, float("nan"))
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
    # The most any wind rotation improves the fit, % (mean over windy sessions)
    wind_gain = 100 * (1 - min((wt.get("mean_relative_sse") or {"": 1.0}).values()))

    def ci(v: Any, d: int = 1) -> str:
        return f"{_f(v[0], d)} to {_f(v[1], d)}" if v else "n/a"

    lines = [
        "# Where Aston Martin loses time: technical note",
        "",
        f"By {AUTHOR.name}. {AUTHOR.line}",
        "",
        "*Generated from `data/processed/season.json` by `aerotwin report`. Public data only; not affiliated with Aston Martin Aramco F1 Team. "
        "Intervals are 90% bootstrap intervals over events unless stated, widened for small samples (expanded percentile bootstrap: with as few events as "
        "here, plain percentile intervals cover less than their nominal level, which the tests check by simulation).*",
        "",
        "## Findings",
        "",
        f"1. **{headline(s)}** Loss rate = time lost to the pole lap "
        f"in a section ÷ the pole lap's time there, summed over events. Aston Martin's 2026 straight-line rate is {_f(st26.get('v'), 2)}% "
        f"[{_f(st26.get('lo'), 2)}, {_f(st26.get('hi'), 2)}] against {_f(a26.get('corner_rate_pct'), 2)}% in the corners, a ratio of "
        f"{_f(a26.get('straight_to_corner_ratio'), 2)} [{ci(a26.get('straight_to_corner_ci90'), 2)}]. Every other team with five or more events (its own pole laps count as zero loss) has a straight-line rate between "
        f"{_f(min(o_st), 2)}% and {_f(max(o_st), 2)}%. Summing every team over the same {vf.get('n_events')} events (those where Aston Martin has a passing lap), "
        f"Aston Martin's rate is {_f(vf.get('ratio'), 2)} times the highest of the others ({vf.get('next_team', 'n/a')}, {_f(vf.get('next_rate_pct'), 2)}%) "
        f"[{ci(vf.get('ratio_ci90'), 2)}, paired bootstrap over those events with the maximum over rivals taken inside each draw]{central}. "
        f"Teams at least 1% off pole over a lap have straights-to-corners ratios between "
        f"{_f(min(o_ratio), 2)} and {_f(max(o_ratio), 2)}. On those {vf.get('n_events')} tracks {nxt}, {pace_words(nl, al)} over a lap "
        f"({_f(nl, 2)}% vs {_f(al, 2)}%), loses {_f(vf.get('next_rate_pct'), 2)}% on the straights. Nearer the front the ratio is unstable "
        "because the corner deficit is close to zero" + front_sentence + f". In 2025 Aston Martin's ratio was "
        f"{_f(a25.get('straight_to_corner_ratio'), 2)} [{ci(a25.get('straight_to_corner_ci90'), 2)}], {field25}. Raw seconds by corner type are misleading "
        "here: cars spend the most time in slow corners, so slow corners usually carry the most seconds.",
        f"2. **Where on the straight.** Compared piece by piece along the main straights (those clear of the timing line), Aston Martin starts {_f(-(b0.get('gap_kmh') or 0), 1)} km/h "
        f"down, {first_half_phrase(sp26)} and loses {_f(-(sp26.get('second_half_kmh') or 0), 1)} km/h more "
        f"in the second half [{ci(sp26.get('second_half_ci90'))}], at full throttle, on {sp26.get('n_straights_losing_late')} of {sp26.get('n_straights')} main straights at {sp26.get('n_events')} events "
        f"(leaving out any one event: {ci(sorted(sp26.get('second_half_loo_range') or []))}). A late loss alone is not unusual: {late_team} loses {_f(late_kmh, 1)} km/h in the second half too, the next largest, "
        f"and several teams show smaller ones in both seasons. What sets Aston Martin apart is the size of both parts: the next largest gap at the start of the straights is {start_team}'s, {_f(max_start, 1)} km/h. "
        f"The gap reaches {_f(-((sp26.get('bins') or [{}])[-1].get('gap_kmh') or 0), 1)} km/h at the braking point. Extra drag, deployment ending earlier and harvesting at full "
        "throttle can all open a gap along a straight; public timing data cannot tell them apart. "
        f"In 2025 the same second-half change was {_pm(sp25.get('second_half_kmh'), 1)} km/h [{ci(sp25.get('second_half_ci90'))}]. Against the other teams' median, the main "
        f"straights cost {_f(sp26.get('time_total_s'), 2)} s per lap [{ci(sp26.get('time_total_ci90'), 2)}] in 2026.",
        "3. **Power vs drag is not identifiable from public timing data.** Over one straight the two terms are collinear; fits need at least 200 m of clean straight and a "
        "60 km/h speed range and are reported only where that holds. An earlier version of this project claimed a ~36 kW power deficit; it came from not correcting for "
        "gradient and comparing cars on different stretches of track, and is withdrawn.",
        f"4. **The teams decide the 2026 order.** Pooled over events, between-team differences (car and driver line-up together) explain {_f(100 * vs['2026']['car_share'], 0)}% "
        f"[{_f(100 * vs['2026']['car_share_ci90'][0], 0)}, {_f(100 * vs['2026']['car_share_ci90'][1], 0)}] of the variance in qualifying gaps in 2026, against {_f(100 * vs['2025']['car_share'], 0)}% "
        f"[{_f(100 * vs['2025']['car_share_ci90'][0], 0)}, {_f(100 * vs['2025']['car_share_ci90'][1], 0)}] in 2025; in the median event, {_f(100 * vs['2026']['median_event_share'], 0)}% and "
        f"{_f(100 * vs['2025']['median_event_share'], 0)}% (laps outside 107% of the best excluded).",
        f"5. **Physics accounting.** Giving the pole car's calibrated simulator Aston Martin's measured grip and top-speed gap accounts for "
        f"{_f(100 * (ds.get('ratio_of_means') or float('nan')), 0)}% of its mean 2026 gap over the {ds.get('n_events')} events where the geometry check passes and both teams have grip and "
        f"top-speed measurements, with a wide interval once the grip ratios' uncertainty is included [{_f(100 * (ds.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds.get('ratio_ci90') or [0, float('nan')])[1], 0)}%]: the measured deficits are of the right size to explain the gap, not a split of it "
        f"(event-level R² {_f(ds.get('r2_event_level'), 2)}). The same accounting for 2025, when the gap averaged {_f(ds25.get('mean_actual_s'), 2)} s against "
        f"{_f(ds.get('mean_actual_s'), 2)} s, gives "
        f"{_f(100 * (ds25.get('ratio_of_means') or float('nan')), 0)}% [{_f(100 * (ds25.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds25.get('ratio_ci90') or [0, float('nan')])[1], 0)}%] with event-level R² {_f(ds25.get('r2_event_level'), 1)} over {ds25.get('n_events')} events. "
        "It is an accounting of a large deficit, not a forecast of small ones.",
    ]
    if up:
        gh = up["grip_high_rel"]
        uh: dict[str, Any] = next((e for e in did if e["season"] == 2026 and e["event"] == up["event"]), {})
        p0 = [r["p_no_change"] for r in cp.get("prior_sensitivity", [])]
        pm = [r["map_probability"] for r in cp.get("prior_sensitivity", []) if r["map_event"] == cp.get("map_event")] or [float("nan")]
        two = cp.get("two_change_events") or []
        lines.append(
            f"6. **The 2026 Hungary upgrade: suggestive, not established.** A changepoint model not told upgrade dates rates the {cp.get('map_event')} the most likely single shift "
            f"(posterior {_f(cp.get('map_probability'), 2)} vs {_f(cp.get('p_no_change'), 2)} for no change; across the priors in the table below, P(no change) ranges "
            f"{_f(min(p0), 2)}–{_f(max(p0), 2)} and the {cp.get('map_event')} {_f(min(pm), 2)}–{_f(max(pm), 2)}). "
            f"Given a change the step is {_pm(cp.get('effect_pct'), 2)}% [{ci(cp.get('effect_ci90_pct'), 2)}]; allowing for no change, {_pm(cp.get('effect_avg_pct'), 2)}% "
            f"[{ci(cp.get('effect_avg_ci90_pct'), 2)}]. "
            + (f"A rise and a fall fit better than one step: two changes ({_pm((cp.get('two_change_steps_pct') or [0, 0])[0], 1)}% at the {two[0]}, "
               f"{_pm((cp.get('two_change_steps_pct') or [0, 0])[1], 1)}% at the {two[1]}) are {_f(cp.get('bf_two_vs_one'), 1)} times more likely than one, so much of the drop "
               "undoes a mid-season peak. " if len(two) == 2 and (cp.get("bf_two_vs_one") or 0) > 3 else "")
            + f"Fast-corner grip vs the other teams went {_f(100 * gh['before']['mean'], 1)}% → {_f(100 * gh['after']['mean'], 1)}% ({gh['before']['n']} events before, "
            f"only {gh['after']['n']} after with usable Aston Martin telemetry). The difference-in-differences test cannot settle it: Aston Martin's own estimates at its "
            f"other 2026 dates are spread {_f(uh.get('noise_ratio'), 1)} times as widely as the rivals' estimates at this date, so the rival placebos are not a fair "
            "reference, and against its own "
            f"{uh.get('n_time_placebos')} other dates no test can go below p = {_f(1 / (1 + (uh.get('n_time_placebos') or 0)), 2)} (the {up['event']} gets {_f(uh.get('time_placebo_p'), 2)})."
        )
    lines += [
        f"7. **Wind is left out, on evidence.** Rotating the wind direction through 360° across {wt.get('n_events', 0)} windy sessions, no orientation improves the "
        f"acceleration fit by more than {_f(wind_gain, 1)}% and the assumed one was best in {_f(100 * (wt.get('share_events_assumed_orientation_best') or 0), 0)}% of them "
        f"(chance: 1 in {len(wt.get('mean_relative_sse') or {})}). "
        "Session-level wind readings are not informative enough, so dynamic pressure uses ground speed. Earlier wind claims are withdrawn.",
        f"8. **Data note.** Placing car data by GPS position needs a per-lap timing correction in this archive (median {_f(dq['gps_lag_s_median'], 2)} s, about {_f(dq['gps_lag_s_median'] * 300 / 3.6, 0)} m at 300 km/h); "
        "the archive's odometer distance is unaffected. Frozen car-data stretches (e.g. Baku 2026), car-data stalls (speed, throttle and brake held for 0.5–1.5 s "
        "while GPS shows the car braking, then an impossible jump) and the feed's 104% throttle marker are detected and handled.",
        "",
        "## Data",
        "",
        f"Fastest valid qualifying lap of every driver at {s['n_events']} Grands Prix (2025 and 2026 to date), plus every lap of each race, from the public "
        "TracingInsights archive of F1 live timing. Car data (speed, throttle, brake, gear, rpm) arrives at roughly 4–10 Hz and GPS at about 4 Hz. "
        f"{dq['laps_passed']} of {dq['laps_total']} laps pass the automated data checks. Excluded events and reasons are listed in the report"
        + (f"; wet qualifying sessions ({', '.join(s.get('wet_events_excluded', []))}) are left out of everything built on qualifying. " if s.get("wet_events_excluded") else ". ")
        + "Gaps are to the fastest lap of qualifying, called the pole lap here; it is the Q3 pole at every event except 2025 Hungary, where a Q2 lap was faster. "
        "Regulation figures (minimum mass, MGU-K taper) and Aston Martin's declared upgrades come from FIA documents (data/reference/SOURCES.md).",
        "",
        "## Method",
        "",
        "1. **Alignment.** Each lap is projected onto the path of the fastest lap that passes every check. Between GPS fixes the archive fills in positions on the car-data "
        f"timestamps along a smooth curve in time; original fixes are identified (whole-decimetre coordinates) and the offset between the GPS and car-data streams (median {_f(dq['gps_lag_s_median'], 2)} s) "
        "is estimated per lap by matching GPS-derived speed to wheel speed. The archive's lap clock itself is often offset from the timing line, for both streams "
        f"together (up to {_f(dq.get('max_clock_offset_m'), 0)} m at the line on laps that pass: {dq.get('max_clock_offset_lap')}), so each lap is re-timed: "
        "positions stay where GPS puts them and time is mapped so the car is at the line at 0 and at the official lap time. Checked against the official sector "
        f"times, which come from separate timing loops, the aligned clock is off by {_f(dq.get('sector_time_error_median_s'), 3)} s in the median lap "
        f"({_f(dq.get('sector_time_error_rms_s'), 3)} s RMS, worst {_f(dq.get('sector_time_error_max_s'), 2)} s). Section and corner losses are measured against that "
        "reference lap" + ("; it is the fastest lap of qualifying except at " + ", ".join(
            f"the {r['season']} {r['event']} ({r['reference']}, {_f(r['gap_s'], 2)} s slower, because {r['fastest']}'s lap fails a check)"
            for r in s.get("reference_not_fastest", [])) if s.get("reference_not_fastest") else ", which is always the fastest lap of qualifying") + ".",
        "2. **Geometry.** Curvature is a smoothing spline of x(t), y(t) through raw fixes (time-domain, so position noise does not scale with speed), with the "
        "smoothing level chosen per event by the GPS-speed cross-check, then the median across all drivers. Integrated curvature must match the circuit's turn count "
        "(one for most circuits, zero for figure-of-eight Suzuka) within 3.5% below to 5% above; on clean data it runs about 1.5% high, because the smoothed path "
        "cuts corners slightly.",
        "3. **Lap simulator.** Quasi-steady point mass: grip μ(g + qC<sub>L</sub>A/m) on a friction ellipse, power limit, drag and rolling resistance, closed-lap "
        "forward/backward passes. Calibrated to the pole lap and Aston Martin's best lap at each event by MAP with weak log-normal priors; Laplace posterior with an AR(1) effective sample size; "
        "checked against a Metropolis sampler; a Gaussian process on the residual shows where point-mass physics fails.",
        f"4. {emulator_paragraph(s)}",
        "5. **Grip.** One near-limit point per corner (flat-out corners excluded) gives a line of limit acceleration against dynamic pressure; it is read only at "
        "two event-wide reference pressures because tyre load sensitivity makes absolute μ and C<sub>L</sub>A unidentifiable from public data.",
        "6. **Straights.** Main straights from the pole lap are split into ten equal pieces; each team's speed in each piece is compared with the other teams' median. "
        "Joint power and drag fits use the acceleration phase only (up to the field-median peak), gravity removed with GPS altitude, tow-free samples, 2026 speeds below the MGU-K taper.",
        "7. **Corner model.** Minimum corner speed at unseen circuits, cross-validated by whole circuit. Physics baseline: the lap simulator on the held-out track with a "
        "nominal car from the training events' calibrations only. Hybrid: gradient boosting on its residual. Split-conformal intervals; exact baseline Shapley values of the reported model.",
        "8. **Race pace.** Fixed effects for driver, compound and per-compound tyre degradation plus a fuel term per lap on green-flag laps; intervals from a "
        "delete-one-stint jackknife, checked for coverage of the fuel effect and of team gaps with autocorrelated errors.",
        "9. **Season.** Supertime gaps; per-event one-way random-effects variance split; single-changepoint model with exact normal-inverse-gamma evidence, effect averaged "
        "over the changepoint posterior (given a change, and over all models), prior sensitivity in the table below, and a two-change model as a check on a mid-season "
        "peak; upgrade difference-in-differences (team and event fixed effects, team-specific track-type slopes) with permutation p-values against rivals and against the "
        "team's own other dates, the fairer of the two used as the reference, Holm adjustment and an exact permutation minimum detectable effect.",
        "",
        "## Validation",
        "",
        "- Automated tests (backend/tests): analytic physics (constant-radius circle, terminal speed, braking distance), parameter recovery and interval coverage on "
        "synthetic data, leakage guards, exact Shapley efficiency, JavaScript–Python simulator parity, and an end-to-end run on real Silverstone data.",
        f"- Corner model, out of sample by whole circuit: steady-state formula R² {_f(mm.get('steady', {}).get('r2'), 2)}, lap sim on GPS geometry alone R² {_f(mm['physics']['r2'], 2)}, "
        f"gradient boosting R² {_f(mm['ml']['r2'], 2)}, hybrid R² {_f(mm['hybrid']['r2'], 2)} (RMSE {_f(mm['hybrid']['rmse_kmh'], 1)} km/h); within-corner R² ≤ 0 for all models (they do not separate cars at the same corner). "
        f"Conformal coverage {_f(100 * cm['conformal_coverage'], 1)}% at a 90% target (median event {_f(100 * cm['coverage_by_event']['median'], 1)}%, worst {_f(100 * cm['coverage_by_event']['min'], 0)}%).",
        f"- Lap-sim accounting of the 2026 gap: {_f(100 * ds.get('ratio_of_means', float('nan')), 0)}% of the mean gap [{_f(100 * (ds.get('ratio_ci90') or [float('nan')])[0], 0)}, "
        f"{_f(100 * (ds.get('ratio_ci90') or [0, float('nan')])[1], 0)}%], correlation across its {ds.get('n_events')} events r = {_f(ds.get('correlation'), 2)} "
        f"(Spearman {_f(ds.get('spearman'), 2)}), event-level R² {_f(ds.get('r2_event_level'), 2)}; in 2025, R² {_f(ds25.get('r2_event_level'), 1)}. "
        f"With {ds.get('n_events')} events and inputs from the same laps this is an accounting, not a forecast.",
        "- Upgrade effects (difference-in-differences, 4 events either side). Each is tested against rivals given the same date (team placebos) and against Aston Martin "
        "at its other dates (time placebos); when Aston Martin's own estimates are more than 1.5 times noisier than its rivals', only the time placebo is a fair reference. "
        "Detectable = the effect the reference test finds with 80% power at the 10% level. "
        f"With {len(did)} upgrades tested, no Holm-adjusted p can fall below {_f(s.get('upgrades', {}).get('holm_floor_lead'), 2)}, so none can be called significant after correction:",
    ]
    for e in did:
        ref = "own dates" if e.get("lead_test") == "time" else "rivals"
        mde = f"detectable ≥ {_f(e['mde_pct'], 2)}%" if e.get("mde_pct") is not None else "no effect detectable at 10% with this many dates"
        lines.append(f"  - {e['season']} {e['event']}: {_pm(e['effect_pct'], 2)}% ({mde}; reference {ref}, noise ratio {_f(e.get('noise_ratio'), 1)}; "
                     f"p vs rivals {_f(e['team_placebo_p'], 2)}, p vs own dates {_f(e['time_placebo_p'], 2)}, Holm-adjusted {_f(e.get('lead_p_holm'), 2)}; {e['n_pre']}/{e['n_post']} events)")
    sens = cp.get("prior_sensitivity") or []
    if sens:
        lines += ["", "Changepoint prior sensitivity (2026): posterior probability of no change, and the most likely single change, by coefficient prior scale g and prior P(no change).", "",
                  "| g | prior P(no change) | posterior P(no change) | most likely change | its probability |", "|---|---|---|---|---|"]
        lines += [f"| {_f(r['g'], 0)} | {_f(r['prior_no_change'], 2)} | {_f(r['p_no_change'], 2)} | {r['map_event']} | {_f(r['map_probability'], 2)} |" for r in sens]
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
    nxt_lap = vf.get("next_lap_rate_pct", rates.get("2026", {}).get(nxt, {}).get("lap_rate_pct"))
    amr_lap = vf.get("target_lap_rate_pct", a26.get("lap_rate_pct"))
    off = _others(rates, "2026", off_pace=True)
    ratios = [v["straight_to_corner_ratio"] for v in off.values()]
    sp26 = s.get("straight_profile", {}).get("2026", {}).get(TARGET, {})
    b0 = (sp26.get("bins") or [{}])[0]
    prof26 = {t: v for t, v in s.get("straight_profile", {}).get("2026", {}).items() if t != TARGET and v.get("second_half_kmh") is not None}
    late_team = min(prof26, key=lambda t: prof26[t]["second_half_kmh"]) if prof26 else "n/a"
    late_kmh = -prof26[late_team]["second_half_kmh"] if prof26 else float("nan")
    start_gaps = {t: abs((v.get("bins") or [{}])[0].get("gap_kmh") or 0) for t, v in prof26.items()}
    start_team = max(start_gaps, key=lambda t: start_gaps[t]) if start_gaps else "n/a"
    max_start = start_gaps.get(start_team, float("nan"))
    vs = s["variance_split"]
    findings = "\n".join([
        f"- **{headline(s)}** Measured as time lost to the pole lap per second spent "
        f"in each part of the lap, it loses {_f(st26.get('v'), 1)}% on the straights. On the same {vf.get('n_events')} tracks no other team loses more than "
        f"{_f(vf.get('next_rate_pct'), 1)}% ({nxt}, {_f(nxt_lap, 2)}% off pole over a lap against Aston Martin's {_f(amr_lap, 2)}%): "
        f"{_f(vf.get('ratio'), 1)} times as much, 90% interval {_f((vf.get('ratio_ci90') or [None])[0], 1)} to {_f((vf.get('ratio_ci90') or [None, None])[1], 1)}. "
        + ("Every other team" if ratios and max(ratios) < 1 else "Most teams") + " more than 1% off pole loses less per second "
        f"on the straights than in the corners (ratios {_f(min(ratios), 2)} to {_f(max(ratios), 2)}, against {_f(a26.get('straight_to_corner_ratio'), 2)} for Aston Martin)"
        + (f", as did Aston Martin in 2025 ({_f(a25.get('straight_to_corner_ratio'), 2)})." if (a25.get("straight_to_corner_ratio") or 9) < 1 else "."),
        f"- **The straight-line loss starts at the corner exit and {'grows along the straight' if (sp26.get('first_half_ci90') or [0, 0])[1] < 0 else 'grows late'}.** "
        f"On the main straights the car starts {_f(-(b0.get('gap_kmh') or 0), 1)} km/h down, where the next largest gap is {start_team}'s, {_f(max_start, 1)} km/h, "
        + (f"loses {_f(-(sp26.get('first_half_kmh') or 0), 1)} km/h over the first half and " if (sp26.get('first_half_ci90') or [0, 0])[1] < 0 else "and loses ")
        + f"{_f(-(sp26.get('second_half_kmh') or 0), 1)} km/h more in the second half (90% interval "
        f"{_f(-(sp26.get('second_half_ci90') or [0, 0])[1], 1)} to {_f(-(sp26.get('second_half_ci90') or [0, 0])[0], 1)}), at full throttle, on {sp26.get('n_straights_losing_late')} of "
        f"{sp26.get('n_straights')} main straights at {sp26.get('n_events')} events; the next largest late loss is {late_team}'s ({_f(late_kmh, 1)} km/h). Extra drag, deployment ending "
        "earlier and harvesting at full throttle all fit that shape; public timing data cannot tell them apart.",
        f"- **The teams decide the 2026 qualifying order:** between-team differences (car and driver line-up together) explain {_f(100 * vs['2026']['car_share'], 0)}% "
        f"(90% interval {_f(100 * vs['2026']['car_share_ci90'][0], 0)} to {_f(100 * vs['2026']['car_share_ci90'][1], 0)}) of the variance in qualifying gaps, against "
        f"{_f(100 * vs['2025']['car_share'], 0)}% in 2025.",
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
        "Every lap is checked against limits that real broken laps fail: GPS distance to the reference line; the lap's clock offset at the timing line, which must "
        "be the same at both ends (the lap is then re-timed); the aligned clock against the official sector times (within 0.15 s"
        + (f"; {_f(dq.get('sector_time_error_rms_s'), 3)} s RMS on the {dq.get('n_laps_sector_checked')} laps that pass" if dq.get("sector_time_error_rms_s") is not None else "")
        + "); consistency of speed with the timing channel; GPS speed vs wheel speed; sample gaps; speed trap vs peak speed; frozen car data (speed and rpm stuck for "
        "over 100 m, as on both Aston Martins at Baku 2026); and car-data stalls (speed, throttle and brake held for 0.5–1.5 s while GPS shows the car braking, then "
        "a jump no car can make). The reference line is rebuilt from the fastest lap that passes. The feed's 104% \"invalid throttle\" marker is repaired rather "
        "than rejected. Every event's curvature must integrate to the circuit's own turn count (zero for the figure-of-eight at Suzuka). "
        + (f"Wet qualifying ({', '.join(s.get('wet_events_excluded', []))}) is left out. " if s.get("wet_events_excluded") else "")
        + f"{dq['laps_passed']} of {dq['laps_total']} laps pass. Events that fail are listed with reasons in the report"
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
