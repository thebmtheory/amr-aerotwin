"""Lap comparison, POD, energy, race pace, validation gates."""

import numpy as np
import pandas as pd
import pytest
from amr_aerotwin.domain import AlignedLap, AmbientState, LapMeta
from amr_aerotwin.modeling.energy import lap_energy_summary, straight_energy_metrics
from amr_aerotwin.modeling.lap_compare import compare_laps, reference_cell_time, segment_time_loss
from amr_aerotwin.modeling.pod import PODReducedOrderModel
from amr_aerotwin.modeling.race_pace import clean_race_laps, fit_race_pace
from amr_aerotwin.modeling.validation import check_lap, geometry_ok
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
    # The trace is the gap at each grid point (not one point ahead); the last cell closes it
    assert np.allclose(cmp_.delta_s, tgt.time_s - ref.time_s, atol=1e-12)
    assert cmp_.delta_s[-1] + segment_time_loss(tgt, ref)[-1] == pytest.approx(official, abs=1e-9)
    assert cmp_.total_delta_s == pytest.approx(official, abs=1e-9)
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
    pad = np.full(40, 30.0)  # slow, part-throttle sections so the straight does not touch the line
    v_steady = np.concatenate([pad, np.linspace(40, 85, 300), np.full(300, 85.0), pad])
    v_clip = np.concatenate([pad, np.linspace(40, 85, 300), np.linspace(85, 77, 300), pad])
    n = len(v_steady)
    thr = np.concatenate([np.full(40, 30.0), np.full(600, 100.0), np.full(40, 30.0)])
    k = np.zeros(n)
    steady = straight_energy_metrics(estimate_vehicle_state(_lap(v_steady, throttle=thr), mass_kg=775, curvature_inv_m=k))
    clip = lap_energy_summary(estimate_vehicle_state(_lap(v_clip, throttle=thr), mass_kg=775, curvature_inv_m=k))
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
    res = fit_race_pace(laps, dict(zip(laps["drv"], laps["team"])))
    assert res.fuel_s_per_lap == pytest.approx(-0.06, abs=0.012)
    assert res.deg_s_per_lap["HARD"] == pytest.approx(0.03, abs=0.01)
    assert res.deg_s_per_lap["MEDIUM"] == pytest.approx(0.05, abs=0.01)
    dp = res.driver_pace.set_index("driver")["pace_s"]
    assert (dp - dp["D0"]).to_dict() == pytest.approx({d: p - 90 for d, p in pace.items()}, abs=0.12)
    assert res.team_pace.iloc[0]["gap_s"] == 0.0


def test_lap_checks_can_fail():
    from amr_aerotwin.modeling.validation import LAP_CHECKS

    ok = {m: 0.0 for m in LAP_CHECKS}
    ok.update(projection_rms_m=1.0, speed_trap_minus_max_kmh=-15.0)
    good = _lap(np.full(100, 50.0), quality=ok)
    bad = _lap(np.full(100, 50.0), quality={**ok, "projection_rms_m": 30.0, "speed_trap_minus_max_kmh": 20.0})
    assert check_lap(good).passed
    res = check_lap(bad)
    assert not res.passed and set(res.failures) == {"projection_rms_m", "speed_trap_minus_max_kmh"}
    missing = {k: v for k, v in ok.items() if k != "gps_speed_rms_ms"}
    assert not check_lap(_lap(np.full(100, 50.0), quality=missing)).passed  # missing required metric
    no_trap = {**ok, "speed_trap_minus_max_kmh": float("nan")}
    assert check_lap(_lap(np.full(100, 50.0), quality=no_trap)).passed  # optional metric may be absent
    assert geometry_ok(-1.01) and not geometry_ok(0.9)


def test_race_pace_refuses_unidentifiable_single_strategy_race():
    laps, _ = _synthetic_race()
    same = laps.copy()
    same["life"] = np.where(same["lap"] <= 20, same["lap"], same["lap"] - 20)
    same["compound"] = np.where(same["lap"] <= 20, "MEDIUM", "HARD")
    assert fit_race_pace(same, dict(zip(same["drv"], same["team"]))) is None


def _correlated_race(seed: int, n_drivers: int = 16, phi: float = 0.6, offset_sd: float = 0.12):
    """Synthetic race with AR(phi) within-stint errors and stint-level offsets."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_drivers):
        d = f"D{i:02d}"
        stop = 12 + (i * 3) % 20
        for stint, laps in ((1, range(1, stop + 1)), (2, range(stop + 1, 51))):
            offset = rng.normal(0, offset_sd)
            e_prev = 0.0
            for lap in laps:
                comp = "MEDIUM" if stint == 1 else "HARD"
                life = lap if stint == 1 else lap - stop
                e_prev = phi * e_prev + rng.normal(0, 0.15)
                t = 90 + 0.1 * i + (0.4 if comp == "HARD" else 0) + (0.05 if comp == "MEDIUM" else 0.03) * life - 0.06 * lap + offset + e_prev
                rows.append({"drv": d, "team": f"T{i // 2}", "lap": lap, "time": t, "compound": comp, "life": life,
                             "stint": stint, "status": "1", "del": False, "is_pit_in": lap == stop, "is_pit_out": lap == stop + 1})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("phi,offset_sd", [(0.0, 0.0), (0.6, 0.12)])
def test_race_pace_intervals_cover(phi, offset_sd):
    """Fuel-effect interval coverage with independent and with correlated lap errors."""
    hits = 0
    n = 20
    for seed in range(n):
        laps = _correlated_race(seed, phi=phi, offset_sd=offset_sd)
        lo, hi = fit_race_pace(laps, dict(zip(laps["drv"], laps["team"]))).fuel_ci90
        hits += lo <= -0.06 <= hi
    assert hits / n >= 0.85  # nominal 90%; 0.93 over 60 seeds for both error models


AMB_STD = AmbientState(15.0, 30.0, 1013.25 * 1.2 / 1.225, 0.0, 0.0, 0.0)


def _straight_lap(power_w, cda, grade=0.0, seed=0, team="T", driver="X"):
    """A lap of three full-throttle straights integrated from m a = P/v - q CdA - m g (Crr + grade)."""
    from amr_aerotwin.domain import GRAVITY_ACCEL as G

    rng = np.random.default_rng(seed)
    m, rho, step = 775.0, 1.2, 5.0
    v_all, thr, z = [], [], [0.0]
    for v0 in (42.0, 50.0, 58.0):
        v = v0
        for _ in range(int(600 / step)):
            a = power_w / (m * v) - 0.5 * rho * v * v * cda / m - G * (0.012 + grade)
            v = np.sqrt(v * v + 2 * a * step)
            v_all.append(v + rng.normal(0, 0.02))
            thr.append(100.0)
            z.append(z[-1] + grade * step)
        for _ in range(int(200 / step)):
            v_all.append(max(v_all[-1] - 1.2, 30.0))
            thr.append(0.0)
            z.append(z[-1] - 3 * grade * step)  # descend while braking so the lap closes in altitude
    n = len(v_all)
    s = np.arange(n) * step
    v_arr = np.array(v_all)
    lap = AlignedLap(
        meta=LapMeta(2026, "T", "Qualifying", driver, team, 1, float(np.sum(step / v_arr))), ambient=AMB_STD,
        distance_m=s, time_s=np.cumsum(step / v_arr), speed_ms=v_arr, throttle_pct=np.array(thr),
        brake=np.zeros(n), gear=np.full(n, 7.0), drs=np.zeros(n), rpm=np.zeros(n), x_m=s, y_m=np.zeros(n),
        z_m=np.array(z[:n]), lap_length_m=n * step, gap_ahead_m=np.full(n, 1e6),
    )
    return estimate_vehicle_state(lap, mass_kg=m, curvature_inv_m=np.zeros(n))


def test_power_drag_fit_recovers_values_and_removes_gradient():
    from amr_aerotwin.modeling.powertrain import acceleration_phase_mask, fit_power_drag

    for grade in (0.0, 0.04):
        st = _straight_lap(600e3, 1.3, grade=grade)
        fit = fit_power_drag([st], acceleration_phase_mask([st], st))
        assert fit.power_kw == pytest.approx(600.0, rel=0.07), grade
        assert fit.cda_m2 == pytest.approx(1.3, rel=0.15), grade  # P and CdA are collinear


def test_acceleration_phase_mask_respects_speed_cap():
    from amr_aerotwin.modeling.powertrain import acceleration_phase_mask

    st = _straight_lap(600e3, 1.3)
    mask = acceleration_phase_mask([st], st)
    assert mask.any() and np.all(st.speed_smooth_ms[mask] * 3.6 <= 285.0 + 1e-6)


def test_joint_deficit_reports_power_and_drag_with_their_correlation():
    from amr_aerotwin.modeling.powertrain import joint_deficit

    rng = np.random.default_rng(0)
    rows = []
    for rnd in range(12):
        for t in range(9):
            team = "Aston Martin" if t == 0 else f"T{t}"
            p = 600 + rng.normal(0, 8) - (35 if t == 0 else 0)
            cda = 1.3 + 0.03 * (p - 600) / 10 + rng.normal(0, 0.01)  # collinear, as in real fits
            rows.append({"season": 2026, "round": rnd, "event": f"E{rnd}", "team": team, "power_kw": p,
                         "cda_m2": cda, "matched_deficit_kw": -20 + rng.normal(0, 5)})
    jd = joint_deficit(pd.DataFrame(rows), "Aston Martin")
    assert jd.d_power_ci90[0] < -35 < jd.d_power_ci90[1]
    assert jd.correlation > 0.5
    assert jd.matched_ci90[0] < -20 < jd.matched_ci90[1]
    assert joint_deficit(pd.DataFrame(rows), "Aston Martin", exclude_round=3).n_events == 11


def test_geometry_check_accepts_figure_of_eight():
    from amr_aerotwin.modeling.validation import expected_turn_count

    t = np.linspace(0, 2 * np.pi, 800, endpoint=False)
    assert expected_turn_count(np.cos(t), np.sin(t)) == 1
    assert expected_turn_count(np.sin(t), np.sin(t) * np.cos(t)) == 0  # lemniscate
    assert geometry_ok(0.01, expected_turns=0) and not geometry_ok(0.01, expected_turns=1)


def test_speed_gap_profile_detects_late_straight_loss_and_flat_profiles():
    from amr_aerotwin.modeling.energy import PROFILE_BINS, speed_gap_profile

    rng = np.random.default_rng(1)
    rows = []
    for rnd in range(10):
        for t in range(9):
            team = "Aston Martin" if t == 0 else f"T{t}"
            for b in range(PROFILE_BINS):
                v = 200 + 10 * b + rng.normal(0, 0.5)
                if t == 0:
                    v -= 5 + (0 if b < 5 else 2 * (b - 4))  # constant exit deficit, then late loss
                rows.append({"round": rnd, "team": team, "straight": 0, "bin": b, "speed_kmh": v})
    prof = speed_gap_profile(pd.DataFrame(rows), "Aston Martin")
    assert prof["gap_kmh"].iloc[0] == pytest.approx(-5, abs=0.5)
    assert prof.attrs["second_half_kmh"] == pytest.approx(-8, abs=0.7)
    assert abs(prof.attrs["first_half_kmh"]) < 0.7
    lo, hi = prof.attrs["growth_ci90"]
    assert hi < 0
    flat = speed_gap_profile(pd.DataFrame(rows), "T3")
    assert flat.attrs["growth_ci90"][0] < 0 < flat.attrs["growth_ci90"][1]


def test_uniform_percentage_deficit_gives_equal_loss_rates_in_every_section():
    base = 40 + 30 * (1 + np.sin(np.linspace(0, 8 * np.pi, 1200)))
    ref = _lap(base)
    slow = _lap(base / 1.03)  # 3% slower everywhere
    cmp_ = compare_laps(slow, ref, np.array([700.0, 2000.0, 3600.0, 5200.0]), ["T1", "T2", "T3", "T4"])
    rates = cmp_.class_summary.dropna(subset=["loss_rate_pct"])
    rates = rates[rates["reference_time_s"] > 0]
    assert np.allclose(rates["loss_rate_pct"], 3.0, atol=0.05)
    # Seconds lost are still largest where the reference spends most time
    biggest = rates.loc[rates["time_s"].idxmax(), "speed_class"]
    assert biggest == rates.loc[rates["reference_time_s"].idxmax(), "speed_class"]


def test_race_pace_team_gap_intervals_cover():
    """Team gaps (the published quantity) must cover too, not only the shared fuel term."""
    hits, total = 0, 0
    for seed in range(20):
        laps = _correlated_race(seed)
        tp = fit_race_pace(laps, dict(zip(laps["drv"], laps["team"]))).team_pace.set_index("team")
        for team, row in tp.iterrows():
            if team == "T0":
                continue
            truth = 0.2 * int(team[1:])
            hits += row["ci_lo"] <= truth <= row["ci_hi"]
            total += 1
    assert 0.85 <= hits / total <= 0.99  # nominal 90%: neither too narrow nor uselessly wide


def test_close_corners_split_the_track_instead_of_one_taking_it():
    """Two corners 90 m apart (a chicane) each keep braking, apex and exit time; nothing is counted twice."""
    base = 60 + 20 * np.sin(np.linspace(0, 6 * np.pi, 1000))
    ref = _lap(base)
    tgt = _lap(base * 0.99)
    cmp_ = compare_laps(tgt, ref, np.array([2000.0, 2090.0]), ["T1", "T2"])
    t = cmp_.corner_table.set_index("corner")
    for c in ("T1", "T2"):
        assert t.loc[c, "apex_s"] > 0 and t.loc[c, "entry_s"] > 0 and t.loc[c, "exit_s"] > 0
    total = cmp_.corner_table["total_s"].sum() + cmp_.straight_loss_s
    assert total == pytest.approx(cmp_.total_delta_s, abs=1e-12)
    # Together they cover exactly the union of their windows (120 m before T1 to 120 m after T2)
    assert t["reference_time_s"].sum() == pytest.approx(
        float(np.sum(reference_cell_time(ref)[(ref.distance_m >= 1880.0) & (ref.distance_m < 2210.0)])), rel=1e-9)
