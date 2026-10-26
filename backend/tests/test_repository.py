"""Archive access: wind averaging, lap cleaning, offline behaviour."""

import numpy as np
import pandas as pd
import pytest
from amr_aerotwin.data.repository import DataUnavailableError, TelemetryRepository, fastest_valid_lap, vector_mean_wind


def test_vector_mean_wind_handles_north_wraparound():
    speed, direction = vector_mean_wind(np.array([4.0, 4.0]), np.array([350.0, 10.0]))
    assert speed == pytest.approx(4.0 * np.cos(np.radians(10)), rel=1e-6)
    assert min(direction, 360 - direction) < 1e-6  # a naive mean would say 180


def test_session_laps_cleans_none_strings(fixture_repo):
    laps = fixture_repo.session_laps(2025, "British Grand Prix", "Qualifying")
    assert laps["time"].dtype.kind == "f"
    assert laps["time"].isna().any()  # out-laps are 'None' in the raw file
    assert laps["del"].dtype == bool


def test_fastest_valid_lap_skips_deleted_laps():
    laps = pd.DataFrame({"drv": ["A", "A", "A"], "time": [80.0, 81.0, np.nan], "del": [True, False, False], "lap": [1, 2, 3]})
    assert fastest_valid_lap(laps, "A")["lap"] == 2
    assert fastest_valid_lap(laps, "B") is None


def test_offline_repository_raises_for_uncached_file(tmp_path):
    repo = TelemetryRepository(tmp_path, offline=True)
    with pytest.raises(DataUnavailableError):
        repo.fetch_json(2025, "Nowhere Grand Prix/Qualifying/weather.json")


def test_corners_are_converted_to_metres(fixture_repo):
    c = fixture_repo.corners(2025, "British Grand Prix")
    assert len(c) >= 15 and c["x_m"].abs().max() < 5000  # decimetres would be > 10,000
