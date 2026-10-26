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
    site = build_site(proc, tmp_path / "site")
    for name in ("index.html", "page.html", "app.js", "app.css", "lapsim.js", "data/season.js", "data/events/2025-test.js"):
        assert (site / name).exists(), name
    text = (site / "data" / "season.js").read_text()
    assert "NaN" not in text and "window.SEASON=" in text and "window.MANIFEST=" in text
    assert "<!doctype html>" in (site / "index.html").read_text().lower()
