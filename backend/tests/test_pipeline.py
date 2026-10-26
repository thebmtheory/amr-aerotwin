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
