"""Separating a straight-line deficit into power and drag from acceleration vs speed.

On a straight at full throttle, m a = P / v - q CdA - m g Crr. Comparing one car with the
field median *at the same speed and event*, a deficit in power and a deficit in drag leave
different fingerprints in the acceleration gap:

    power deficit dP:   da(v) = dP / (m v)              -> m * da * v is flat in v
    drag deficit dCdA:  da(v) = -rho v^2 dCdA / (2 m)    -> m * da * v grows like v^3
    traction limit:     da concentrated at low speed, vanishing at high speed

So the gap is expressed as a "power-equivalent" deficit m * da * v in speed bands. If that
number is roughly constant across bands, the deficit behaves like missing power; if it
grows steeply with speed, like extra drag. Speeds are capped at 285 km/h in 2026, below the
regulated MGU-K taper, so the comparison is between cars with the same electrical limit.
The power here is *deployed* wheel power: it includes the energy-management strategy, not
only the power unit's peak output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.vehicle_params import straight_segments

BAND_KMH = 20.0
MIN_SPEED_KMH = 160.0


def max_band_speed(season: int) -> float:
    return 280.0 if season >= 2026 else 320.0


def acceleration_samples(state: VehicleState) -> pd.DataFrame:
    """Full-throttle, low-lateral-load (speed, acceleration) samples from one lap."""
    season = state.lap.meta.season
    rows = []
    for seg in straight_segments(state, min_length_m=120.0, trim_m=10.0, max_speed_kmh=max_band_speed(season) + 5):
        rows.append(pd.DataFrame({"v_kmh": state.speed_smooth_ms[seg][::2] * 3.6, "ax": state.ax_ms2[seg][::2]}))
    if not rows:
        return pd.DataFrame(columns=["v_kmh", "ax"])
    return pd.concat(rows, ignore_index=True)


def band_medians(samples: pd.DataFrame, season: int) -> pd.DataFrame:
    """Median acceleration per speed band (one row per band with >= 3 samples)."""
    s = samples[(samples["v_kmh"] >= MIN_SPEED_KMH) & (samples["v_kmh"] < max_band_speed(season))].copy()
    s["band"] = (s["v_kmh"] // BAND_KMH) * BAND_KMH
    g = s.groupby("band")["ax"].agg(["median", "size"]).reset_index()
    return g[g["size"] >= 3].rename(columns={"median": "ax", "size": "n"})


def acceleration_deficit(
    bands: pd.DataFrame, team: str, n_boot: int = 500, seed: int = 0
) -> pd.DataFrame:
    """Team's acceleration gap to the field median per speed band, with an event bootstrap.

    `bands` columns: season, round, team, band, ax, mass_kg (one season).
    Returns band, d_ax (m/s^2), ci, power-equivalent deficit (kW) and its ci.
    """
    b = bands.copy()
    b["field"] = b.groupby(["round", "band"])["ax"].transform("median")
    b["d_ax"] = b["ax"] - b["field"]
    t = b[b["team"] == team]
    rng = np.random.default_rng(seed)
    rows = []
    for band, g in t.groupby("band"):
        by_event = g.groupby("round")["d_ax"].mean()
        if len(by_event) < 4:
            continue
        boots = np.array([rng.choice(by_event.to_numpy(), len(by_event)).mean() for _ in range(n_boot)])
        v = (band + BAND_KMH / 2) / 3.6
        m = float(g["mass_kg"].iloc[0])
        rows.append({
            "band_kmh": float(band), "d_ax": float(by_event.mean()),
            "d_ax_lo": float(np.percentile(boots, 5)), "d_ax_hi": float(np.percentile(boots, 95)),
            "d_power_kw": float(by_event.mean() * m * v / 1000),
            "d_power_lo": float(np.percentile(boots, 5) * m * v / 1000),
            "d_power_hi": float(np.percentile(boots, 95) * m * v / 1000),
            "n_events": int(len(by_event)),
        })
    return pd.DataFrame(rows)


def power_or_drag_signature(deficit: pd.DataFrame) -> dict[str, float]:
    """Log-log slope of |power-equivalent deficit| vs speed: ~0 => power-like, ~3 => drag-like.

    Also returns the mean power-equivalent deficit across bands.
    """
    d = deficit[np.abs(deficit["d_power_kw"]) > 1e-6]
    if len(d) < 3:
        return {"slope": float("nan"), "mean_kw": float("nan")}
    x = np.log((d["band_kmh"] + BAND_KMH / 2).to_numpy())
    y = np.log(np.abs(d["d_power_kw"].to_numpy()))
    slope = float(np.polyfit(x, y, 1)[0])
    return {"slope": slope, "mean_kw": float(deficit["d_power_kw"].mean()),
            "all_bands_negative": bool((deficit["d_ax_hi"] < 0).all()),
            "all_bands_positive": bool((deficit["d_ax_lo"] > 0).all())}


def power_deficit_summary(
    bands: pd.DataFrame, team: str, min_band_kmh: float = 200.0, n_boot: int = 2000, seed: int = 1
) -> dict[str, float]:
    """Mean power-equivalent deficit over bands >= min_band_kmh with an event bootstrap CI.

    Each event contributes the mean of its bands, so events with more bands do not dominate.
    """
    b = bands.copy()
    b["field"] = b.groupby(["round", "band"])["ax"].transform("median")
    b["d_kw"] = (b["ax"] - b["field"]) * b["mass_kg"] * (b["band"] + BAND_KMH / 2) / 3.6 / 1000
    t = b[(b["team"] == team) & (b["band"] >= min_band_kmh)]
    per_event = t.groupby("round")["d_kw"].mean()
    if len(per_event) < 3:
        return {"mean_kw": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_events": int(len(per_event))}
    rng = np.random.default_rng(seed)
    boots = [rng.choice(per_event.to_numpy(), len(per_event)).mean() for _ in range(n_boot)]
    return {"mean_kw": float(per_event.mean()), "lo": float(np.percentile(boots, 5)),
            "hi": float(np.percentile(boots, 95)), "n_events": int(len(per_event))}
