"""Build the static report site from processed results.

Data is written as small `window.*` script files rather than JSON so the site works from
file:// or any static host such as GitHub Pages (no fetch, no server). Each event's
detail file is loaded only when that event is selected.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

STATIC = Path(__file__).parent / "static"
MARKER = ".aerotwin-site"  # written into every built site; only such folders are ever replaced

# Keys from the per-event summary that the site actually uses (keeps files small)
EVENT_KEYS = [
    "season", "event", "round", "date", "circuit", "lap_length_m", "turning_number", "geometry_ok",
    "pole", "track", "corners", "map", "comparison", "lapsim", "iso_lap_time", "sandbox", "pod",
    "energy", "energy_speed", "race_pace", "warnings", "n_laps", "n_passed", "gps_smoothing_lam",
    "distance_scale", "team_table", "official_pole", "fastest_lap", "wet_session",
]


def _js(var: str, payload: Any) -> str:
    return f"{var}={json.dumps(payload, separators=(',', ':'), allow_nan=False)};\n"


def _clean(x: Any) -> Any:
    """Replace NaN/inf with None recursively so the output is strict JSON."""
    if isinstance(x, float):
        return x if x == x and abs(x) != float("inf") else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def _event_report_links(reports_dir: Path | None) -> list[tuple[str, str]]:
    """(relative href, title) for each single-event report page in `reports_dir`."""
    if reports_dir is None or not Path(reports_dir).is_dir():
        return []
    out = []
    for f in sorted(Path(reports_dir).glob("*.html")):
        m = re.search(r"<title>(.*?)</title>", f.read_text(encoding="utf-8")[:8192], re.S)
        out.append((f"reports/{f.name}", (m.group(1).strip() if m else f.stem).replace("Aston Martin at ", "")))
    return out


def build_site(processed_dir: Path, site_dir: Path, reports_dir: Path | None = None) -> Path:
    processed_dir, site_dir = Path(processed_dir), Path(site_dir)
    season = json.loads((processed_dir / "season.json").read_text())
    events = {p.stem: json.loads(p.read_text()) for p in sorted((processed_dir / "events").glob("*.json"))}

    if site_dir.exists():
        if not (site_dir / MARKER).exists() and any(site_dir.iterdir()):
            raise FileExistsError(f"{site_dir} exists and was not built by aerotwin; refusing to overwrite it")
        shutil.rmtree(site_dir)
    (site_dir / "data" / "events").mkdir(parents=True)
    (site_dir / MARKER).write_text("built by aerotwin report\n", encoding="utf-8")
    for f in STATIC.iterdir():
        if f.is_file() and f.name != "event_report.html":
            shutil.copy(f, site_dir / f.name)
    links = _event_report_links(reports_dir)
    if links:
        (site_dir / "reports").mkdir()
        for href, _ in links:
            shutil.copy(Path(reports_dir) / Path(href).name, site_dir / href)  # type: ignore[arg-type]
    # page.html is the body fragment (used as-is by hosts that add their own document
    # skeleton); index.html wraps it for GitHub Pages and local viewing.
    fragment = (STATIC / "page.html").read_text(encoding="utf-8")
    fragment = fragment.replace("<!--EVENT_REPORTS-->", "".join(f'<a href="{href}" class="nav-report">{title} report</a>' for href, title in links))
    (site_dir / "page.html").write_text(fragment, encoding="utf-8")
    # Content-hash query strings so browsers never run a stale script after a rebuild
    for asset in ("app.js", "app.css", "lapsim.js"):
        h = hashlib.sha1((STATIC / asset).read_bytes()).hexdigest()[:8]
        fragment = fragment.replace(f'"{asset}"', f'"{asset}?v={h}"')
    head, body = fragment.split("<header", 1)  # title/meta/link lines go in <head>
    (site_dir / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + head + "</head>\n<body>\n<header" + body + "\n</body>\n</html>\n",
        encoding="utf-8",
    )

    manifest = []
    for key, e in sorted(events.items(), key=lambda kv: (kv[1]["season"], kv[1]["round"])):
        slim = _clean({k: e.get(k) for k in EVENT_KEYS})
        (site_dir / "data" / "events" / f"{key}.js").write_text(
            f"window.EVENTS=window.EVENTS||{{}};window.EVENTS[{json.dumps(key)}]=" + json.dumps(slim, separators=(",", ":")) + ";\n",
            encoding="utf-8",
        )
        manifest.append({
            "key": key, "season": e["season"], "round": e["round"], "event": e["event"],
            "circuit": (e.get("circuit") or {}).get("location"), "geometry_ok": e["geometry_ok"],
            "has_comparison": "comparison" in e, "has_sandbox": "sandbox" in e,
            "amr_gap_s": (e.get("comparison") or {}).get("total_delta_s"),
        })
    (site_dir / "data" / "season.js").write_text(_js("window.SEASON", _clean(season)) + _js("window.MANIFEST", manifest), encoding="utf-8")
    return site_dir
