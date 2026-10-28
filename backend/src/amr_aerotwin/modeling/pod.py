"""Proper orthogonal decomposition (POD) of one event's speed traces: a reduced-order model of a lap.

Each lap is a row of the snapshot matrix on a shared distance grid. The modes come from the SVD of the
mean-centred matrix, and a lap's modal coefficients describe how its speed profile differs from the field.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import svd


@dataclass(frozen=True)
class PODResult:
    n_modes: int
    singular_values: NDArray[np.float64]
    explained_variance_ratio: NDArray[np.float64]  # all modes
    spatial_modes: NDArray[np.float64]  # (n_modes, N_grid), unit norm
    modal_coefficients: NDArray[np.float64]  # (n_snapshots, n_modes)
    mean_trace: NDArray[np.float64]
    reconstruction_rmse: float
    loo_reconstruction_rmse: float  # held-out laps projected on modes fitted without them


class PODReducedOrderModel:
    """Truncated SVD of a snapshot matrix (n_snapshots, N_grid)."""

    def __init__(self, n_modes: int = 3) -> None:
        self.n_modes = n_modes

    def fit_transform(self, snapshot_matrix: NDArray[np.float64]) -> PODResult:
        if snapshot_matrix.ndim != 2:
            raise ValueError("snapshot_matrix must be 2D of shape (n_snapshots, N_grid)")
        n = snapshot_matrix.shape[0]
        k = min(self.n_modes, n)
        mean = snapshot_matrix.mean(axis=0)
        centred = snapshot_matrix - mean
        u, sigma, vt = svd(centred, full_matrices=False)
        energy = sigma**2
        ratio = energy / max(float(energy.sum()), 1e-12)
        modes = vt[:k]
        coeffs = u[:, :k] * sigma[:k]
        recon = mean + coeffs @ modes
        rmse = float(np.sqrt(np.mean((snapshot_matrix - recon) ** 2)))
        return PODResult(
            n_modes=k,
            singular_values=sigma,
            explained_variance_ratio=ratio,
            spatial_modes=modes,
            modal_coefficients=coeffs,
            mean_trace=mean,
            reconstruction_rmse=rmse,
            loo_reconstruction_rmse=self._leave_one_out_rmse(snapshot_matrix, k),
        )

    @staticmethod
    def _leave_one_out_rmse(x: NDArray[np.float64], k: int) -> float:
        """RMS error over laps, each reconstructed from modes fitted on the others; NaN below 4 laps."""
        n = x.shape[0]
        if n < 4:
            return float("nan")
        errs = []
        for i in range(n):
            train = np.delete(x, i, axis=0)
            mean = train.mean(axis=0)
            _, _, vt = svd(train - mean, full_matrices=False)
            modes = vt[: min(k, n - 2)]
            c = (x[i] - mean) @ modes.T
            errs.append(np.mean((x[i] - mean - c @ modes) ** 2))
        return float(np.sqrt(np.mean(errs)))
