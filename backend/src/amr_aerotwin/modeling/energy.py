"""Energy-limited deployment ("clipping") on straights, from speed traces alone.

If power depended only on speed (the 2026 MGU-K taper included), a car at full throttle would approach an
equilibrium speed from below, so a sustained full-throttle deceleration means power falling with time. ERS
and active-aero state are not in the public data (see data/reference/SOURCES.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from amr_aerotwin.modeling.intervals import boot_ci, boot_ci_columns
from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.vehicle_params import straight_segments

DECEL_THRESHOLD_MS2 = -0.3
MIN_PERSIST_M = 30.0  # single-sample acceleration noise is about 2 m/s^2, so a deceleration must last this long


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
    """Clipping metrics for each straight of one lap.

    Acceleration is propulsive (gravity removed). The power deficit ignores the change in drag, so it is a
    lower bound; the time loss, against holding peak speed, is an upper bound on what full deployment recovers.
    """
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
    """Clipping metrics over all straights of one lap.

    Distance and time are summed; speed drop is a mean and power deficit a deceleration-weighted mean.
    """
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
    """Each team's mean speed (km/h) in PROFILE_BINS equal parts of every main straight.

    Straights and bins are positions on the reference (pole) lap, so all cars are compared on the same
    piece of track, with gradient and wind shared.
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
    """Team speed minus the other teams' median (km/h) per bin of straight length, with event-bootstrap intervals.

    `profiles` are `straight_speed_profile` rows plus `round`; each event counts once, as its mean over
    straights. Growth along the straight, its two halves and the time cost per lap go in `attrs`.
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
    # The profile locates a loss but cannot attribute it: extra drag, deployment ending sooner and
    # harvesting at full throttle all open a gap along a straight
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
    # Leave-one-event-out range of the second-half change, to show whether one event carries it
    ev_second = arr[:, -1] - arr[:, half]
    loo = [float(np.nanmean(np.delete(ev_second, i))) for i in range(n)] if n > 2 else []
    out.attrs["second_half_loo_range"] = (min(loo), max(loo)) if loo else (float("nan"), float("nan"))
    out.attrs["n_events"] = int(n)
    per_straight = d.pivot_table(index=["round", "straight"], columns="bin", values="gap_kmh")
    late = (per_straight.iloc[:, -1] - per_straight.iloc[:, half]).dropna()
    out.attrs["n_straights"] = int(len(late))
    out.attrs["n_straights_losing_late"] = int((late < 0).sum())
    if d["bin_length_m"].notna().all():
        # Time cost per lap over all main straights: of the whole gap, and of the part that builds up
        # along the straight (beyond that straight's corner-exit gap)
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
