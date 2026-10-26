"""Vehicle state along the lap: accelerations, airspeed, dynamic pressure and driving regime."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import savgol_filter

from amr_aerotwin.domain import GRAVITY_ACCEL, AlignedLap, regulations_for
from amr_aerotwin.physics.kinematics import (
    compute_air_density_kg_m3,
    gps_spline_kinematics,
    decompose_aero_wind_vectors,
    path_curvature,
    turning_number,
)

MIN_GPS_FIXES = 50
GPS_SPLINE_LAM = 0.2  # default time-smoothing penalty (events re-select it, see kinematics)

STRAIGHT = "STRAIGHT"
BRAKING = "BRAKING"
LOW_SPEED_CORNER = "LOW_SPEED_CORNER"
MEDIUM_SPEED_CORNER = "MEDIUM_SPEED_CORNER"
HIGH_SPEED_CORNER = "HIGH_SPEED_CORNER"
TRANSITION = "TRANSITION"
REGIMES = (STRAIGHT, BRAKING, LOW_SPEED_CORNER, MEDIUM_SPEED_CORNER, HIGH_SPEED_CORNER, TRANSITION)

# Corner speed classes (km/h) used throughout the project
LOW_SPEED_MAX_KMH = 150.0
HIGH_SPEED_MIN_KMH = 230.0
CORNER_MIN_LAT_G = 1.5
STRAIGHT_MAX_LAT_G = 1.0


def corner_speed_class(speed_kmh: float) -> str:
    if speed_kmh < LOW_SPEED_MAX_KMH:
        return "low"
    if speed_kmh < HIGH_SPEED_MIN_KMH:
        return "medium"
    return "high"


@dataclass(frozen=True)
class VehicleState:
    """Derived physical state on the lap's distance grid (all SI)."""

    lap: AlignedLap
    mass_kg: float
    rho_kg_m3: float
    heading_rad: NDArray[np.float64]
    curvature_inv_m: NDArray[np.float64]
    speed_smooth_ms: NDArray[np.float64]
    ax_ms2: NDArray[np.float64]
    ay_ms2: NDArray[np.float64]  # signed: + = left turn
    v_headwind_ms: NDArray[np.float64]
    v_crosswind_ms: NDArray[np.float64]
    v_airspeed_ms: NDArray[np.float64]
    beta_aero_deg: NDArray[np.float64]
    q_dyn_pa: NDArray[np.float64]
    regime: NDArray[np.str_]
    turning_number: float

    @property
    def distance_m(self) -> NDArray[np.float64]:
        return self.lap.distance_m


def smooth_speed(speed_ms: NDArray[np.float64], step_m: float, window_m: float = 25.0) -> NDArray[np.float64]:
    w = max(5, int(round(window_m / step_m)) | 1)
    return savgol_filter(speed_ms, w, 2, mode="wrap")


def longitudinal_acceleration(speed_ms: NDArray[np.float64], step_m: float) -> NDArray[np.float64]:
    """a_x = v dv/ds on a closed lap (periodic central difference)."""
    dv_ds = (np.roll(speed_ms, -1) - np.roll(speed_ms, 1)) / (2.0 * step_m)
    return speed_ms * dv_ds


def classify_regimes(
    speed_ms: NDArray[np.float64],
    throttle_pct: NDArray[np.float64],
    brake: NDArray[np.float64],
    ay_ms2: NDArray[np.float64],
) -> NDArray[np.str_]:
    """Label each grid point. Braking is checked first so brake zones are never called corners.

    Corners are defined by lateral load (|a_y| >= 1.5 g), not raw curvature, so gentle
    flat-out kinks at 300 km/h are not confused with real corners.
    """
    lat_g = np.abs(ay_ms2) / GRAVITY_ACCEL
    v_kmh = speed_ms * 3.6
    out = np.full(len(speed_ms), TRANSITION, dtype="<U20")
    is_brake = brake > 0.5
    is_corner = ~is_brake & (lat_g >= CORNER_MIN_LAT_G)
    out[is_corner & (v_kmh < LOW_SPEED_MAX_KMH)] = LOW_SPEED_CORNER
    out[is_corner & (v_kmh >= LOW_SPEED_MAX_KMH) & (v_kmh < HIGH_SPEED_MIN_KMH)] = MEDIUM_SPEED_CORNER
    out[is_corner & (v_kmh >= HIGH_SPEED_MIN_KMH)] = HIGH_SPEED_CORNER
    out[~is_brake & ~is_corner & (throttle_pct >= 98.0) & (lat_g < STRAIGHT_MAX_LAT_G)] = STRAIGHT
    out[is_brake] = BRAKING
    return out


def vehicle_mass_kg(season: int, fuel_kg: float | None = None, qualifying: bool = True) -> float:
    """Assumed running mass: regulation minimum (car + driver) plus fuel."""
    regs = regulations_for(season)
    base = regs.quali_min_mass_kg if qualifying else regs.min_mass_kg
    return base + (regs.quali_fuel_kg if fuel_kg is None else fuel_kg)


def lap_curvature(
    lap: AlignedLap, lam: float = GPS_SPLINE_LAM, curvature_window_m: float = 55.0
) -> NDArray[np.float64]:
    """Curvature of one lap from its raw GPS fixes (time-domain spline), else smoothed X/Y."""
    if len(lap.gps_time_s) >= MIN_GPS_FIXES:
        kappa, _ = gps_spline_kinematics(
            lap.gps_time_s, lap.gps_x_m, lap.gps_y_m, lap.meta.lap_time_s, lap.time_s, lam
        )
        # Express curvature per odometer metre so total heading change is preserved.
        return kappa / lap.distance_scale
    return path_curvature(lap.distance_m, lap.x_m, lap.y_m, curvature_window_m)[1]


def estimate_vehicle_state(
    lap: AlignedLap,
    mass_kg: float | None = None,
    curvature_inv_m: NDArray[np.float64] | None = None,
    curvature_window_m: float = 55.0,
) -> VehicleState:
    """Compute accelerations, airspeed, dynamic pressure and regimes for one aligned lap.

    Pass `curvature_inv_m` (e.g. the event's multi-driver consensus) to override the lap's
    own GPS-derived curvature. Heading always comes from the smoothed lap path.
    """
    step = lap.grid_step_m
    is_quali = "Qualifying" in lap.meta.session
    mass = vehicle_mass_kg(lap.meta.season, qualifying=is_quali) if mass_kg is None else mass_kg
    rho = compute_air_density_kg_m3(lap.ambient)

    heading, _ = path_curvature(lap.distance_m, lap.x_m, lap.y_m, curvature_window_m)
    kappa = lap_curvature(lap) if curvature_inv_m is None else curvature_inv_m
    v = smooth_speed(lap.speed_ms, step)
    ax = longitudinal_acceleration(v, step)
    ay = v**2 * kappa

    wind = decompose_aero_wind_vectors(v, heading, lap.ambient)
    q = 0.5 * rho * wind["v_airspeed_ms"] ** 2

    return VehicleState(
        lap=lap,
        mass_kg=mass,
        rho_kg_m3=rho,
        heading_rad=heading,
        curvature_inv_m=kappa,
        speed_smooth_ms=v,
        ax_ms2=ax,
        ay_ms2=ay,
        v_headwind_ms=wind["v_headwind_ms"],
        v_crosswind_ms=wind["v_crosswind_ms"],
        v_airspeed_ms=wind["v_airspeed_ms"],
        beta_aero_deg=wind["beta_aero_deg"],
        q_dyn_pa=q,
        regime=classify_regimes(v, lap.throttle_pct, lap.brake, ay),
        turning_number=turning_number(kappa, step),
    )
