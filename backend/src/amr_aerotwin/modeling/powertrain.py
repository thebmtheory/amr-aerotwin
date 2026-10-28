"""Straight-line power and drag differences between cars, from m (a_x + g grade + g Crr) = P / v - q CdA.

Power and drag are collinear over one straight (both terms fall with speed), so their differences are
reported jointly. P is deployed wheel power, so it includes energy management as well as the power unit.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from amr_aerotwin.domain import GRAVITY_ACCEL
from amr_aerotwin.modeling.intervals import boot_ci
from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.kinematics import decompose_aero_wind_vectors
from amr_aerotwin.physics.lapsim import CRR
from amr_aerotwin.physics.vehicle_params import straight_segments

TOW_GAP_M = 150.0  # closer to the car ahead, its slipstream lowers drag
MIN_SPEED_KMH = 150.0
MIN_FIT_POSITIONS = 40  # 200 m of straight
MIN_FIT_SPEED_SPAN_KMH = 60.0


def max_fit_speed_kmh(season: int) -> float:
    """Highest speed used in the fits (km/h); from 2026, below the regulated MGU-K taper."""
    return 285.0 if season >= 2026 else 330.0


def acceleration_phase_mask(states: list[VehicleState], ref: VehicleState) -> NDArray[np.bool_]:
    """Grid positions on the acceleration phase of each straight (positional, same for all cars).

    Each phase ends where the field-median speed peaks, so late clipping is left out without selecting on a
    car's own acceleration.
    """
    n = len(ref.distance_m)
    mask = np.zeros(n, dtype=bool)
    v_field = np.median(np.vstack([s.speed_smooth_ms for s in states]), axis=0)
    for seg in straight_segments(ref, min_length_m=250.0, trim_m=10.0):
        peak = int(np.argmax(v_field[seg]))
        mask[seg[: max(peak - 2, 0)]] = True
    cap = max_fit_speed_kmh(ref.lap.meta.season) / 3.6
    return mask & (v_field <= cap) & (v_field >= MIN_SPEED_KMH / 3.6)


def lap_samples(state: VehicleState, mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Positions in `mask` where this car is flat out, not braking, unloaded and not in a tow."""
    lap = state.lap
    gap = lap.gap_ahead_m if len(lap.gap_ahead_m) == len(mask) else np.full(len(mask), np.inf)
    return (
        mask & (lap.throttle_pct >= 99.0) & (lap.brake < 0.5)
        & (np.abs(state.ay_ms2) < 0.6 * GRAVITY_ACCEL) & (gap > TOW_GAP_M)
    )


@dataclass(frozen=True)
class PowerDragFit:
    power_kw: float
    cda_m2: float
    n_samples: int


def fit_power_drag(states: list[VehicleState], mask: NDArray[np.bool_]) -> PowerDragFit | None:
    """Least-squares (P, CdA) from one team's laps on the acceleration-phase positions."""
    xs, ys, pos, speeds = [], [], set(), []
    for st in states:
        sel = lap_samples(st, mask)
        if sel.sum() == 0:
            continue
        pos.update(np.flatnonzero(sel).tolist())
        speeds.append(st.speed_smooth_ms[sel] * 3.6)
        v = st.speed_smooth_ms[sel]
        ys.append(st.mass_kg * (st.ax_propulsive_ms2[sel] + GRAVITY_ACCEL * CRR))
        xs.append(np.column_stack([1.0 / v, -st.q_dyn_pa[sel]]))
    if not xs:
        return None
    x, y = np.vstack(xs), np.concatenate(ys)
    v_all = np.concatenate(speeds)
    # Two collinear terms need a long stretch of straight and a wide speed range to be fitted
    if len(pos) < MIN_FIT_POSITIONS or np.ptp(v_all) < MIN_FIT_SPEED_SPAN_KMH:
        return None
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    return PowerDragFit(power_kw=float(beta[0] / 1000.0), cda_m2=float(beta[1]), n_samples=len(y))


def position_matched_deficit_kw(
    states_by_team: dict[str, list[VehicleState]], mask: NDArray[np.bool_], team: str
) -> float:
    """Mean m * (a_team - median a_others) * v over shared positions (power-equivalent, kW)."""
    per_team = {}
    for t, sts in states_by_team.items():
        stack = [np.where(lap_samples(st, mask), st.ax_propulsive_ms2, np.nan) for st in sts]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # positions this team's cars did not use
            per_team[t] = np.nanmean(np.vstack(stack), axis=0)
    if team not in per_team or len(per_team) < 5:
        return float("nan")
    others = np.vstack([a for t, a in per_team.items() if t != team])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # positions no other car used
        field = np.nanmedian(others, axis=0)
    enough = np.sum(np.isfinite(others), axis=0) >= 4
    ok = np.isfinite(per_team[team]) & np.isfinite(field) & enough
    if ok.sum() < 10:
        return float("nan")
    st = states_by_team[team][0]
    return float(np.mean(st.mass_kg * (per_team[team][ok] - field[ok]) * st.speed_smooth_ms[ok]) / 1000.0)


def event_power_drag_rows(states: dict[str, VehicleState], ref: VehicleState) -> pd.DataFrame:
    """One row per team: fitted (P, CdA) and the position-matched deficit at this event."""
    mask = acceleration_phase_mask(list(states.values()), ref)
    by_team: dict[str, list[VehicleState]] = {}
    for st in states.values():
        by_team.setdefault(st.lap.meta.team, []).append(st)
    rows = []
    for team, sts in sorted(by_team.items()):
        fit = fit_power_drag(sts, mask)
        rows.append({
            "team": team,
            "power_kw": fit.power_kw if fit else np.nan,
            "cda_m2": fit.cda_m2 if fit else np.nan,
            "n_samples": fit.n_samples if fit else 0,
            "matched_deficit_kw": position_matched_deficit_kw(by_team, mask, team),
            "mass_kg": sts[0].mass_kg,
            "n_positions": int(mask.sum()),
        })
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class JointDeficit:
    d_power_kw: float
    d_power_ci90: tuple[float, float]
    d_cda_m2: float
    d_cda_ci90: tuple[float, float]
    correlation: float
    matched_kw: float
    matched_ci90: tuple[float, float]
    n_events: int
    draws: NDArray[np.float64]  # bootstrap draws of the median (dP kW, dCdA m^2)
    per_event: pd.DataFrame


def per_event_deltas(rows: pd.DataFrame, team: str) -> pd.DataFrame:
    """Team minus median of the other teams, per event, for P, CdA and the matched deficit."""
    out = []
    for rnd, g in rows.groupby("round"):
        t = g[g["team"] == team]
        o = g[(g["team"] != team) & g["power_kw"].notna()]
        if t.empty or len(o) < 4 or not np.isfinite(t["power_kw"].iloc[0]):
            continue
        out.append({
            "round": int(rnd),
            "event": str(t["event"].iloc[0]) if "event" in t else "",
            "d_power_kw": float(t["power_kw"].iloc[0] - o["power_kw"].median()),
            "d_cda_m2": float(t["cda_m2"].iloc[0] - o["cda_m2"].median()),
            "matched_kw": float(t["matched_deficit_kw"].iloc[0]),
        })
    return pd.DataFrame(out)


def joint_deficit(rows: pd.DataFrame, team: str, n_boot: int = 2000, seed: int = 0,
                  exclude_round: int | None = None) -> JointDeficit | None:
    """Median over events of `team` minus the field in P (kW) and CdA (m^2), with event-bootstrap intervals.

    Medians, because single-event fits of two collinear terms can be far off. None below 4 events.
    """
    pe = per_event_deltas(rows, team)
    if exclude_round is not None and not pe.empty:
        pe = pe[pe["round"] != exclude_round]
    if len(pe) < 4:
        return None
    arr = pe[["d_power_kw", "d_cda_m2"]].to_numpy()
    rng = np.random.default_rng(seed)
    draws = np.median(arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))], axis=1)
    mk = pe["matched_kw"].dropna().to_numpy()
    mk_boot = mk[rng.integers(0, len(mk), size=(n_boot, len(mk)))].mean(axis=1) if len(mk) else np.array([np.nan])

    def ci(a: NDArray[np.float64]) -> tuple[float, float]:
        return boot_ci(a, len(arr))

    return JointDeficit(
        d_power_kw=float(np.median(arr[:, 0])), d_power_ci90=ci(draws[:, 0]),
        d_cda_m2=float(np.median(arr[:, 1])), d_cda_ci90=ci(draws[:, 1]),
        correlation=float(np.corrcoef(draws[:, 0], draws[:, 1])[0, 1]),
        matched_kw=float(np.mean(mk)) if len(mk) else float("nan"), matched_ci90=ci(mk_boot),
        n_events=len(pe), draws=draws, per_event=pe,
    )


WIND_TEST_ANGLES = tuple(range(0, 360, 30))


def wind_rotation_test(states: dict[str, VehicleState], ref: VehicleState, min_wind_ms: float = 2.0) -> dict | None:
    """Residual sum of squares of the (P, CdA) fits with airspeed, relative to ground speed, per wind rotation.

    Tests the assumed timing-frame orientation (X = East, Y = North): if it is right, rotation 0 fits best
    and beats ground speed. None when the session was nearly calm.
    """


    wind = float(np.median([s.lap.ambient.wind_speed_ms for s in states.values()]))
    if wind < min_wind_ms:
        return None
    mask = acceleration_phase_mask(list(states.values()), ref)
    by_team: dict[str, list[VehicleState]] = {}
    for st in states.values():
        by_team.setdefault(st.lap.meta.team, []).append(st)

    def sse(q_of: Callable[[VehicleState], NDArray[np.float64]]) -> float:
        total = 0.0
        for sts in by_team.values():
            xs, ys = [], []
            for st in sts:
                sel = lap_samples(st, mask)
                if sel.sum() < 5:
                    continue
                v = st.speed_smooth_ms[sel]
                ys.append(st.mass_kg * (st.ax_propulsive_ms2[sel] + GRAVITY_ACCEL * CRR))
                xs.append(np.column_stack([1.0 / v, -q_of(st)[sel]]))
            if xs:
                x, y = np.vstack(xs), np.concatenate(ys)
                beta = np.linalg.lstsq(x, y, rcond=None)[0]
                total += float(np.sum((y - x @ beta) ** 2))
        return total

    ground = sse(lambda st: 0.5 * st.rho_kg_m3 * st.speed_smooth_ms**2)
    if ground <= 0:
        return None
    rel = {}
    for a in WIND_TEST_ANGLES:
        def q_air(st: VehicleState, a: int = a) -> np.ndarray:
            amb = replace(st.lap.ambient, wind_direction_deg=(st.lap.ambient.wind_direction_deg + a) % 360)
            w = decompose_aero_wind_vectors(st.speed_smooth_ms, st.heading_rad, amb)
            return 0.5 * st.rho_kg_m3 * w["v_airspeed_ms"] ** 2
        rel[a] = sse(q_air) / ground
    return {"wind_ms": wind, "relative_sse": rel, "best_rotation_deg": int(min(rel, key=lambda k: rel[k]))}
