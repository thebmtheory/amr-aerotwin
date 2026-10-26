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
    changepoint_count_evidence,
    log_marginal_likelihood,
    permutation_mde_sd,
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


def test_model_averaged_step_includes_the_no_change_possibility():
    rng = np.random.default_rng(5)
    y = np.concatenate([np.full(9, 1.3), np.full(9, 1.05)]) + rng.normal(0, 0.15, 18)  # a small, uncertain step
    cp = bayesian_changepoint(y)
    w0 = cp.p_no_change
    # Averaging over "no change" shrinks the step toward zero by about P(no change)
    assert abs(cp.effect_avg_pct) < abs(cp.effect_mean_pct)
    assert cp.effect_avg_pct == pytest.approx((1 - w0) * cp.effect_mean_pct, abs=0.03)
    assert cp.effect_avg_ci90_pct[1] >= cp.effect_ci90_pct[1] - 1e-9


def test_two_changes_beat_one_for_a_mid_season_peak_but_not_for_a_step():
    rng = np.random.default_rng(6)
    peak = np.concatenate([np.full(6, 4.0), np.full(5, 5.5), np.full(6, 3.8)]) + rng.normal(0, 0.2, 17)
    c = changepoint_count_evidence(peak)
    assert c["bf_two_vs_one"] > 3 and c["map_pair_index"] == [6, 11]
    up, down = c["map_pair_steps"]
    assert up > 1.0 and down < -1.0
    step = np.concatenate([np.full(9, 4.0), np.full(8, 3.0)]) + rng.normal(0, 0.2, 17)
    # A single step gives no strong case for two (the report mentions two changes only above 3)
    assert changepoint_count_evidence(step)["bf_two_vs_one"] < 3


def test_permutation_mde_needs_more_than_normal_theory_with_few_placebos():
    assert permutation_mde_sd(8) == float("inf")  # 1/(1+8) > 0.10: the 10% level is unreachable
    m9, m10, m200 = permutation_mde_sd(9), permutation_mde_sd(10), permutation_mde_sd(200)
    assert 2.6 < m9 < 3.0 and 2.6 < m10 < 3.0
    assert m200 == pytest.approx(2.49, abs=0.05)  # 1.645 + 0.842 in the limit
    # Check by simulation: an effect of m10 sd is detected about 80% of the time against 10 placebos
    rng = np.random.default_rng(0)
    e = rng.normal(m10, 1.0, 4000)
    pl = np.abs(rng.normal(0, 1, (4000, 10)))
    p = (1 + (pl >= np.abs(e)[:, None]).sum(1)) / 11
    assert np.mean(p <= 0.10) == pytest.approx(0.80, abs=0.03)


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
                rows.append({"event_key": f"E{e}", "circuit": f"Circuit{e // 2}", "corner_key": f"C{c}", "circuit_corner": f"E{e}C{c}",
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


def test_cross_validation_is_grouped_by_circuit_and_conformal_is_calibrated():
    df, _ = _corner_data()
    rep = cross_validate(df)
    # Events come in pairs at the same circuit (2025 and 2026): a circuit, not just an event,
    # must never be split across folds, or the same corners would be in train and test
    circuit_of = df.drop_duplicates("event_key").set_index("event_key")["circuit"]
    assert (rep.oof.assign(c=rep.oof["event_key"].map(circuit_of)).groupby("c")["fold"].nunique() == 1).all()
    assert rep.oof["fold"].nunique() > 1
    assert (rep.oof.groupby("event_key")["fold"].nunique() == 1).all()
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


def test_straight_vs_field_compares_every_team_on_the_targets_tracks():
    from amr_aerotwin.pipeline.season import straight_vs_field

    rows = []
    # Six events; the target has no passing lap at the last two, where the rival loses a lot.
    # Summed over the rival's own events its rate would be 2.8%; on the target's four, 2%.
    for rnd in range(1, 7):
        for team, loss in (("AMR", 0.4 if rnd <= 4 else None), ("RIV", 0.2 if rnd <= 4 else 0.6), ("OTH", 0.1)):
            if loss is not None:
                rows.append({"season": 2026, "round": rnd, "team": team, "section": "straights", "loss_s": loss, "reference_time_s": 10.0})
    out = straight_vs_field(pd.DataFrame(rows), "AMR", ["RIV", "OTH"], n_boot=400, seed=3, season=2026)
    assert out["n_events"] == 4 and out["next_team"] == "RIV"
    assert out["next_rate_pct"] == pytest.approx(2.0) and out["target_rate_pct"] == pytest.approx(4.0)
    assert out["ratio"] == pytest.approx(2.0)
    # Paired draws of identical events: every draw gives the same ratio
    assert out["ratio_ci90"][0] == pytest.approx(2.0) and out["ratio_ci90"][1] == pytest.approx(2.0)
