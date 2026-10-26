"""Energy-limited deployment ("clipping") on straights, from speed traces alone.

Why a speed *drop* is the signature
-----------------------------------
On a straight at full throttle, m dv/dt = P(v, t) / v - drag(v). If power depended only on
speed, including the 2026 regulated MGU-K taper (1800 - 5 v kW above 290 km/h), the car
would settle at an equilibrium speed and approach it from below; it would not slow down.
A sustained deceleration at full throttle with no braking and little lateral load means
power is falling with *time*: the battery has stopped deploying, or the car is harvesting
at full throttle. Active-aero and ERS state are not published (FIA data policy, 2026), so
this indirect signature is the only public view of energy management.

Metrics per straight (model-light). Acceleration has gravity removed using the road
gradient, so an uphill straight does not read as clipping, and a deceleration only counts
when it persists for at least 30 m (single-sample noise is ~2 m/s^2).
- speed_drop_kmh      peak speed minus speed at the end of the straight
- decel_distance_m    metres of persistent full-throttle deceleration after the peak
- power_deficit_kw    m * |a_x| * v averaged over the decelerating part: the minimum power
                      shortfall relative to holding speed (drag change ignored, so a
                      lower bound)
- time_loss_s         time lost against holding the peak speed to the end of the straight
                      (an upper bound on what full deployment could recover)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from amr_aerotwin.modeling.intervals import boot_ci, boot_ci_columns
from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.vehicle_params import straight_segments

DECEL_THRESHOLD_MS2 = -0.3
MIN_PERSIST_M = 30.0


def _persistent(flag: np.ndarray, n_min: int) -> np.ndarray:
    """Keep only runs of True at least n_min long."""
    out = np.zeros_like(flag)
    i = 0
    while i < len(flag):
        if flag[i]:
            j = i
            while j < len(flag) and flag[j]:
                j += 1
            if j - i >= n_min:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def straight_energy_metrics(state: VehicleState, min_length_m: float = 150.0) -> pd.DataFrame:
    """Per-straight clipping metrics for one lap."""
    rows = []
    step = state.lap.grid_step_m
    n_min = max(1, int(round(MIN_PERSIST_M / step)))
    for seg in straight_segments(state, min_length_m=min_length_m, trim_m=10.0, drop_line_cut=True):
        v = state.speed_smooth_ms[seg]
        ax = state.ax_propulsive_ms2[seg]
        i_peak = int(np.argmax(v))
        after = slice(i_peak, len(seg))
        decel = _persistent(ax[after] < DECEL_THRESHOLD_MS2, n_min)
        v_after = v[after]
        deficit = state.mass_kg * np.abs(ax[after][decel]) * v_after[decel] / 1000.0
        rows.append(
            {
                "start_m": float(state.distance_m[seg[0]]),
                "length_m": float(len(seg) * step),
                "peak_speed_kmh": float(v[i_peak] * 3.6),
                "end_speed_kmh": float(v[-1] * 3.6),
                "speed_drop_kmh": float((v[i_peak] - v[-1]) * 3.6),
                "peak_position_frac": float(i_peak / max(len(seg) - 1, 1)),
                "decel_distance_m": float(np.sum(decel) * step),
                "power_deficit_kw": float(np.mean(deficit)) if len(deficit) else 0.0,
                "time_loss_s": float(np.sum(step * (1.0 / v_after - 1.0 / v[i_peak]))),
            }
        )
    return pd.DataFrame(rows)


def lap_energy_summary(state: VehicleState) -> dict[str, float]:
    """Totals over all straights of one lap."""
    df = straight_energy_metrics(state)
    if df.empty:
        return {"n_straights": 0.0, "speed_drop_kmh": 0.0, "decel_distance_m": 0.0,
                "power_deficit_kw": 0.0, "time_loss_s": 0.0}
    return {
        "n_straights": float(len(df)),
        "speed_drop_kmh": float(df["speed_drop_kmh"].mean()),
        "decel_distance_m": float(df["decel_distance_m"].sum()),
        "power_deficit_kw": float(np.average(df["power_deficit_kw"], weights=df["decel_distance_m"] + 1e-9)),
        "time_loss_s": float(df["time_loss_s"].sum()),
    }


PROFILE_BINS = 10


def straight_speed_profile(states: list[VehicleState], ref: VehicleState, min_length_m: float = 400.0) -> pd.DataFrame:
    """Speed of every team along each main straight, at matched fractions of its length.

    Straights are taken from the reference (pole) lap: full throttle from corner exit to the
    braking point. Each straight is split into PROFILE_BINS equal parts by position, so all
    cars are compared at the same piece of track (gradient and wind are shared). Returns one
    row per (team, straight, bin) with the team's mean speed there (km/h).
    """
    rows = []
    for k, seg in enumerate(straight_segments(ref, min_length_m=min_length_m, trim_m=0.0, drop_line_cut=True)):
        edges = np.linspace(0, len(seg), PROFILE_BINS + 1).astype(int)
        step = ref.lap.grid_step_m
        for st in states:
            v = st.speed_smooth_ms[seg] * 3.6
            for b in range(PROFILE_BINS):
                rows.append({"team": st.lap.meta.team, "driver": st.lap.meta.driver, "straight": k,
                             "straight_start_m": float(ref.distance_m[seg[0]]), "bin": b,
                             "bin_length_m": float((edges[b + 1] - edges[b]) * step),
                             "speed_kmh": float(np.mean(v[edges[b]:edges[b + 1]]))})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby(["team", "straight", "straight_start_m", "bin", "bin_length_m"], as_index=False)["speed_kmh"].mean()


def speed_gap_profile(profiles: pd.DataFrame, team: str, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Team speed minus the median of the *other* teams, per fraction of straight length.

    `profiles`: rows from `straight_speed_profile` plus `round`. Each event contributes its
    mean over straights; the bootstrap resamples events.
    """
    p = profiles.copy()
    rows = []
    for (rnd, k, b), g in p.groupby(["round", "straight", "bin"]):
        t, o = g[g["team"] == team], g[g["team"] != team]
        if t.empty or len(o) < 4:
            continue
        rows.append({"round": rnd, "straight": k, "bin": b, "gap_kmh": float(t["speed_kmh"].iloc[0] - o["speed_kmh"].median()),
                     "field_kmh": float(o["speed_kmh"].median()),
                     "bin_length_m": float(g["bin_length_m"].iloc[0]) if "bin_length_m" in g else np.nan})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    per_event = d.groupby(["round", "bin"])["gap_kmh"].mean().unstack("bin")
    rng = np.random.default_rng(seed)
    arr = per_event.to_numpy()
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    boots = np.nanmean(arr[idx], axis=1)
    growth = boots[:, -1] - boots[:, 0]
    half = PROFILE_BINS // 2
    first = boots[:, half - 1] - boots[:, 0]
    second = boots[:, -1] - boots[:, half]
    # Note: the shape alone cannot separate causes. A point-mass simulation shows that a
    # corner-exit deficit plus extra drag also gives a flat first half and a late loss, so the
    # profile locates the loss along the straight but does not attribute it.
    n = len(arr)
    lo, hi = boot_ci_columns(boots, n)
    out = pd.DataFrame({
        "bin": per_event.columns.astype(int),
        "fraction": (per_event.columns.astype(float) + 0.5) / PROFILE_BINS,
        "gap_kmh": np.nanmean(arr, axis=0),
        "ci_lo": lo,
        "ci_hi": hi,
    })
    out.attrs["growth_kmh"] = float(np.nanmean(arr[:, -1] - arr[:, 0]))
    out.attrs["growth_ci90"] = boot_ci(growth, n)
    out.attrs["first_half_kmh"] = float(np.nanmean(arr[:, half - 1] - arr[:, 0]))
    out.attrs["first_half_ci90"] = boot_ci(first, n)
    out.attrs["second_half_kmh"] = float(np.nanmean(arr[:, -1] - arr[:, half]))
    out.attrs["second_half_ci90"] = boot_ci(second, n)
    # Leave-one-event-out range of the second-half change: does any single event carry it?
    ev_second = arr[:, -1] - arr[:, half]
    loo = [float(np.nanmean(np.delete(ev_second, i))) for i in range(n)] if n > 2 else []
    out.attrs["second_half_loo_range"] = (min(loo), max(loo)) if loo else (float("nan"), float("nan"))
    out.attrs["n_events"] = int(n)
    per_straight = d.pivot_table(index=["round", "straight"], columns="bin", values="gap_kmh")
    late = (per_straight.iloc[:, -1] - per_straight.iloc[:, half]).dropna()
    out.attrs["n_straights"] = int(len(late))
    out.attrs["n_straights_losing_late"] = int((late < 0).sum())
    if d["bin_length_m"].notna().all():
        # Time cost per lap (all main straights) of the whole straight-line gap, and of the part
        # that builds up along the straight (gap beyond the corner-exit gap of that straight)
        v_f = d["field_kmh"] / 3.6
        exit_gap = d.groupby(["round", "straight"])["gap_kmh"].transform(lambda x: x.iloc[0])
        d["t_total"] = d["bin_length_m"] * (1 / np.maximum(v_f + d["gap_kmh"] / 3.6, 1) - 1 / v_f)
        d["t_build"] = d["bin_length_m"] * (1 / np.maximum(v_f + d["gap_kmh"] / 3.6, 1) - 1 / np.maximum(v_f + exit_gap / 3.6, 1))
        per_ev_t = d.groupby("round")[["t_total", "t_build"]].sum().to_numpy()
        tb = per_ev_t[rng.integers(0, len(per_ev_t), size=(n_boot, len(per_ev_t)))].mean(axis=1)
        out.attrs["time_total_s"] = float(per_ev_t[:, 0].mean())
        out.attrs["time_total_ci90"] = boot_ci(tb[:, 0], len(per_ev_t))
        out.attrs["time_build_s"] = float(per_ev_t[:, 1].mean())
        out.attrs["time_build_ci90"] = boot_ci(tb[:, 1], len(per_ev_t))
    return out


def relative_metric(teams: pd.DataFrame, team: str, col: str, n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    """Mean over events of (team value - median of other teams), with an event bootstrap CI."""
    vals = []
    for _, g in teams.groupby("round"):
        t, o = g[g["team"] == team][col].dropna(), g[g["team"] != team][col].dropna()
        if len(t) and len(o) >= 4:
            vals.append(float(t.iloc[0] - o.median()))
    v = np.array(vals)
    if len(v) < 3:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": int(len(v))}
    rng = np.random.default_rng(seed)
    boots = v[rng.integers(0, len(v), size=(n_boot, len(v)))].mean(axis=1)
    lo, hi = boot_ci(boots, len(v))
    return {"mean": float(v.mean()), "lo": lo, "hi": hi, "n": int(len(v))}
