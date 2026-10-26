"""Shared data contracts, physical constants and per-season regulation assumptions (SI units)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

# Physical constants
R_SPECIFIC_DRY_AIR: float = 287.058  # J / (kg K)
R_SPECIFIC_WATER_VAPOUR: float = 461.495  # J / (kg K)
KELVIN_OFFSET: float = 273.15
GRAVITY_ACCEL: float = 9.80665  # m / s^2

TARGET_TEAM = "Aston Martin"
TARGET_DRIVERS = ("ALO", "STR")


@dataclass(frozen=True)
class SeasonRegulations:
    """Regulation-driven modelling assumptions for one season.

    Masses are car + driver without fuel (sources in data/reference/SOURCES.md). Aero
    coefficients estimated from telemetry scale linearly with the assumed mass, so a 2 kg
    error moves ClA by ~0.25%.
    """

    season: int
    min_mass_kg: float
    quali_min_mass_kg: float
    has_drs: bool
    quali_fuel_kg: float = 5.0  # assumed low-fuel qualifying load (not published)
    notes: str = ""


REGULATIONS: dict[int, SeasonRegulations] = {
    2025: SeasonRegulations(
        season=2025,
        min_mass_kg=800.0,
        quali_min_mass_kg=800.0,
        has_drs=True,
        notes="2022-2025 ground-effect rules; DRS on straights; MGU-K 120 kW.",
    ),
    2026: SeasonRegulations(
        season=2026,
        min_mass_kg=768.0,  # 724 kg + ~44 kg nominal tyre mass
        quali_min_mass_kg=770.0,  # 726 kg + ~44 kg nominal tyre mass
        has_drs=False,
        notes="Active aero (Corner/Straight Mode) replaces DRS; MGU-K 350 kW with speed taper.",
    ),
}


def mgu_k_power_limit_kw(speed_kmh: np.ndarray, season: int) -> np.ndarray:
    """Regulated maximum MGU-K power (kW) vs speed, without Overtake Mode.

    2026 (Section C Art. C5.2.8): 350 kW up to 290 km/h, then 1800 - 5 v up to 340 km/h
    (100 kW at 340), then falling linearly to 0 at 345 km/h. Earlier seasons: flat 120 kW.
    """
    v = np.asarray(speed_kmh, dtype=float)
    if season >= 2026:
        p = np.minimum(350.0, 1800.0 - 5.0 * v)
        p = np.where(v > 340.0, 100.0 * (345.0 - v) / 5.0, p)
        return np.clip(p, 0.0, 350.0)
    return np.full_like(v, 120.0)


def regulations_for(season: int) -> SeasonRegulations:
    """Return regulation assumptions for `season`, falling back to the nearest known season."""
    if season in REGULATIONS:
        return REGULATIONS[season]
    nearest = min(REGULATIONS, key=lambda s: abs(s - season))
    return REGULATIONS[nearest]


@dataclass(frozen=True)
class AmbientState:
    """Weather at the time of a lap. Wind direction is meteorological (blowing FROM, 0 = N)."""

    air_temp_c: float
    track_temp_c: float
    pressure_mbar: float
    wind_speed_ms: float
    wind_direction_deg: float
    relative_humidity_pct: float = 50.0


@dataclass(frozen=True)
class LapMeta:
    """Identifying metadata and official timing for one lap."""

    season: int
    event: str
    session: str
    driver: str
    team: str
    lap_number: int
    lap_time_s: float
    compound: str = "SOFT"
    tyre_life_laps: int = 1
    sector_times_s: tuple[float, float, float] = (float("nan"),) * 3
    speed_trap_kmh: float = float("nan")
    team_color: str = "#777777"

    @property
    def lap_id(self) -> str:
        return f"{self.season}-{self.event}-{self.session}-{self.driver}-L{self.lap_number}"


@dataclass(frozen=True)
class AlignedLap:
    """One lap resampled onto a shared distance grid (metres along a reference line).

    `time_s` comes from the measured timing channel (anchored to 0 at the line and to the
    official lap time at the end of the lap); it is never reconstructed from speed.
    """

    meta: LapMeta
    ambient: AmbientState
    distance_m: NDArray[np.float64]
    time_s: NDArray[np.float64]
    speed_ms: NDArray[np.float64]
    throttle_pct: NDArray[np.float64]
    brake: NDArray[np.float64]
    gear: NDArray[np.float64]
    drs: NDArray[np.float64]
    rpm: NDArray[np.float64]
    x_m: NDArray[np.float64]
    y_m: NDArray[np.float64]
    z_m: NDArray[np.float64]
    lap_length_m: float
    distance_scale: float = 1.0  # odometer metres per GPS-path metre (see ReferenceLine)
    # Original GPS fixes projected onto the reference line (for curvature estimation)
    gps_time_s: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    gps_distance_m: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    gps_x_m: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    gps_y_m: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    quality: dict[str, float] = field(default_factory=dict)

    @property
    def grid_step_m(self) -> float:
        return float(self.distance_m[1] - self.distance_m[0])
