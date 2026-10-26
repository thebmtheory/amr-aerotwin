"""Where one lap gains or loses time against another, by corner phase and corner class.

The time delta comes from the measured timing channel on a shared distance grid, so the
corner and straight contributions add up to the official lap-time gap exactly. That
additivity is bookkeeping, not validation; the validation of the alignment itself is in
`AlignedLap.quality`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from amr_aerotwin.domain import AlignedLap
from amr_aerotwin.physics.dynamics import corner_speed_class

ENTRY_M = (-120.0, -20.0)
APEX_M = (-20.0, 20.0)
EXIT_M = (20.0, 120.0)


@dataclass(frozen=True)
class LapComparison:
    distance_m: NDArray[np.float64]
    delta_s: NDArray[np.float64]  # cumulative time delta (target - reference), + = target slower
    corner_table: pd.DataFrame
    class_summary: pd.DataFrame
    straight_loss_s: float
    total_delta_s: float


def segment_time_loss(target: AlignedLap, reference: AlignedLap) -> NDArray[np.float64]:
    """Time lost (s) in each grid cell, including the closing cell to the finish line."""
    gap = np.append(target.time_s - reference.time_s, target.meta.lap_time_s - reference.meta.lap_time_s)
    cell = np.diff(gap)
    cell[0] += gap[0]
    return cell


def reference_cell_time(reference: AlignedLap) -> NDArray[np.float64]:
    """Time the reference lap spends in each grid cell (s); sums to its lap time."""
    t = np.append(reference.time_s, reference.meta.lap_time_s)
    cell = np.diff(t)
    cell[0] += t[0]
    return cell


def compare_laps(
    target: AlignedLap,
    reference: AlignedLap,
    corner_distance_m: NDArray[np.float64],
    corner_labels: list[str],
) -> LapComparison:
    """Split the lap-time gap into entry / apex / exit phases of each corner, plus straights."""
    s = target.distance_m
    length = target.lap_length_m
    cell = segment_time_loss(target, reference)
    ref_cell = reference_cell_time(reference)
    assigned = np.zeros(len(s), dtype=bool)
    rows = []
    for c_s, label in sorted(zip(corner_distance_m, corner_labels)):
        d = (s - c_s + length / 2) % length - length / 2
        masks = {
            "entry": (d >= ENTRY_M[0]) & (d < ENTRY_M[1]),
            "apex": (d >= APEX_M[0]) & (d < APEX_M[1]),
            "exit": (d >= EXIT_M[0]) & (d < EXIT_M[1]),
        }
        row = {"corner": label, "distance_m": float(c_s)}
        window = np.abs(d) <= 60.0
        v_t_min = float(np.min(target.speed_ms[window]) * 3.6)
        v_r_min = float(np.min(reference.speed_ms[window]) * 3.6)
        row.update(
            target_min_kmh=v_t_min,
            reference_min_kmh=v_r_min,
            min_speed_delta_kmh=v_t_min - v_r_min,
            speed_class=corner_speed_class(v_r_min),
        )
        ref_t = 0.0
        for phase, m in masks.items():
            m = m & ~assigned  # corners closer than 240 m share no cells
            row[f"{phase}_s"] = float(cell[m].sum())
            ref_t += float(ref_cell[m].sum())
            assigned |= m
        row["total_s"] = row["entry_s"] + row["apex_s"] + row["exit_s"]
        row["reference_time_s"] = ref_t
        rows.append(row)
    table = pd.DataFrame(rows)
    straight = float(cell[~assigned].sum())
    total = float(cell.sum())
    summary = (
        table.groupby("speed_class").agg(time_s=("total_s", "sum"), n_corners=("total_s", "size"),
                                          reference_time_s=("reference_time_s", "sum"))
        .reindex(["low", "medium", "high"]).fillna(0.0).reset_index()
    )
    summary = pd.concat(
        [summary, pd.DataFrame([{"speed_class": "straights", "time_s": straight, "n_corners": 0,
                                 "reference_time_s": float(ref_cell[~assigned].sum())}])],
        ignore_index=True,
    )
    # Loss as a share of the time the reference spends there: a uniform percentage deficit
    # gives equal rates everywhere, so rates (not seconds) show where a car is weak.
    summary["loss_rate_pct"] = 100 * summary["time_s"] / summary["reference_time_s"].replace(0, np.nan)
    return LapComparison(
        distance_m=s,
        delta_s=np.cumsum(cell),
        corner_table=table,
        class_summary=summary,
        straight_loss_s=straight,
        total_delta_s=total,
    )
