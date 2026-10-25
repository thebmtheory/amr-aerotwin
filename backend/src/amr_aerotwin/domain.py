"""Domain data contracts and SI-unit physical constants for AMR-AeroTwin."""

from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray

# Standard physical constants (strictly SI units)
R_SPECIFIC_DRY_AIR: float = 287.058  # J / (kg * K)
KELVIN_OFFSET: float = 273.15        # K at 0 deg C
GRAVITY_ACCEL: float = 9.80665       # m / s^2

# 2025/2026 F1 Technical Regulations baseline car parameters
CAR_DRY_MASS_KG: float = 798.0       # Minimum reglamentary car + driver mass (kg)
FUEL_LAP_BURN_KG: float = 1.65       # Typical fuel mass burned per lap (kg/lap)
FUEL_TIME_SENSITIVITY_S_PER_KG: float = 0.032  # Lap time penalty per kg fuel (s/kg)
FRONTAL_AREA_M2: float = 1.50        # Reference aerodynamic frontal area A (m^2)


@dataclass(frozen=True)
class AmbientState:
    """Thermodynamic and wind vector state of the circuit environment (SI units)."""

    air_temp_c: float
    track_temp_c: float
    pressure_mbar: float
    wind_speed_ms: float
    wind_direction_deg: float  # Meteorological heading (0 deg = North, 90 deg = East)
    relative_humidity_pct: float = 50.0


@dataclass(frozen=True)
class AlignedTelemetryTrace:
    """Distance-aligned 1m spatial grid telemetry & kinematic state for a single lap."""

    lap_id: str
    driver: str
    team: str
    session_type: str          # 'FP1', 'FP2', 'FP3', 'Q', 'R'
    compound: str              # 'SOFT', 'MEDIUM', 'HARD'
    tyre_life_laps: int
    stint_id: int
    fuel_Load_kg: float
    ambient: AmbientState

    # 1D spatial arrays of shape (N_grid,) along lap distance s in [0, L] meters
    distance_m: NDArray[np.float64]
    time_s: NDArray[np.float64]
    speed_ms: NDArray[np.float64]
    throttle_pct: NDArray[np.float64]
    brake_flag: NDArray[np.float64]
    gear: NDArray[np.int32]
    drs_active: NDArray[np.int32]
    x_m: NDArray[np.float64]
    y_m: NDArray[np.float64]
    z_m: NDArray[np.float64]

    # Official FIA Timing & Speed-Trap Cross-Verification Metadata
    official_lap_time_s: float = 0.0
    sector_times_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    speed_trap_kmh: float = 0.0
