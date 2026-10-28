"""Cached access to the public TracingInsights F1 timing archive (one GitHub repo per season).

Every response is cached as JSON on disk, so after one `fetch` the pipeline runs offline and reproducibly.
Lap telemetry is returned as published; alignment.py converts it to SI units.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from amr_aerotwin.domain import DATA_DIR, AmbientState

DEFAULT_CACHE_DIR = DATA_DIR / "telemetry_cache"
RAW_BASE_URL = "https://raw.githubusercontent.com/TracingInsights"
API_BASE_URL = "https://api.github.com/repos/TracingInsights"

NON_EVENT_DIRS = {"cache", "cache_joblib", "cache_preseason", "fastf1_cache", "images", "schemas", "sections"}

LAP_NUMERIC_COLUMNS = [
    "time", "lap", "stint", "s1", "s2", "s3", "life", "pos", "vi1", "vi2", "vfl", "vst",
    "sesT", "wAT", "wH", "wP", "wTT", "wWD", "wWS",
]


class DataUnavailableError(RuntimeError):
    """Raised when a file is neither cached nor downloadable (offline mode or HTTP 404)."""


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _clean_value(v: Any) -> Any:
    return np.nan if v in ("None", None, "") else v


def vector_mean_wind(speed_ms: np.ndarray, direction_deg: np.ndarray) -> tuple[float, float]:
    """Average wind as a vector. A scalar mean or median of compass angles is wrong near north."""
    speed = np.asarray(speed_ms, dtype=float)
    theta = np.radians(np.asarray(direction_deg, dtype=float))
    ok = np.isfinite(speed) & np.isfinite(theta)
    if not np.any(ok):
        return 0.0, 0.0
    u = float(np.mean(speed[ok] * np.sin(theta[ok])))
    v = float(np.mean(speed[ok] * np.cos(theta[ok])))
    mean_dir = float(np.degrees(np.arctan2(u, v)) % 360.0)
    return float(np.hypot(u, v)), mean_dir


class TelemetryRepository:
    """Read-through JSON cache over the TracingInsights archive."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR, offline: bool | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.get("AEROTWIN_OFFLINE", "").strip().lower()
        self.offline = env in ("1", "true", "yes", "on") if offline is None else offline

    # Transport
    def _cache_path(self, year: int, rel_path: str) -> Path:
        return self.cache_dir / (f"{year}_" + rel_path.replace("/", "__").replace(" ", "_"))

    def _download(self, url: str) -> Any:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 404:
                    raise DataUnavailableError(f"404: {url}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code}: {url}")
                resp.raise_for_status()
                return resp.json()
            except DataUnavailableError:
                raise
            except (requests.RequestException, ValueError) as err:
                last_err = err
                time.sleep(1.5 * (attempt + 1))
        raise DataUnavailableError(f"Download failed after retries: {url}") from last_err

    def fetch_json(self, year: int, rel_path: str) -> Any:
        """Return parsed JSON for `rel_path` inside the `year` repo, using the disk cache."""
        path = self._cache_path(year, rel_path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise DataUnavailableError(f"Not cached (offline): {year}/{rel_path}")
        data = self._download(f"{RAW_BASE_URL}/{year}/main/{quote(rel_path)}")
        _atomic_write(path, json.dumps(data))
        return data

    def invalidate_event(self, year: int, event: str) -> int:
        """Delete cached files of one event (used to re-fetch a weekend still in progress)."""
        prefix = f"{year}_" + event.replace(" ", "_") + "__"
        removed = 0
        for f in self.cache_dir.glob(prefix + "*"):
            f.unlink()
            removed += 1
        return removed

    # Catalogue
    def list_events(self, year: int, refresh: bool = False) -> list[str]:
        """Grand Prix folders available for `year` (testing sessions excluded).

        The listing is cached; pass `refresh=True` (as `fetch` does) to pick up new rounds.
        """
        path = self.cache_dir / f"{year}__events.json"
        if path.exists() and not (refresh and not self.offline):
            names = json.loads(path.read_text(encoding="utf-8"))
        else:
            if self.offline:
                raise DataUnavailableError(f"Event list for {year} not cached (offline)")
            listing = self._download(f"{API_BASE_URL}/{year}/contents")
            names = [d["name"] for d in listing if d.get("type") == "dir"]
            _atomic_write(path, json.dumps(names))
        return [n for n in names if n.endswith("Grand Prix") and n not in NON_EVENT_DIRS]

    # Tables
    def session_laps(self, year: int, event: str, session: str) -> pd.DataFrame:
        """All laps of all drivers in a session, with 'None' strings converted to NaN."""
        raw = self.fetch_json(year, f"{event}/{session}/session_laptimes.json")
        df = pd.DataFrame({k: [_clean_value(v) for v in vals] for k, vals in raw.items()})
        for col in LAP_NUMERIC_COLUMNS:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("del", "pb", "fresh"):
            if col in df:
                df[col] = df[col].eq(True)
        df["is_pit_in"] = df["pin"].notna() if "pin" in df else False
        df["is_pit_out"] = df["pout"].notna() if "pout" in df else False
        df["status"] = df.get("status", pd.Series(["1"] * len(df))).astype(str)
        df["compound"] = df.get("compound", pd.Series(["UNKNOWN"] * len(df))).fillna("UNKNOWN")
        return df

    def drivers(self, year: int, event: str, session: str) -> pd.DataFrame:
        raw = self.fetch_json(year, f"{event}/{session}/drivers.json")
        rows = [
            {
                "driver": d["driver"],
                "team": d.get("team", ""),
                "number": str(d.get("dn", "")),
                "name": f"{d.get('fn', '')} {d.get('ln', '')}".strip(),
                "color": "#" + str(d.get("tc", "777777")).lstrip("#"),
            }
            for d in raw.get("drivers", [])
            if d.get("driver")
        ]
        return pd.DataFrame(rows)

    def corners(self, year: int, event: str, session: str = "Qualifying") -> pd.DataFrame:
        """Official corner markers. Distances are along the FIA layout lap; X/Y in metres."""
        raw = self.fetch_json(year, f"{event}/{session}/corners.json")
        n = len(raw.get("CornerNumber", []))
        letters = raw.get("CornerLetter") or [""] * n
        return pd.DataFrame(
            {
                "number": [int(v) for v in raw["CornerNumber"]],
                "letter": ["" if pd.isna(_clean_value(v)) else str(v) for v in letters],
                "distance_m": [float(v) for v in raw["Distance"]],
                "x_m": [float(v) / 10.0 for v in raw["X"]],
                "y_m": [float(v) / 10.0 for v in raw["Y"]],
            }
        )

    def circuit_info(self, year: int, event: str, session: str = "Qualifying") -> dict[str, Any]:
        raw = self.fetch_json(year, f"{event}/{session}/corners.json")
        return {
            "circuit_name": raw.get("CircuitName"),
            "location": raw.get("Location"),
            "country": raw.get("CountryName"),
        }

    def session_ambient(self, year: int, event: str, session: str) -> AmbientState:
        """Session-average weather (vector-averaged wind)."""
        wx = pd.DataFrame(self.fetch_json(year, f"{event}/{session}/weather.json"))
        wx = wx.apply(pd.to_numeric, errors="coerce")
        ws, wd = vector_mean_wind(wx["wWS"].to_numpy(), wx["wWD"].to_numpy())
        return AmbientState(
            air_temp_c=float(wx["wAT"].mean()),
            track_temp_c=float(wx["wTT"].mean()),
            pressure_mbar=float(wx["wP"].mean()),
            wind_speed_ms=ws,
            wind_direction_deg=wd,
            relative_humidity_pct=float(wx["wH"].mean()),
        )

    def lap_telemetry(self, year: int, event: str, session: str, driver: str, lap: int) -> dict[str, Any]:
        return self.fetch_json(year, f"{event}/{session}/{driver}/{int(lap)}_tel.json")["tel"]


def lap_ambient(row: pd.Series, fallback: AmbientState) -> AmbientState:
    """Weather sampled closest to a lap (TracingInsights merges it into each lap row)."""

    def pick(col: str, default: float) -> float:
        v = row.get(col, np.nan)
        return float(v) if pd.notna(v) else default

    return AmbientState(
        air_temp_c=pick("wAT", fallback.air_temp_c),
        track_temp_c=pick("wTT", fallback.track_temp_c),
        pressure_mbar=pick("wP", fallback.pressure_mbar),
        wind_speed_ms=pick("wWS", fallback.wind_speed_ms),
        wind_direction_deg=pick("wWD", fallback.wind_direction_deg),
        relative_humidity_pct=pick("wH", fallback.relative_humidity_pct),
    )


def fastest_valid_lap(laps: pd.DataFrame, driver: str) -> pd.Series | None:
    """Fastest timed lap for `driver` that was not deleted (e.g. for track limits)."""
    d = laps[(laps["drv"] == driver) & laps["time"].notna() & ~laps["del"]]
    if d.empty:
        return None
    return d.loc[d["time"].idxmin()]
