"""Single-event report: the checks and metrics it adds on top of the season pipeline."""

import json

import numpy as np
import pytest
from amr_aerotwin.modeling.validation import WHEEL_GPS_TOL_KMH, flag_corner_speeds
from amr_aerotwin.report.event_report import full_throttle_speed_loss, render_event_report, slug


def test_full_throttle_speed_loss_sees_a_fall_but_not_a_lift():
    v = np.concatenate([np.linspace(250, 300, 50), np.linspace(300, 290, 20)])
    flat_out = np.full(len(v), 100.0)
    assert full_throttle_speed_loss(v, flat_out) == pytest.approx(10.0)
    lifted = flat_out.copy()
    lifted[50:] = 0.0  # the same fall off throttle is braking or a lift, not lost drive power
    assert full_throttle_speed_loss(v, lifted) == pytest.approx(0.0)
    rising = np.linspace(250, 300, 70)  # drag limit: flattening, never falling
    assert full_throttle_speed_loss(rising, np.full(70, 100.0)) == pytest.approx(0.0)


def test_corner_speed_check_ignores_a_shared_gps_bias_and_flags_one_stuck_channel():
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(10)]
    # GPS reads 15 km/h low for every car at this corner (smoothing), plus a few km/h noise
    vmin = {t: [{"wheel_kmh": 250.0 + rng.normal(0, 3), "gps_kmh": 235.0 + rng.normal(0, 3)}] for t in teams}
    vmin["T3"][0]["wheel_kmh"] = 212.0  # stuck channel: wheel reads far below the GPS speed
    flag_corner_speeds(vmin)
    assert [t for t in teams if not vmin[t][0]["ok"]] == ["T3"]
    assert abs(vmin["T3"][0]["residual_kmh"]) > WHEEL_GPS_TOL_KMH


def test_render_embeds_strict_json_and_keeps_markup_safe():
    data = {"event": "British Grand Prix", "target": "Aston Martin", "note": "</script><b>", "x": float("nan"), "seasons": {}}
    page = render_event_report(data)
    assert "/*REPORT_DATA*/" not in page
    payload = page.split("window.REPORT = ", 1)[1].split(";</script>", 1)[0]
    parsed = json.loads(payload)
    assert parsed["x"] is None and parsed["note"] == "</script><b>"
    assert "</script><b>" not in payload  # escaped so it cannot close the script tag
    assert slug("São Paulo Grand Prix") == "s-o-paulo-grand-prix"
