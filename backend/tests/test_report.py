"""The browser lap simulator matches the Python one; the site builds from processed output."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from amr_aerotwin.physics.lapsim import VehicleParams, simulate_lap
from conftest import stadium_track

JS = Path(__file__).resolve().parents[1] / "src" / "amr_aerotwin" / "report" / "static" / "lapsim.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("low_drag", [False, True])
def test_javascript_lapsim_matches_python(tmp_path, low_drag):
    s, k, *_ , length = stadium_track(straight_m=700.0, radius_m=45.0)
    k = k * (1 + 0.3 * np.sin(s / 90.0))  # vary curvature so every limit is exercised
    p = VehicleParams(800.0, 4.6, 1.4, 1.85, 610e3, 1.17, long_grip_scale=0.82, low_drag_cda_m2=1.1 if low_drag else None)
    mask = (k == 0) if low_drag else None
    py = simulate_lap(s, k, p, mask, length)
    payload = {"d": s.tolist(), "k": k.tolist(), "p": p.__dict__, "mask": mask.tolist() if mask is not None else None, "L": length}
    (tmp_path / "in.json").write_text(json.dumps(payload))
    script = (
        f"const L=require({json.dumps(str(JS))});const fs=require('fs');"
        f"const a=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'in.json'))}));"
        "const r=L.simulateLap(a.d,a.k,a.p,a.mask,a.L);"
        "process.stdout.write(JSON.stringify({t:r.lapTime,v:Array.from(r.speed)}));"
    )
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert out["t"] == pytest.approx(py.lap_time_s, abs=1e-9)
    assert np.allclose(out["v"], py.speed_ms, atol=1e-9)


def test_site_builds_with_strict_json(tmp_path):
    from amr_aerotwin.report.build import build_site

    proc = tmp_path / "processed"
    (proc / "events").mkdir(parents=True)
    (proc / "season.json").write_text(json.dumps({"n_events": 1, "powertrain": {}, "value": float("nan")}))
    (proc / "events" / "2025-test.json").write_text(json.dumps({"season": 2025, "round": 1, "event": "Test Grand Prix",
                                                                  "geometry_ok": True, "circuit": {"location": "X"}}))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "test-grand-prix.html").write_text("<!doctype html><title>Aston Martin at Testville</title><p>x</p>")
    site = build_site(proc, tmp_path / "site", reports)
    for name in ("index.html", "page.html", "app.js", "app.css", "lapsim.js", "data/season.js", "data/events/2025-test.js",
                 "reports/test-grand-prix.html"):
        assert (site / name).exists(), name
    for page in ("index.html", "page.html"):  # the event report is linked from the season site's nav
        html = (site / page).read_text()
        assert '<a href="reports/test-grand-prix.html" class="nav-report">Testville report</a>' in html and "<!--EVENT_REPORTS-->" not in html
    assert not (site / "event_report.html").exists()
    text = (site / "data" / "season.js").read_text()
    assert "NaN" not in text and "window.SEASON=" in text and "window.MANIFEST=" in text
    assert "<!doctype html>" in (site / "index.html").read_text().lower()


def test_readme_blocks_are_generated_from_results(tmp_path):
    """README numbers come from season.json; text outside the markers is left alone."""
    from amr_aerotwin.report.note import update_readme

    rate = lambda st, c, lap, n=10: {"sections": ["high", "low", "medium", "straights"], "rate_pct": [c, c, c, st],  # noqa: E731
                                     "ci_lo": [0, 0, 0, 0], "ci_hi": [9, 9, 9, 9], "lap_rate_pct": lap, "n_events": n,
                                     "corner_rate_pct": c, "straight_to_corner_ratio": st / c}
    season = {
        "section_rates": {"2026": {"Aston Martin": rate(3.8, 4.1, 4.0), "Cadillac": rate(1.7, 5.0, 4.05), "Alpine": rate(0.5, 2.3, 1.8)},
                          "2025": {"Aston Martin": rate(0.3, 1.5, 1.2)}},
        "straight_vs_field": {"2026": {"next_team": "Cadillac", "next_rate_pct": 1.7, "ratio": 2.24, "ratio_ci90": [1.75, 2.86]}},
        "straight_profile": {"2026": {"Aston Martin": {"bins": [{"gap_kmh": -5.7}], "second_half_kmh": -3.0, "second_half_ci90": [-4.5, -1.5],
                                                       "n_straights": 6, "n_straights_losing_late": 5, "n_events": 5}}},
        "variance_split": {"2025": {"median_event_share": 0.51}, "2026": {"median_event_share": 0.94}},
        "data_quality": {"laps_passed": 717, "laps_total": 758},
        "skipped_events": [{"season": 2026, "event": "Chinese Grand Prix", "reason": "Only 0 laps passed checks"},
                           {"season": 2026, "event": "Spanish Grand Prix", "reason": "archive file unavailable at fetch time"}],
    }
    sj = tmp_path / "season.json"
    sj.write_text(json.dumps(season))
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- findings:start -->\nSTALE_TEXT\n<!-- findings:end -->\nmiddle\n<!-- gates:start -->\nSTALE_TEXT\n<!-- gates:end -->\nend\n")
    assert update_readme(sj, readme)
    text = readme.read_text()
    assert "STALE_TEXT" not in text and text.startswith("intro\n") and "middle" in text and text.endswith("end\n")
    assert "2.2 times as much, 90% interval 1.8 to 2.9" in text and "94%" in text and "51%" in text
    assert "717 of 758 laps pass" in text and "Chinese 2026" in text and "Spanish 2026" in text
    assert not update_readme(sj, readme)  # idempotent
    readme.write_text("no markers here\n")
    with pytest.raises(ValueError):
        update_readme(sj, readme)
