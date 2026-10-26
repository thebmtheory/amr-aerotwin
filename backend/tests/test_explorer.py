"""Per-track data behind the report's track views, on the real Silverstone 2025 fixture."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from amr_aerotwin.modeling.validation import WHEEL_GPS_TOL_KMH, flag_corner_speeds
from amr_aerotwin.pipeline.event import process_event
from amr_aerotwin.report.explorer import (
    SECTIONS,
    explorer_event,
    full_throttle_speed_loss,
    js_assign,
    no_telemetry_reason,
    slug,
)


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


def test_reasons_and_names_for_the_page():
    w = ["ALO failed data checks: {'frozen_run_m': 138.7, 'car_data_stall_kmh': 61.0}", "STR: no telemetry file"]
    assert no_telemetry_reason("ALO", w) == "failed data checks: frozen telemetry, car-data stall"
    assert no_telemetry_reason("STR", w) == "no usable telemetry"
    assert no_telemetry_reason("HUL", w) == "no usable telemetry"
    assert slug("São Paulo Grand Prix") == "s-o-paulo-grand-prix"


@pytest.fixture(scope="module")
def track(fixture_repo):
    out = process_event(fixture_repo, 2025, "British Grand Prix", 12, run_mcmc=False)
    index, detail = explorer_event(out.summary, out.timing_rows, out.section_rows, fixture_repo)
    return out, index, detail


def test_each_drivers_sections_add_up_to_the_gap_to_the_reference_lap(track):
    _, index, detail = track
    assert sorted(index["drivers"]) == ["ALO", "STR"]
    ref = index["reference"]["lap_time_s"]
    for d, x in detail["drivers"].items():
        assert sum(x["sections_s"].values()) == pytest.approx(x["lap_time_s"] - ref, abs=1e-6), d
        # Corner windows do not overlap, so the corners add up to the three corner classes
        corners = sum(c["total_s"] for c in x["corners"])
        assert corners == pytest.approx(sum(x["sections_s"][k] for k in ("high", "medium", "low")), abs=1e-9), d
        assert index["drivers"][d]["sections_s"] == x["sections_s"]


def test_the_page_rule_for_the_team_lap_matches_the_season_table(track):
    # The page represents Aston Martin by the faster passing lap of the selected drivers; with
    # both selected that must be exactly the row the season analysis uses
    out, index, _ = track
    fast = min(index["drivers"], key=lambda d: index["timing"][d]["lap_time_s"])
    team = index["team_sections_s"]["Aston Martin"]
    assert all(team[k] == pytest.approx(index["drivers"][fast]["sections_s"][k], abs=1e-9) for k in SECTIONS)
    assert index["team_sections_s"][index["reference"]["team"]] == {k: 0.0 for k in SECTIONS}
    # Same corner positions as the event build, so the reference lap's time per section is the
    # season table's to the last digit (the event summary's rounded markers are not used)
    ref_t = out.section_rows.drop_duplicates("section").set_index("section")["reference_time_s"]
    assert all(index["ref_time_s"][k] == pytest.approx(ref_t[k], abs=1e-12) for k in SECTIONS)


def test_timing_ranks_and_gaps_come_from_official_lap_times(track):
    out, index, _ = track
    tm = out.timing_rows.sort_values("lap_time_s").reset_index(drop=True)
    for d, r in index["timing"].items():
        assert r["gap_s"] == pytest.approx(r["lap_time_s"] - tm["lap_time_s"].min())
        assert tm.loc[r["rank"] - 1, "driver"] == d
        assert r["representative"] and r["telemetry"]
    assert index["team_position"] == 1 + sum(t < min(r["lap_time_s"] for r in index["timing"].values())
                                             for t in tm.groupby("team")["lap_time_s"].min())


def test_sums_count_only_corners_with_a_trusted_speed_and_whole_straights(track):
    _, index, detail = track
    n_class = {c: sum(x["speed_class"] == c for x in detail["corners"]) for c in ("high", "medium", "low")}
    for d, agg in index["drivers"].items():
        for c, v in agg["corner_class_kmh"].items():
            ok = [i for i, x in enumerate(detail["corners"]) if x["speed_class"] == c and detail["drivers"][d]["corners"][i]["ok"]]
            assert v["n"] == len(ok) <= n_class[c]
            expect = sum(detail["drivers"][d]["corners"][i]["min_kmh"] - detail["corners"][i]["field_median_kmh"] for i in ok)
            assert v["sum"] == pytest.approx(expect)
        assert agg["straights"]["n"] == len(detail["straights"])
        mean_peak = np.mean([s["drivers"][d]["peak_kmh"] - s["field"]["peak_kmh"] for s in detail["straights"]])
        assert agg["straights"]["peak_kmh"] / agg["straights"]["n"] == pytest.approx(mean_peak)


def test_detail_traces_share_the_distance_grid_and_write_as_strict_json(track):
    _, index, detail = track
    n = len(detail["distance_m"])
    assert len(detail["map"]["x"]) == len(detail["map"]["y"]) == n
    assert all(len(v) == n for v in detail["reference_trace"].values())
    for x in detail["drivers"].values():
        assert all(len(v) == n for v in x["trace"].values()) and len(x["loss_per_100m_s"]) == n
        assert x["trace"]["delta_s"][0] == 0.0
    names = [s["name"] for s in detail["straights"]]
    assert "Hangar Straight" in names and "Wellington Straight" in names
    for s in detail["straights"]:
        m = len(s["distance_m"])
        assert len(s["pole_kmh"]) == len(s["field_median_kmh"]) == m
        assert all(len(v["speed_kmh"]) == m for v in s["drivers"].values())
        assert np.all(np.asarray(s["field_min_kmh"]) <= np.asarray(s["field_max_kmh"]))
    for var, payload, key in (("EXPLORER", detail, index["key"]), ("EXPLORER_INDEX", {"events": [index]}, None)):
        js = js_assign(var, payload, key=key)
        body = js.split("=", 2)[-1] if key else js.split("=", 1)[1]
        data = json.loads(body.rstrip().rstrip(";"))
        assert "NaN" not in js and data


TRACKMATH = Path(__file__).resolve().parents[1] / "src" / "amr_aerotwin" / "report" / "static" / "trackmath.js"
# Runs the page's own arithmetic: rates for every team (each team's passing lap) and for Aston
# Martin (the faster passing lap of the given drivers) over a list of per-track entries
NODE_RATES = """
const TM = require(process.argv[1]); const fs = require("fs"); const vm = require("vm");
const a = JSON.parse(fs.readFileSync(process.argv[2]));
let evs = a.events;
if (a.index_js) { const ctx = { window: {} }; vm.runInNewContext(fs.readFileSync(a.index_js, "utf8"), ctx); evs = ctx.window.EXPLORER_INDEX.events; }
const out = {};
for (const y of a.seasons) {
  const ev = evs.filter(e => String(e.season) === String(y) && !e.wet);
  const teams = new Set(); ev.forEach(e => Object.keys(e.team_sections_s).forEach(k => teams.add(k)));
  out[y] = {};
  for (const t of teams) out[y][t] = TM.sumRates(ev, t === a.target ? TM.amrPick(a.drivers[y] || []) : TM.teamPick(t));
  // The same, on the tracks where the Aston Martin lap exists (the page's like-for-like comparison)
  const pick = TM.amrPick(a.drivers[y] || []), same = ev.filter(e => pick(e));
  out[y]._same = {};
  for (const t of teams) out[y]._same[t] = TM.sumRates(same, t === a.target ? pick : TM.teamPick(t));
}
process.stdout.write(JSON.stringify(out));
"""


def _node_rates(tmp_path, payload):
    (tmp_path / "in.json").write_text(json.dumps(payload))
    run = subprocess.run(["node", "-e", NODE_RATES, str(TRACKMATH), str(tmp_path / "in.json")], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_arithmetic_matches_the_season_tables_on_the_fixture(track, tmp_path):
    out, index, _ = track
    got = _node_rates(tmp_path, {"events": [index], "seasons": [2025], "target": "Aston Martin", "drivers": {"2025": ["ALO", "STR"]}})["2025"]
    sec = out.section_rows
    for team, g in sec.groupby("team"):
        loss, ref = g.set_index("section")["loss_s"], g.set_index("section")["reference_time_s"]
        r = got[team]
        assert r["n"] == 1
        assert r["straights"] == pytest.approx(100 * loss["straights"] / ref["straights"], rel=1e-12), team
        corners = ["high", "medium", "low"]
        assert r["corners"] == pytest.approx(100 * loss[corners].sum() / ref[corners].sum(), rel=1e-12), team


SITE_INDEX = Path(__file__).resolve().parents[2] / "site" / "data" / "explorer" / "index.js"
SEASON_JSON = Path(__file__).resolve().parents[2] / "data" / "processed" / "season.json"


@pytest.mark.skipif(shutil.which("node") is None or not SITE_INDEX.exists() or not SEASON_JSON.exists(),
                    reason="needs node and a built report (make report)")
def test_page_arithmetic_reproduces_the_season_rates_for_every_team(tmp_path):
    # With both drivers and every dry track selected, the track views must give the season
    # analysis's loss rates (season.json keeps 4 decimals), for every team in both seasons
    season = json.loads(SEASON_JSON.read_text())
    rates = season["section_rates"]
    got = _node_rates(tmp_path, {"index_js": str(SITE_INDEX), "seasons": sorted(rates), "target": "Aston Martin",
                                 "drivers": {y: ["ALO", "STR"] for y in rates}})
    checked = 0
    for y, vf in season["straight_vs_field"].items():  # the headline ratio, on the same tracks
        same = got[y]["_same"]
        assert same[vf["next_team"]]["straights"] == pytest.approx(vf["next_rate_pct"], abs=1e-4), y
        assert same["Aston Martin"]["straights"] / same[vf["next_team"]]["straights"] == pytest.approx(vf["ratio"], abs=1e-3), y
    for y, teams in rates.items():
        for team, r in teams.items():
            g = got[y][team]
            assert g["n"] == r["n_events"], (y, team)
            for sec_name, v in zip(r["sections"], r["rate_pct"]):
                assert g[sec_name] == pytest.approx(v, abs=1e-4), (y, team, sec_name)
            if "corner_rate_pct" in r:
                assert g["corners"] == pytest.approx(r["corner_rate_pct"], abs=1e-4), (y, team)
            checked += 1
    assert checked >= 20
