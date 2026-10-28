"""GP lap-time emulator: held-out accuracy, interval coverage, Sobol indices, seeds and outputs."""

import json
from pathlib import Path

import numpy as np
import pytest
from amr_aerotwin.modeling.intervals import INTERVAL_Z
from amr_aerotwin.modeling.surrogate import (
    PARAMS,
    build_emulator,
    lap_time_emulator,
    latin_hypercube,
    linear_changes,
    scaled_car,
    simulated_lap_times,
    sobol_first_order,
)
from amr_aerotwin.physics.lapsim import VehicleParams, lap_time_sensitivities
from amr_aerotwin.pipeline.season import SURROGATE_ROW_KEYS, surrogate_summary
from conftest import stadium_track

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"
CAR = VehicleParams(mass_kg=800.0, cla_m2=4.5, cda_m2=1.3, mu=1.8, power_w=700e3, rho_kg_m3=1.2,
                    long_grip_scale=0.85, low_drag_cda_m2=0.9)
TEST_LISTS = ("test_sim_s", "test_gp_s", "test_gp_sd_s", "test_linear_s")
SUMMARY_KEYS = {"params", "half_range", "n_train", "n_test", "base_lap_time_s", "spread_s", "rmse_s", "max_abs_err_s",
                "coverage90", "linear_rmse_s", "linear_max_abs_err_s", "sobol_first", "length_scales",
                "test_factors", *TEST_LISTS}


@pytest.fixture(scope="module")
def track():
    """Stadium with varying curvature, so corner, traction and braking limits all occur, and a low-drag
    mode on the straights, so the low-drag CdA is scaled too. 10 m grid to keep the runs cheap."""
    s, k, *_, length = stadium_track(step_m=10.0)
    k = k * (1 + 0.3 * np.sin(s / 90.0))
    mask = k == 0
    return s, k, mask, length, lap_time_sensitivities(s, k, CAR, mask, length)


@pytest.fixture(scope="module")
def emu(track):
    s, k, mask, length, sens = track
    return build_emulator(s, k, CAR, mask, length, sens, seed=0)


def test_low_drag_cda_moves_with_cda_only():
    p = scaled_car(CAR, {"cda_m2": 1.1, "mu": 0.9})
    assert (p.cda_m2, p.low_drag_cda_m2, p.mu) == pytest.approx((1.43, 0.99, 1.62))
    assert scaled_car(CAR, {"cla_m2": 1.1}).low_drag_cda_m2 == CAR.low_drag_cda_m2
    assert scaled_car(VehicleParams(800.0, 4.5, 1.3, 1.8, 700e3), {"cda_m2": 1.1}).low_drag_cda_m2 is None


def test_designs_are_latin_hypercubes_in_the_box_and_independent():
    a, b = latin_hypercube(60, [0, 1]), latin_hypercube(60, [0, 2])
    assert a.shape == (60, len(PARAMS)) and a.min() >= 0.85 and a.max() <= 1.15
    for j in range(len(PARAMS)):  # one run in each of the 60 equal slices of every factor
        assert sorted(np.floor((a[:, j] - 0.85) / 0.30 * 60).astype(int)) == list(range(60))
    assert np.abs(a - b).max() > 0.1


def test_linear_surrogate_is_first_order(track):
    """Within +-0.5% the 1% sensitivities predict the simulator; over +-15% they miss by far more."""
    s, k, mask, length, sens = track
    base = simulated_lap_times(np.ones((1, 4)), s, k, CAR, mask, length)[0]
    errs = []
    for h in (0.005, 0.15):
        f = latin_hypercube(30, [5, 1], half_range=h)
        dt = simulated_lap_times(f, s, k, CAR, mask, length) - base
        errs.append(np.max(np.abs(linear_changes(f, sens) - dt)) / np.max(np.abs(dt)))
    assert errs[0] < 0.01 < 0.05 < errs[1]


def test_emulator_reproduces_the_simulator_on_held_out_runs(emu, track):
    s, k, mask, length, _ = track
    direct = simulated_lap_times(emu.test_factors[:3], s, k, CAR, mask, length) - emu.base_lap_time_s
    assert np.allclose(direct, emu.test_dt_s[:3], atol=1e-12)  # the held-out targets are simulator runs
    out = emu.summary()
    assert out["spread_s"] > 0.5  # the box moves the lap by seconds, so the check is not trivial
    assert out["rmse_s"] < 0.02 * out["spread_s"]
    assert out["max_abs_err_s"] < 0.06 * out["spread_s"]
    assert out["rmse_s"] < 0.2 * out["linear_rmse_s"]  # the curvature the linear surrogate misses is captured


def test_predictive_interval_coverage_is_sensible(track):
    """90% intervals from 60 runs are roughly calibrated on average over ten designs, and stay narrow."""
    s, k, mask, length, sens = track
    # One design can come out too narrow when its runs miss the kinks where track points switch between
    # grip-limited and flat out, so the band is checked on the mean over ten designs
    fits = [build_emulator(s, k, CAR, mask, length, sens, seed=sd, sobol_log2_n=6) for sd in range(10)]
    cov = [f.summary()["coverage90"] for f in fits]
    assert 0.75 <= np.mean(cov) <= 0.97
    assert max(cov) - min(cov) > 0.1  # one design's coverage is a noisy figure
    assert all(np.mean(f.test_sd_s) < 0.02 * np.std(f.test_dt_s) for f in fits)


def test_sobol_estimator_recovers_known_indices():
    """Additive: S_i = a_i^2 / sum(a^2). With an interaction, u1 (1 + u2) gives S = (0.75, 0, 0, 0)."""
    h = 0.15
    a = np.array([3.0, 2.0, 1.0, 0.5])
    s_add = sobol_first_order(lambda f: ((f - 1) / h) @ a, h, log2_n=12, seed=1)
    assert s_add == pytest.approx(a**2 / np.sum(a**2), abs=0.01)
    s_int = sobol_first_order(lambda f: (f[:, 0] - 1) / h * (1 + (f[:, 1] - 1) / h), h, log2_n=12, seed=1)
    assert s_int == pytest.approx([0.75, 0.0, 0.0, 0.0], abs=0.02)


def test_sobol_indices_are_variance_shares_and_match_the_simulator(emu, track):
    s1 = emu.sobol_first
    assert np.all(s1 >= 0) and s1.sum() <= 1.01
    assert PARAMS[int(np.argmax(s1))] == "mu"  # grip dominates a track that is mostly corners
    # The same indices computed with the simulator itself (2^9 base points, 2,560 runs)
    s, k, mask, length, _ = track
    direct = sobol_first_order(lambda f: simulated_lap_times(f, s, k, CAR, mask, length), log2_n=9, seed=[0, 3])
    assert s1 == pytest.approx(direct, abs=0.02)


def test_same_seed_gives_identical_results(track):
    s, k, mask, length, sens = track
    a = lap_time_emulator(s, k, CAR, mask, length, sens, seed=7)
    b = lap_time_emulator(s, k, CAR, mask, length, sens, seed=7)
    assert a == b and json.dumps(a) == json.dumps(b)
    assert lap_time_emulator(s, k, CAR, mask, length, sens, seed=8)["test_factors"] != a["test_factors"]


def test_summary_is_json_ready_and_lists_the_held_out_runs_in_order(emu):
    out = emu.summary()
    assert set(out) == SUMMARY_KEYS
    json.dumps(out, allow_nan=False)
    n = out["n_test"]
    assert (n, out["n_train"], out["half_range"], out["params"]) == (60, 60, 0.15, list(PARAMS))
    assert list(out["sobol_first"]) == list(PARAMS) == list(out["length_scales"])
    assert len(out["test_factors"]) == n and all(len(out[k]) == n for k in TEST_LISTS)
    assert all(len(r) == 4 and all(0.85 <= v <= 1.15 and v == round(v, 3) for v in r) for r in out["test_factors"])
    assert all(v == round(v, 4) for k in TEST_LISTS for v in out[k])
    assert np.allclose(out["test_factors"], emu.test_factors, atol=5e-4)
    # Same order and length: the rounded lists reproduce the summary statistics
    sim, gp, sd, lin = (np.array(out[k]) for k in TEST_LISTS)
    assert np.sqrt(np.mean((gp - sim) ** 2)) == pytest.approx(out["rmse_s"], abs=1e-4)
    assert np.max(np.abs(gp - sim)) == pytest.approx(out["max_abs_err_s"], abs=1e-4)
    assert np.sqrt(np.mean((lin - sim) ** 2)) == pytest.approx(out["linear_rmse_s"], abs=1e-4)
    assert np.max(np.abs(lin - sim)) == pytest.approx(out["linear_max_abs_err_s"], abs=1e-4)
    assert np.std(sim, ddof=1) == pytest.approx(out["spread_s"], abs=1e-4)
    assert np.mean(np.abs(gp - sim) <= INTERVAL_Z * sd) == pytest.approx(out["coverage90"], abs=2 / n)


def _event(season, rnd, car, rmse, lin, cov, spread, sobol):
    return {"season": season, "round": rnd, "event": f"Round {rnd} Grand Prix", "surrogate": {
        "car": car, "params": list(PARAMS), "half_range": 0.15, "n_train": 60, "n_test": 60, "base_lap_time_s": 90.0,
        "spread_s": spread, "rmse_s": rmse, "max_abs_err_s": 3 * rmse, "coverage90": cov, "linear_rmse_s": lin,
        "linear_max_abs_err_s": 3 * lin, "sobol_first": dict(zip(PARAMS, sobol)),
        "length_scales": dict(zip(PARAMS, (1.0, 2.0, 3.0, 2.0)))}}


def test_season_summary_medians_counts_and_rows():
    events = {
        "c": _event(2026, 9, "STR", 0.03, 0.6, 0.85, 3.5, (0.6, 0.1, 0.1, 0.2)),
        "a": _event(2026, 2, "ALO", 0.01, 0.4, 0.95, 3.0, (0.8, 0.05, 0.05, 0.1)),
        "b": _event(2026, 5, "ALO", 0.50, 0.3, 0.70, 2.5, (0.7, 0.1, 0.05, 0.15)),
        "d": _event(2025, 1, "ALO", 0.02, 0.5, 0.90, 3.0, (0.7, 0.1, 0.05, 0.15)),
        "e": {"season": 2025, "round": 3, "event": "No calibrated car"},
    }
    out = surrogate_summary(events)
    assert list(out) == ["2025", "2026"] and out["2025"]["n_events"] == 1
    s26 = out["2026"]
    assert s26["n_events"] == 3 and (s26["n_train"], s26["n_test"], s26["half_range"]) == (60, 60, 0.15)
    assert (s26["rmse_s"], s26["linear_rmse_s"], s26["coverage90"], s26["spread_s"]) == (0.03, 0.4, 0.85, 3.0)
    assert (s26["max_abs_err_s"], s26["linear_max_abs_err_s"]) == pytest.approx((0.09, 1.2))
    assert s26["n_gp_rmse_below_linear"] == 2  # round 5 is the one where the emulator does worse
    assert s26["sobol_first"] == pytest.approx({"mu": 0.7, "cla_m2": 0.0833, "cda_m2": 0.0667, "power_w": 0.15}, abs=1e-4)
    lo, hi = s26["coverage90_mean_ci90"]
    assert s26["coverage90_mean"] == pytest.approx(0.8333, abs=1e-4) and lo < 0.8333 < hi
    rows = s26["events"]
    assert [r["round"] for r in rows] == [2, 5, 9]
    for r in rows:
        e = next(e for e in events.values() if e["season"] == 2026 and e["round"] == r["round"])
        assert set(r) == {"event", "round", "car", *SURROGATE_ROW_KEYS}
        assert (r["event"], r["car"]) == (e["event"], e["surrogate"]["car"])
        assert all(r[k] == e["surrogate"][k] for k in SURROGATE_ROW_KEYS)


def _season_block(n, rmse, lin, cov, ci, sobol):
    rows = [{"event": f"Round {i + 1} Grand Prix", "round": i + 1, "car": "ALO", "rmse_s": rmse, "linear_rmse_s": lin,
             "max_abs_err_s": 3 * rmse + 0.001 * i, "coverage90": cov - 0.02 * i, "spread_s": 3.0} for i in range(n)]
    return {"n_events": n, "n_train": 60, "n_test": 60, "half_range": 0.15, "rmse_s": rmse, "max_abs_err_s": 3 * rmse,
            "coverage90": cov, "coverage90_mean": cov, "coverage90_mean_ci90": ci, "linear_rmse_s": lin,
            "linear_max_abs_err_s": 3 * lin, "spread_s": 3.0, "sobol_first": dict(zip(PARAMS, sobol)),
            "n_gp_rmse_below_linear": n, "events": rows}


def test_note_paragraph_is_worded_from_the_results():
    from amr_aerotwin.report.note import emulator_paragraph

    s = {"surrogate_summary": {"2025": _season_block(3, 0.02, 0.41, 0.88, [0.85, 0.91], (0.7, 0.07, 0.05, 0.18)),
                               "2026": _season_block(4, 0.01, 0.45, 0.85, [0.82, 0.88], (0.75, 0.07, 0.05, 0.13))}}
    p = emulator_paragraph(s)
    assert "fitted at each event to 60 simulator runs" in p and "each within ±15%" in p and "tested on 60 independent runs" in p
    assert "median RMS error is 0.010 s in 2026 (4 events) and 0.020 s in 2025 (3 events)" in p
    assert "85% of held-out runs in 2026 [82, 88], fewer than the nominal 90%, so the intervals are somewhat too narrow" in p
    assert "in 2025, 88% [85, 91], in line with the nominal 90%" in p
    assert "the lowest is 79% (the 2026 Round 4 Grand Prix)" in p and "0.062 s at most (the 2025 Round 3 Grand Prix)" in p
    assert "lower at every event of both seasons, by a factor of 20 or more" in p  # smallest ratio 0.41 / 0.02 = 20.5
    assert "μ 75%, power 13%, C<sub>L</sub>A 7% and C<sub>D</sub>A 5% of the 2026 lap-time variance" in p
    assert "almost additively" in p and "mainly the curvature" in p and "n/a" not in p
    # The words follow the data: losses to the linear surrogate, wide intervals and interactions change them
    s["surrogate_summary"]["2026"].update(n_gp_rmse_below_linear=3, coverage90_mean=0.97, coverage90_mean_ci90=[0.95, 0.99],
                                          sobol_first=dict(zip(PARAMS, (0.5, 0.1, 0.05, 0.1))))
    p = emulator_paragraph(s)
    assert "lower at 3 of 4 events in 2026 and at 3 of 3 events in 2025" in p
    assert "97% of held-out runs in 2026 [95, 99], more than the nominal 90%, so the intervals are conservative" in p
    assert "remaining 25.0% in 2026 and under 0.1% in 2025, so the four parameters act far from additively" in p
    assert "curvature" not in p
    assert emulator_paragraph({}).startswith("**Lap-time emulator.**")


@pytest.mark.skipif(not (PROCESSED / "season.json").exists(), reason="needs make build and make analyse")
def test_processed_outputs_carry_the_emulator_and_season_rows_match_the_events():
    season = json.loads((PROCESSED / "season.json").read_text())
    events = [json.loads(p.read_text()) for p in sorted((PROCESSED / "events").glob("*.json"))]
    dry = [e for e in events if not e.get("wet_session") and e.get("surrogate")]
    assert dry and set(season["surrogate_summary"]) == {str(e["season"]) for e in dry}
    for e in dry:
        sg = e["surrogate"]
        assert set(sg) == SUMMARY_KEYS | {"car"} and sg["car"] == e["iso_lap_time"]["car"]
        assert all(len(sg[k]) == sg["n_test"] for k in (*TEST_LISTS, "test_factors"))
    for yr, block in season["surrogate_summary"].items():
        evs = sorted((e for e in dry if str(e["season"]) == yr), key=lambda e: e["round"])
        assert block["n_events"] == len(evs) == len(block["events"])
        for row, e in zip(block["events"], evs):
            assert (row["event"], row["round"], row["car"]) == (e["event"], e["round"], e["surrogate"]["car"])
            assert all(row[k] == e["surrogate"][k] for k in SURROGATE_ROW_KEYS)
