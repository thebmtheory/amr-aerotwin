"""End-to-end event processing on the real Silverstone 2025 fixture (offline)."""

import json

import numpy as np
import pytest
from amr_aerotwin.pipeline.event import process_event


@pytest.fixture(scope="module")
def silverstone(fixture_repo):
    return process_event(fixture_repo, 2025, "British Grand Prix", 12, run_mcmc=False)


def test_event_summary_is_json_serialisable_and_complete(silverstone):
    s = silverstone.summary
    json.dumps(s, allow_nan=True)
    from amr_aerotwin.pipeline.event import _r

    json.dumps(_r(s, 6), allow_nan=False)  # what the build writes: strict JSON
    for key in ("comparison", "lapsim", "pod", "energy", "map", "corners", "team_table", "data_checks", "sandbox"):
        assert key in s, key
    assert s["geometry_ok"] and abs(abs(s["turning_number"]) - 1) < 0.035


def test_comparison_closes_on_the_official_gap(silverstone):
    c = silverstone.summary["comparison"]
    rows = silverstone.driver_rows.set_index("driver")
    official = rows.loc[c["target"], "lap_time_s"] - rows.loc[c["reference"], "lap_time_s"]
    assert c["total_delta_s"] == pytest.approx(official, abs=1e-6)
    parts = sum(r["time_s"] for r in c["class_summary"])
    assert parts == pytest.approx(official, abs=1e-3)


def test_lap_sim_calibration_on_real_lap_is_within_half_a_second(silverstone):
    for d, ls in silverstone.summary["lapsim"].items():
        assert abs(ls["lap_time_error_s"]) < 0.5, d
        assert ls["rmse_kmh"] < 20, d
        assert ls["sensitivities"]["cla_m2_plus_1pct_s"] < 0 < ls["sensitivities"]["cda_m2_plus_1pct_s"]


def test_tables_have_expected_rows(silverstone):
    assert silverstone.driver_rows["passed_checks"].sum() >= 8
    assert {"grip_low_g", "grip_high_g", "straight_speed_delta_kmh"} <= set(silverstone.team_rows.columns)
    t = silverstone.team_rows.dropna(subset=["grip_high_g"])
    assert (t["grip_high_g"] > t["grip_low_g"]).all()  # aero grip grows with speed
    assert len(silverstone.corner_rows) > 100
    assert not silverstone.accel_rows.empty
    assert np.isfinite(silverstone.corner_rows["radius_m"]).all()


def test_round_helper_cleans_nested_dicts():
    from amr_aerotwin.pipeline.event import _r

    out = _r({"a": [1.23456, float("nan")], "b": {"c": np.float64(2.5e-7), "d": (1, 2)}}, 3)
    assert out == {"a": [1.235, None], "b": {"c": 0.0, "d": [1, 2]}}


def test_season_build_writes_outputs_and_isolates_failures(tmp_path, fixture_repo):
    import shutil

    from amr_aerotwin.pipeline.season import build

    cache = tmp_path / "cache"
    shutil.copytree(fixture_repo.cache_dir, cache)
    # A listed event with no files must be skipped, not crash the build
    (cache / "2025__events.json").write_text(json.dumps(["British Grand Prix", "Nowhere Grand Prix"]))
    out = tmp_path / "processed"
    tables = build([2025], cache, out, processes=1, run_mcmc=False)
    assert (out / "events" / "2025-british-grand-prix.json").exists()
    assert not (out / "events.partial").exists()
    json.loads((out / "events" / "2025-british-grand-prix.json").read_text())
    assert len(tables["drivers"]) >= 8 and not tables["accel"].empty


def test_timing_table_keeps_every_driver_even_without_telemetry(silverstone, fixture_repo):
    from amr_aerotwin.data.repository import fastest_valid_lap

    laps = fixture_repo.session_laps(2025, "British Grand Prix", "Qualifying")
    expected = {d for d in laps["drv"].dropna().unique() if fastest_valid_lap(laps, d) is not None}
    assert set(silverstone.timing_rows["driver"]) == expected
    # the fastest timed lap is the reference for gaps, whatever happened to telemetry
    assert silverstone.timing_rows["lap_time_s"].min() == pytest.approx(laps.loc[~laps["del"], "time"].min())


def test_wind_rotation_test_output_shape(silverstone):
    wt = silverstone.summary["wind_rotation_test"]
    if wt is None:  # calm session: the test is skipped by design
        return
    rel = wt["relative_sse"]
    assert len(rel) == 12 and all(v > 0 for v in rel.values())
    assert wt["best_rotation_deg"] in {int(k) for k in rel}


def test_section_rates_recover_known_rates_and_target_ratio():
    """Synthetic events with known loss rates: rates are recovered, a uniform deficit gives a
    straights/corners ratio of 1, and the target-vs-field ratio interval covers the truth."""
    import pandas as pd
    from amr_aerotwin.pipeline.season import section_rate_summary

    rng = np.random.default_rng(3)
    truth = {"Aston Martin": (0.03, 0.04), "Uniform": (0.02, 0.02), "Rival": (0.04, 0.01)}  # (corners, straights)
    rows = []
    for rnd in range(1, 13):
        ref = {"low": 20.0 + rnd, "medium": 15.0, "high": 10.0, "straights": 35.0 + 2 * rnd}
        for team, (c, st) in truth.items():
            for sec, t in ref.items():
                rate = (st if sec == "straights" else c) * (1 + 0.05 * rng.standard_normal())
                rows.append({"season": 2026, "round": rnd, "team": team, "section": sec,
                             "loss_s": rate * t, "reference_time_s": t})
    rates, vs = section_rate_summary(pd.DataFrame(rows), n_boot=500, target="Aston Martin")
    r = rates["2026"]
    st = {t: r[t]["rate_pct"][r[t]["sections"].index("straights")] for t in truth}
    assert st["Aston Martin"] == pytest.approx(4.0, rel=0.05)
    assert r["Uniform"]["straight_to_corner_ratio"] == pytest.approx(1.0, abs=0.05)
    assert r["Rival"]["straight_to_corner_ratio"] == pytest.approx(0.25, abs=0.03)
    v = vs["2026"]
    assert v["next_team"] == "Uniform" and v["n_rivals"] == 2
    lo, hi = v["ratio_ci90"]
    assert lo < 2.0 < hi and v["ratio"] == pytest.approx(2.0, rel=0.08)
