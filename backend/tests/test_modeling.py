"""Lap comparison, POD, energy, race pace, validation gates."""

import numpy as np
import pandas as pd
import pytest

from amr_aerotwin.domain import AlignedLap, AmbientState, LapMeta
from amr_aerotwin.modeling.energy import lap_energy_summary, straight_energy_metrics
from amr_aerotwin.modeling.lap_compare import compare_laps, segment_time_loss
from amr_aerotwin.modeling.pod import PODReducedOrderModel
from amr_aerotwin.modeling.race_pace import clean_race_laps, fit_race_pace
from amr_aerotwin.modeling.validation import check_lap, geometry_ok, residual_diagnostics
from amr_aerotwin.physics.dynamics import estimate_vehicle_state

AMB = AmbientState(20.0, 30.0, 1000.0, 0.0, 0.0, 0.0)


def _lap(speed, step=5.0, throttle=None, driver="X", quality=None):
    n = len(speed)
    s = np.arange(n) * step
    t = np.concatenate([[0.0], np.cumsum(2 * step / (speed[1:] + speed[:-1]))])
    lap_time = float(t[-1] + step / speed[-1])
    return AlignedLap(
        meta=LapMeta(2026, "T", "Qualifying", driver, "Team", 1, lap_time), ambient=AMB,
        distance_m=s, time_s=t, speed_ms=np.asarray(speed, float),
        throttle_pct=np.full(n, 100.0) if throttle is None else throttle, brake=np.zeros(n),
        gear=np.full(n, 7.0), drs=np.zeros(n), rpm=np.zeros(n), x_m=s, y_m=np.zeros(n), z_m=np.zeros(n),
        lap_length_m=n * step, quality=quality or {},
    )


def test_lap_comparison_phases_and_straights_sum_to_official_gap():
    base = 60 + 20 * np.sin(np.linspace(0, 6 * np.pi, 1000))
    ref = _lap(base)
    tgt = _lap(base * (1 - 0.01 * (np.sin(np.linspace(0, 6 * np.pi, 1000)) < 0)))
    cmp_ = compare_laps(tgt, ref, np.array([800.0, 2500.0, 4100.0]), ["T1", "T2", "T3"])
    official = tgt.meta.lap_time_s - ref.meta.lap_time_s
    assert segment_time_loss(tgt, ref).sum() == pytest.approx(official, abs=1e-9)
    total = cmp_.corner_table["total_s"].sum() + cmp_.straight_loss_s
    assert total == pytest.approx(official, abs=1e-9)
    assert cmp_.delta_s[-1] == pytest.approx(official, abs=1e-9)
    same = compare_laps(ref, ref, np.array([800.0]), ["T1"])
    assert same.total_delta_s == pytest.approx(0.0, abs=1e-12)


def test_pod_recovers_rank_two_field_and_generalises():
    rng = np.random.default_rng(0)
    s = np.linspace(0, 1, 300)
    m1, m2 = np.sin(2 * np.pi * s), np.cos(6 * np.pi * s)
    x = np.array([200 + rng.normal(10, 3) * m1 + rng.normal(4, 2) * m2 for _ in range(12)])
    res = PODReducedOrderModel(n_modes=2).fit_transform(x)
    assert res.explained_variance_ratio[:2].sum() > 0.999
    assert res.reconstruction_rmse < 1e-8
    assert res.loo_reconstruction_rmse < 1e-6
    assert np.allclose(np.linalg.norm(res.spatial_modes, axis=1), 1.0)


def test_energy_detects_full_throttle_speed_drop_and_ignores_steady_straights():
    n = 600
    v_steady = np.concatenate([np.linspace(40, 85, 300), np.full(300, 85.0)])
    v_clip = np.concatenate([np.linspace(40, 85, 300), np.linspace(85, 77, 300)])
    k = np.zeros(n)
    steady = straight_energy_metrics(estimate_vehicle_state(_lap(v_steady), mass_kg=775, curvature_inv_m=k))
    clip = lap_energy_summary(estimate_vehicle_state(_lap(v_clip), mass_kg=775, curvature_inv_m=k))
    assert steady["speed_drop_kmh"].max() < 0.5
    assert steady["time_loss_s"].max() < 0.01  # smoothing ripple only
    assert clip["speed_drop_kmh"] == pytest.approx(8 * 3.6, abs=1.0)
    assert clip["decel_distance_m"] > 1000
    assert clip["time_loss_s"] > 0.05
    assert clip["power_deficit_kw"] > 0


def _synthetic_race(seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    pace = {f"D{i}": 90 + 0.2 * i for i in range(8)}
    fuel, deg = -0.06, {"MEDIUM": 0.05, "HARD": 0.03}
    off = {"MEDIUM": 0.0, "HARD": 0.4}
    for i, (d, p) in enumerate(pace.items()):
        stop = 14 + 2 * i  # different strategies make fuel and tyre age separable
        for lap in range(1, 51):
            comp = "MEDIUM" if lap <= stop else "HARD"
            life = lap if lap <= stop else lap - stop
            stint = 1 if lap <= stop else 2
            t = p + off[comp] + deg[comp] * life + fuel * lap + rng.normal(0, 0.15)
            rows.append({"drv": d, "team": f"T{int(d[1]) // 2}", "lap": lap, "time": t, "compound": comp,
                         "life": life, "stint": stint, "status": "1", "del": False,
                         "is_pit_in": lap == stop, "is_pit_out": lap == stop + 1})
    rows[5]["status"] = "4"  # safety car lap must be filtered
    rows[6]["time"] += 30.0  # incident lap must be filtered
    return pd.DataFrame(rows), pace


def test_race_pace_recovers_fuel_degradation_and_driver_pace():
    laps, pace = _synthetic_race()
    clean = clean_race_laps(laps)
    assert not ((clean["drv"] == "D0") & (clean["lap"].isin([1, 6, 7, 14, 15]))).any()
    res = fit_race_pace(laps, dict(zip(laps["drv"], laps["team"])), n_boot=100)
    assert res.fuel_s_per_lap == pytest.approx(-0.06, abs=0.012)
    assert res.deg_s_per_lap["HARD"] == pytest.approx(0.03, abs=0.01)
    assert res.deg_s_per_lap["MEDIUM"] == pytest.approx(0.05, abs=0.01)
    dp = res.driver_pace.set_index("driver")["pace_s"]
    assert (dp - dp["D0"]).to_dict() == pytest.approx({d: p - 90 for d, p in pace.items()}, abs=0.12)
    assert res.team_pace.iloc[0]["gap_s"] == 0.0


def test_lap_checks_can_fail():
    good = _lap(np.full(100, 50.0), quality={"projection_rms_m": 1.0, "speed_trap_minus_max_kmh": -15.0})
    bad = _lap(np.full(100, 50.0), quality={"projection_rms_m": 30.0, "speed_trap_minus_max_kmh": 20.0})
    assert check_lap(good).passed
    res = check_lap(bad)
    assert not res.passed and set(res.failures) == {"projection_rms_m", "speed_trap_minus_max_kmh"}
    assert geometry_ok(-1.01) and not geometry_ok(0.9)


def test_residual_diagnostics_calibrated_for_gaussian_noise():
    r = np.random.default_rng(0).normal(0, 2.0, 5000)
    d = residual_diagnostics(r, sigma=2.0)
    assert d.ece < 0.02 and d.jarque_bera_p > 0.01 and abs(d.lag1_autocorr) < 0.05


def test_race_pace_refuses_unidentifiable_single_strategy_race():
    laps, _ = _synthetic_race()
    same = laps.copy()
    same["life"] = np.where(same["lap"] <= 20, same["lap"], same["lap"] - 20)
    same["compound"] = np.where(same["lap"] <= 20, "MEDIUM", "HARD")
    assert fit_race_pace(same, dict(zip(same["drv"], same["team"])), n_boot=10) is None


def test_race_pace_fuel_interval_has_nominal_coverage():
    hits = 0
    for seed in range(20):
        laps, _ = _synthetic_race(seed)
        lo, hi = fit_race_pace(laps, dict(zip(laps["drv"], laps["team"])), n_boot=60).fuel_ci90
        hits += lo <= -0.06 <= hi
    assert hits / 20 >= 0.8  # nominal 90%


def _bands(d_power_kw=0.0, d_cda=0.0, seed=0):
    from amr_aerotwin.modeling.powertrain import BAND_KMH

    rng = np.random.default_rng(seed)
    rows = []
    m, rho = 775.0, 1.2
    for rnd in range(12):
        for t in range(8):
            team = "Aston Martin" if t == 0 else f"T{t}"
            for band in np.arange(160, 280, BAND_KMH):
                v = (band + BAND_KMH / 2) / 3.6
                ax = 600e3 / (m * v) - 0.5 * rho * v * v * 1.3 / m + rng.normal(0, 0.05)
                if t == 0:
                    ax += d_power_kw * 1000 / (m * v) - 0.5 * rho * v * v * d_cda / m
                rows.append({"season": 2026, "round": rnd, "team": team, "band": band, "ax": ax, "mass_kg": m})
    return pd.DataFrame(rows)


def test_power_deficit_has_flat_power_equivalent_signature():
    from amr_aerotwin.modeling.powertrain import acceleration_deficit, power_or_drag_signature

    d = acceleration_deficit(_bands(d_power_kw=-40.0), "Aston Martin")
    assert np.allclose(d["d_power_kw"], -40.0, atol=4.0)
    sig = power_or_drag_signature(d)
    assert abs(sig["slope"]) < 0.5 and sig["all_bands_negative"]


def test_drag_deficit_has_steep_power_equivalent_signature():
    from amr_aerotwin.modeling.powertrain import acceleration_deficit, power_or_drag_signature

    sig = power_or_drag_signature(acceleration_deficit(_bands(d_cda=0.15), "Aston Martin"))
    assert sig["slope"] > 2.0
