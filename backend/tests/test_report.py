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
ROOT = Path(__file__).resolve().parents[2]


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
    (proc / "season.json").write_text(json.dumps({"n_events": 1, "powertrain": {}, "value": float("nan"),
                                                  "straight_vs_field": {"2026": {"ratio": 2.6, "ratio_ci90": [1.9, 3.4]}}}))
    (proc / "events" / "2025-test.json").write_text(json.dumps({"season": 2025, "round": 1, "event": "Test Grand Prix",
                                                                  "geometry_ok": True, "circuit": {"location": "X"}}))
    site = build_site(proc, tmp_path / "site")
    for name in ("index.html", "page.html", "app.js", "app.css", "lapsim.js", "trackmath.js", "favicon.svg",
                 "data/season.js", "data/events/2025-test.js"):
        assert (site / name).exists(), name
    for page in ("index.html", "page.html"):  # one report: the filter bar and the per-track data it reads
        html = (site / page).read_text()
        assert all(f'id="{i}"' in html for i in ("f-season", "f-drivers", "f-tracks", "tracks", "detail"))
        assert 'src="data/explorer/index.js"' in html and "reports/" not in html
    text = (site / "data" / "season.js").read_text()
    assert "NaN" not in text and "window.SEASON=" in text and "window.MANIFEST=" in text
    assert "<!doctype html>" in (site / "index.html").read_text().lower()
    # The headline is written from the results, not typed into the page
    for page in ("index.html", "page.html"):
        assert '<p class="deck">In 2026 Aston Martin loses time on the straights at about two and a half times the rate of any other team.</p>' \
            in (site / page).read_text(), page
    static = (JS.parent / "page.html").read_text()
    assert '<p class="deck"><!--headline--></p>' in static and "twice" not in static


def test_author_details_are_filled_in_from_one_place(tmp_path):
    """The byline at the top, the details at the foot and the page metadata all come from report.author."""
    import html
    import re
    import tomllib

    from amr_aerotwin.report.author import AUTHOR
    from amr_aerotwin.report.build import build_site

    proc = tmp_path / "processed"
    (proc / "events").mkdir(parents=True)
    (proc / "season.json").write_text("{}")
    site = build_site(proc, tmp_path / "site")
    static = (JS.parent / "page.html").read_text()
    filled = {"name": AUTHOR.name, "degree": AUTHOR.degree, "email": AUTHOR.email, "phone": AUTHOR.phone,
              "tel": AUTHOR.tel, "linkedin": AUTHOR.linkedin, "line": AUTHOR.line, "repo": AUTHOR.repo}
    for name, text in filled.items():
        assert f"<!--author-{name}-->" in static and text not in static, name
    assert re.fullmatch(r"\+\d{8,15}", AUTHOR.tel)  # a dialable tel: target
    name = html.escape(AUTHOR.name)
    for page in ("index.html", "page.html"):
        out = (site / page).read_text()
        assert "<!--author-" not in out and "<title>AMR Analysis</title>" in out
        assert re.search(r'<a class="byline" href="#author">.*?' + re.escape(name), out), page  # top right, jumps down
        foot = out[out.index('id="author"'):]
        assert f'id="author-name">{name}</h2>' in foot and html.escape(AUTHOR.line) in foot
        assert f'<p class="author-degree">{html.escape(AUTHOR.degree)}</p>' in foot
        assert f'data-copy="{html.escape(AUTHOR.email)}"' in foot and f'data-copy="{html.escape(AUTHOR.phone)}"' in foot
        assert f'href="tel:{AUTHOR.tel}">{html.escape(AUTHOR.phone)}</a>' in foot
        assert f'href="{AUTHOR.linkedin}" rel="noopener">{AUTHOR.linkedin_label}</a>' in foot
        assert f'href="{AUTHOR.repo}" rel="noopener">{AUTHOR.repo_label}</a>' in foot
        assert f'<meta name="author" content="{name}">' in out
    head = (site / "index.html").read_text().split("<body>")[0]
    assert '<link rel="icon" href="favicon.svg"' in head and f'content="{name}"' in head
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["authors"] == [{"name": AUTHOR.name, "email": AUTHOR.email}]


@pytest.mark.parametrize(("ratio", "ci90", "words"), [
    (2.02, [1.69, 2.52], "at about twice the rate of any other team."),
    (1.74, [1.3, 2.2], "at about one and a half times the rate of any other team."),
    (2.25, [1.8, 2.9], "at about two and a half times the rate of any other team."),
    (3.1, [2.2, 4.0], "at about three times the rate of any other team."),
    (1.2, [1.05, 1.4], "faster than any other team."),
    (1.6, [0.9, 2.4], "has the highest straight-line loss rate of any team, though not by a clear margin."),
    (0.8, [0.6, 1.1], "does not lose time on the straights faster than every other team."),
])
def test_headline_wording_follows_the_ratio_and_its_interval(ratio, ci90, words):
    """A multiple is claimed only when the 90% interval excludes 1, rounded to the nearest half."""
    from amr_aerotwin.report.note import headline

    h = headline({"straight_vs_field": {"2025": {"ratio": 0.5, "ratio_ci90": [0.3, 0.7]}, "2026": {"ratio": ratio, "ratio_ci90": ci90}}})
    assert h.startswith("In 2026 Aston Martin ") and h.endswith(words), h
    assert headline({}) == headline({"straight_vs_field": {"2026": {"ratio": float("nan"), "ratio_ci90": [1.0, 2.0]}}})
    assert "time" in headline({}) and "twice" not in headline({})


def test_pace_words():
    from amr_aerotwin.report.note import pace_words

    assert pace_words(3.99, 4.15) == "about as slow" and pace_words(2.0, 4.15) == "faster" and pace_words(5.0, 4.15) == "slower"
    assert pace_words(None, 4.15) == "n/a"


@pytest.mark.skipif(not ((ROOT / "site" / "index.html").exists() and (ROOT / "data" / "processed" / "season.json").exists()),
                    reason="needs a built report (make report)")
def test_built_report_headline_matches_the_current_results():
    """The published page says exactly what the current season results support."""
    import html

    from amr_aerotwin.report.note import headline

    want = '<p class="deck">' + html.escape(headline(json.loads((ROOT / "data" / "processed" / "season.json").read_text())), quote=False) + "</p>"
    for page in ("index.html", "page.html"):
        assert want in (ROOT / "site" / page).read_text(), page


@pytest.mark.skipif(not (ROOT / "data" / "processed" / "drivers.csv.gz").exists(), reason="needs processed results")
def test_every_rejected_lap_fails_a_check_and_no_kept_lap_does():
    """The data section's counts per check describe the laps the pipeline dropped."""
    import pandas as pd
    from amr_aerotwin.modeling.validation import LAP_CHECKS, failures_by_check

    d = pd.read_csv(ROOT / "data" / "processed" / "drivers.csv.gz")
    rows = d[[f"q_{m}" for m in LAP_CHECKS]].to_numpy(float)
    fails_any = [any(failures_by_check({m: [v] for m, v in zip(LAP_CHECKS, row, strict=True)}).values()) for row in rows]
    assert fails_any == (~d["passed_checks"].astype(bool)).tolist()


def test_every_section_link_reaches_a_section_in_page_order():
    """The masthead links each land on a section, and follow the page from top to bottom."""
    import re

    html = (JS.parent / "page.html").read_text(encoding="utf-8")
    nav = html[html.index('<nav class="nav"'):html.index("</nav>")]
    targets = re.findall(r'href="#([\w-]+)"', nav)
    places = [html.find(f'<section id="{t}"') for t in targets]
    assert len(targets) >= 5 and all(p > 0 for p in places), dict(zip(targets, places, strict=True))
    assert places == sorted(places)
    assert html.count('href="#author"') >= 1 and 'id="author"' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_parses():
    app = JS.parent / "app.js"
    subprocess.run(["node", "--check", str(app)], check=True, capture_output=True)


def test_readme_blocks_are_generated_from_results(tmp_path):
    """README numbers come from season.json; text outside the markers is left alone."""
    from amr_aerotwin.report.note import update_readme

    def rate(st, c, lap, n=10):
        return {"sections": ["high", "low", "medium", "straights"], "rate_pct": [c, c, c, st], "ci_lo": [0, 0, 0, 0],
                "ci_hi": [9, 9, 9, 9], "lap_rate_pct": lap, "n_events": n, "corner_rate_pct": c, "straight_to_corner_ratio": st / c}

    season = {
        "section_rates": {"2026": {"Aston Martin": rate(3.8, 4.1, 4.0), "Cadillac": rate(1.7, 5.0, 4.05), "Alpine": rate(0.5, 2.3, 1.8)},
                          "2025": {"Aston Martin": rate(0.3, 1.5, 1.2)}},
        "straight_vs_field": {"2026": {"next_team": "Cadillac", "next_rate_pct": 1.7, "ratio": 2.24, "ratio_ci90": [1.75, 2.86]}},
        "straight_profile": {"2026": {"Aston Martin": {"bins": [{"gap_kmh": -5.7}], "second_half_kmh": -3.0, "second_half_ci90": [-4.5, -1.5],
                                                       "n_straights": 6, "n_straights_losing_late": 5, "n_events": 5}}},
        "variance_split": {"2025": {"median_event_share": 0.51, "car_share": 0.53, "car_share_ci90": [0.43, 0.58]},
                           "2026": {"median_event_share": 0.94, "car_share": 0.90, "car_share_ci90": [0.83, 0.94]}},
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
    assert "2.2 times as much, 90% interval 1.8 to 2.9" in text and "explain 90% (90% interval 83 to 94)" in text and "53% in 2025" in text
    assert "717 of 758 laps pass" in text and "Chinese 2026" in text and "Spanish 2026" in text
    assert "- **In 2026 Aston Martin loses time on the straights at about twice the rate of any other team.**" in text
    assert not update_readme(sj, readme)  # idempotent
    # A different ratio changes the words, not just the numbers
    season["straight_vs_field"]["2026"].update(ratio=2.6, ratio_ci90=[2.1, 3.3])
    sj.write_text(json.dumps(season))
    assert update_readme(sj, readme)
    assert "at about two and a half times the rate of any other team.**" in readme.read_text()
    readme.write_text("no markers here\n")
    with pytest.raises(ValueError):
        update_readme(sj, readme)


def test_method_settings_quote_the_code_that_uses_them():
    """Settings quoted in the report text come from the modules that use them."""
    from amr_aerotwin.data.alignment import GRID_STEP_M
    from amr_aerotwin.domain import REPRESENTATIVE_LAP_RATIO
    from amr_aerotwin.modeling.calibration import DEFAULT_PRIORS
    from amr_aerotwin.modeling.energy import MIN_PERSIST_M
    from amr_aerotwin.modeling.lap_compare import ENTRY_M, EXIT_M
    from amr_aerotwin.modeling.powertrain import MIN_FIT_POSITIONS, MIN_FIT_SPEED_SPAN_KMH
    from amr_aerotwin.modeling.season import MDE_ALPHA, MDE_POWER, NOISE_RATIO_MAX
    from amr_aerotwin.pipeline.season import method_settings

    m = method_settings()
    assert m["interval_level"] == 0.9 and m["interval_z"] == pytest.approx(1.6449, abs=1e-4)
    assert m["corner_window_m"] == EXIT_M[1] == -ENTRY_M[0]  # the window is symmetric about the corner
    assert m["representative_pct"] == pytest.approx(100 * REPRESENTATIVE_LAP_RATIO)
    assert m["clip_min_decel_m"] == MIN_PERSIST_M
    assert m["powertrain_min_straight_m"] == MIN_FIT_POSITIONS * GRID_STEP_M
    assert m["powertrain_min_speed_span_kmh"] == MIN_FIT_SPEED_SPAN_KMH
    assert (m["did_alpha"], m["did_power"], m["did_noise_ratio_max"]) == (MDE_ALPHA, MDE_POWER, NOISE_RATIO_MAX)
    assert m["calibration_prior_sd_log"] == {k: v[1] for k, v in DEFAULT_PRIORS.items()}


def _js_function(src: str, name: str) -> str:
    """The source of one top-level helper in app.js, up to its closing brace at the same indent."""
    start = src.index(f"  function {name}(")
    end = src.index("\n  }\n", start) + 4
    return src[start:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_words_the_straight_line_multiple_like_the_headline(tmp_path):
    """Finding 02 on the page (JavaScript) and the headline, note and README (Python) use one rule."""
    from amr_aerotwin.report.note import straight_multiple

    src = (JS.parent / "app.js").read_text(encoding="utf-8")
    cases = [(2.02, [1.69, 2.52]), (2.6, [1.9, 3.4]), (1.74, [1.2, 2.3]), (2.24, [1.1, 3.0]), (3.1, [0.9, 4.0]),
             (1.3, [1.1, 1.6]), (12.4, [9.0, 15.0]), (float("nan"), [1.0, 2.0])]
    script = tmp_path / "words.js"
    script.write_text(
        'var CARD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];\n'
        + _js_function(src, "multipleWords") + "\n" + _js_function(src, "straightMultiple") + "\n"
        + "var cases = " + json.dumps([{"ratio": None if r != r else r, "ratio_ci90": c} for r, c in cases]) + ";\n"
        + "console.log(JSON.stringify(cases.map(function (vf) { if (vf.ratio === null) vf.ratio = NaN; return straightMultiple(vf); })));\n",
        encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], check=True, capture_output=True, text=True).stdout)
    want = [(m[1] if (m := straight_multiple({"ratio": r, "ratio_ci90": c})) else None) for r, c in cases]
    assert out == want


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_signed_numbers_that_round_to_zero_have_no_sign(tmp_path):
    """The page's signed format never prints "−0" or "+0.0"."""
    src = (JS.parent / "app.js").read_text(encoding="utf-8")
    script = tmp_path / "sgn.js"
    script.write_text(_js_function(src, "sgn") + "\nconsole.log(JSON.stringify([sgn(-0.11, 0), sgn(0.04, 1), sgn(-2.5, 1), sgn(3, 0), sgn(null), sgn(-0.006, 2)]));\n",
                      encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], check=True, capture_output=True, text=True).stdout)
    assert out == ["0", "0.0", "−2.5", "+3", "–", "−0.01"]


@pytest.mark.skipif(not (ROOT / "data" / "processed" / "season.json").exists(), reason="needs processed results")
def test_note_words_the_wind_test_from_the_results(tmp_path):
    """The note's wind sentence quotes the test's own numbers, and phrasings known to be inaccurate stay out."""
    from amr_aerotwin.report.note import build_note

    s = json.loads((ROOT / "data" / "processed" / "season.json").read_text())
    s["wind_rotation_test"].update(mean_relative_sse={str(a): (0.9 if a == 270 else 1.0) for a in range(0, 360, 30)},
                                   share_events_assumed_orientation_best=0.5)
    (tmp_path / "season.json").write_text(json.dumps(s))
    note = build_note(tmp_path / "season.json", tmp_path / "note.md").read_text(encoding="utf-8")
    assert "more than 10.0% and the assumed one was best in 50% of them (chance: 1 in 12)" in note


def test_static_page_types_no_result_numbers():
    """Every result on the page is filled in by the build or the script; the static HTML holds only labels."""
    import re

    html = (JS.parent / "page.html").read_text(encoding="utf-8")
    body = html[html.index("<header"):]
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<svg[\s\S]*?</svg>", " ", body)
    text = re.sub(r"<[^>]+>", " ", body)  # drop tags and attributes, keep the visible text
    numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
    # Section and model numbers, and "Formula 1" in the footer
    assert numbers <= {"01", "02", "03", "04", "05", "06", "07", "1"}, sorted(numbers)
