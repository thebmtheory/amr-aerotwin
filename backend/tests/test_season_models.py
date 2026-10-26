"""Season analyses: supertimes, variance split, changepoints, upgrade DiD, corner model, Shapley."""

import numpy as np
import pandas as pd
import pytest
from amr_aerotwin.modeling.corner_model import (
    NUMERIC_FEATURES,
    cross_validate,
    exact_baseline_shapley,
    fit_physics,
    physics_speed_kmh,
    team_corner_deficit,
)
from amr_aerotwin.modeling.season import (
    bayesian_changepoint,
    car_vs_driver_variance,
    log_marginal_likelihood,
    supertime_table,
    upgrade_effects,
)


def test_supertime_is_team_best_gap_to_event_best():
    q = pd.DataFrame({"season": 2025, "round": 1, "event": "E", "team": ["A", "A", "B"],
                      "driver": ["a1", "a2", "b1"], "lap_time_s": [80.0, 80.4, 80.8]})
    st = supertime_table(q).set_index("team")["gap_pct"]
    assert st["A"] == 0.0 and st["B"] == pytest.approx(1.0)


def test_variance_split_recovers_known_components():
    rng = np.random.default_rng(0)
    rows = []
    for ev in range(40):
        for t in range(10):
            car = rng.normal(0, 0.6)
            for d in range(2):
                rows.append({"season": 2025, "round": ev, "team": f"T{t}", "driver": f"T{t}D{d}",
                             "lap_time_s": 80 * (1 + (2 + car + rng.normal(0, 0.3)) / 100)})
    vs = car_vs_driver_variance(pd.DataFrame(rows))
    assert vs.car_share == pytest.approx(0.36 / (0.36 + 0.09), abs=0.07)
    assert vs.car_share_ci90[0] < vs.car_share < vs.car_share_ci90[1]


def test_log_marginal_likelihood_matches_monte_carlo():
    rng = np.random.default_rng(1)
    x = np.column_stack([np.ones(6), rng.normal(size=6)])
    y = rng.normal(size=6)
    exact = log_marginal_likelihood(x, y, g=2.0, a0=3.0, b0=2.0)
    s2 = 1 / rng.gamma(3.0, 1 / 2.0, 200000)
    beta = rng.normal(size=(200000, 2)) * np.sqrt(2.0 * s2)[:, None]
    resid = y[None, :] - beta @ x.T
    ll = -0.5 * (resid**2).sum(1) / s2 - 3 * np.log(2 * np.pi * s2)
    mc = np.log(np.mean(np.exp(ll - ll.max()))) + ll.max()
    assert exact == pytest.approx(mc, abs=0.05)


def test_changepoint_finds_a_step_and_stays_quiet_without_one():
    rng = np.random.default_rng(2)
    y = np.concatenate([np.full(10, 1.5), np.full(10, 0.9)]) + rng.normal(0, 0.12, 20)
    cp = bayesian_changepoint(y)
    assert cp.map_index == 10 and cp.p_no_change < 0.05 and cp.map_probability > 0.5
    assert cp.effect_ci90_pct[0] < -0.6 + 0.2 and cp.effect_ci90_pct[1] < 0
    flat = bayesian_changepoint(1.2 + rng.normal(0, 0.12, 20))
    assert flat.p_no_change > 0.5


def _panel(effect=-0.5, seed=3, noise=0.1):
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(1, 21):
        track = rng.uniform(0.2, 0.5)
        for t in range(8):
            team = "Aston Martin" if t == 0 else f"T{t}"
            gap = 1.0 + 0.2 * t + 2.0 * track * (t == 3) + rng.normal(0, noise)
            if team == "Aston Martin" and r >= 11:
                gap += effect
            rows.append({"season": 2025, "round": r, "event": f"E{r}", "team": team, "gap_pct": gap, "track_x": track})
    return pd.DataFrame(rows)


def test_upgrade_did_recovers_effect_with_significant_placebo_test():
    eff = upgrade_effects(_panel(-0.5, noise=0.04), pd.DataFrame({"season": [2025], "event": ["E11"]}), "Aston Martin")[0]
    assert eff.effect_pct == pytest.approx(-0.5, abs=0.08)
    # Smallest attainable permutation p with 7 rival placebos is 1/8
    assert eff.team_placebo_p == pytest.approx(1 / 8) and eff.time_placebo_p <= 0.2
    assert eff.n_pre == 4 and eff.n_post == 4 and eff.mde_pct > 0


def test_upgrade_placebo_p_values_are_calibrated_under_the_null():
    up = pd.DataFrame({"season": [2025], "event": ["E11"]})
    p = [upgrade_effects(_panel(0.0, seed=s), up, "Aston Martin")[0].team_placebo_p for s in range(30)]
    # Under H0 the permutation p-value is uniform on {1/8, ..., 8/8}: P(p <= 1/8) = 1/8
    assert np.mean(np.array(p) <= 1 / 8 + 1e-9) < 0.3
    assert np.mean(p) > 0.35


def _corner_data(n_events=12, seed=4):
    rng = np.random.default_rng(seed)
    a, b = 17.0, 0.0022
    rows = []
    for e in range(n_events):
        rho = rng.uniform(1.1, 1.22)
        for c in range(14):
            radius = rng.uniform(15, 250)
            for t in range(6):
                v = physics_speed_kmh(np.array([radius]), np.array([rho]), a, b)[0]
                v += 3.0 * np.sin(radius / 40) - 2.0 * (t == 0) + rng.normal(0, 2.0)
                rows.append({"event_key": f"E{e}", "corner_key": f"C{c}", "circuit_corner": f"E{e}C{c}",
                             "team": "Aston Martin" if t == 0 else f"T{t}", "season": 2025 + (e % 2),
                             "v_min_kmh": min(v, 330), "radius_m": radius, "turn_angle_deg": 90.0,
                             "approach_m": 400.0, "rho_kg_m3": rho, "headwind_ms": rng.normal(0, 3),
                             "track_temp_c": 35.0, "tyre_life": 1, "season_2026": float(e % 2),
                             "speed_class": "low" if radius < 60 else ("medium" if radius < 140 else "high")})
    return pd.DataFrame(rows), (a, b)


def test_physics_fit_recovers_parameters():
    df, (a, b) = _corner_data()
    fa, fb = fit_physics(df)
    assert fa == pytest.approx(a, rel=0.05) and fb == pytest.approx(b, rel=0.15)


def test_cross_validation_is_grouped_by_event_and_conformal_is_calibrated():
    df, _ = _corner_data()
    rep = cross_validate(df)
    folds = rep.oof.groupby("event_key")["fold"].nunique()
    assert (folds == 1).all()  # no event is split across folds
    m = rep.metrics.set_index("model")
    assert m.loc["hybrid", "rmse_kmh"] < m.loc["physics", "rmse_kmh"]
    assert 0.85 <= rep.conformal_coverage <= 0.96
    assert "v_min_kmh" not in NUMERIC_FEATURES  # no target leakage into features
    deficit = team_corner_deficit(rep.oof).groupby("team")["deficit_kmh"].mean()
    assert deficit["Aston Martin"] == pytest.approx(-2.0 * 5 / 6, abs=0.8)


def test_exact_shapley_linear_model_and_efficiency():
    rng = np.random.default_rng(5)
    x = rng.normal(size=(20, 4))
    base = x.mean(0)
    w = np.array([1.0, -2.0, 0.5, 3.0])
    phi = exact_baseline_shapley(lambda z: z @ w, x, base, [[0], [1], [2], [3]])
    assert np.allclose(phi, (x - base) * w)

    def f(z):
        return np.sin(z[:, 0]) * z[:, 1] + z[:, 2] ** 2 + z[:, 0] * z[:, 3]

    phi = exact_baseline_shapley(f, x, base, [[0], [1], [2], [3]])
    assert np.allclose(phi.sum(1), f(x) - f(base[None, :]))
    phi_g = exact_baseline_shapley(f, x, base, [[0, 3], [1], [2]])
    assert np.allclose(phi_g.sum(1), f(x) - f(base[None, :]))


def test_grip_matched_params_hit_both_reference_points():
    from amr_aerotwin.domain import GRAVITY_ACCEL as G
    from amr_aerotwin.physics.lapsim import VehicleParams
    from amr_aerotwin.pipeline.season import grip_matched_params

    base = VehicleParams(800, 4.5, 1.3, 1.8, 600e3, 1.2)

    def grip(p, q):
        return p.mu * (G + q * p.cla_m2 / p.mass_kg)

    new, clamped = grip_matched_params(base, 0.97, 0.90, 800.0, 3500.0)
    assert not clamped
    assert grip(new, 800.0) / grip(base, 800.0) == pytest.approx(0.97, rel=1e-9)
    assert grip(new, 3500.0) / grip(base, 3500.0) == pytest.approx(0.90, rel=1e-9)
    same, _ = grip_matched_params(base, 1.0, 1.0, 800.0, 3500.0)
    assert same.mu == pytest.approx(base.mu) and same.cla_m2 == pytest.approx(base.cla_m2)


def test_effective_drag_is_recovered_from_a_top_speed_gap():
    from amr_aerotwin.physics.lapsim import VehicleParams, simulate_lap
    from amr_aerotwin.pipeline.season import _straight_peaks_kmh, _with_drag, match_drag_to_top_speed
    from conftest import stadium_track

    s, k, *_, length = stadium_track(straight_m=900.0, radius_m=60.0)
    base = VehicleParams(800, 4.5, 1.3, 1.8, 600e3, 1.2)
    v0 = _straight_peaks_kmh(simulate_lap(s, k, base, None, length).speed_ms, k, 5.0)
    v1 = _straight_peaks_kmh(simulate_lap(s, k, _with_drag(base, 0.25), None, length).speed_ms, k, 5.0)
    assert v1 < v0
    assert match_drag_to_top_speed(base, s, k, None, length, v1 - v0) == pytest.approx(0.25, abs=0.01)
