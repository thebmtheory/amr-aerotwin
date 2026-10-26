# Track Science: where Aston Martin loses time

Physics-first analysis of public Formula 1 timing data: where the Aston Martin loses lap
time, why, and what each fix would be worth. It covers every Grand Prix of 2025 and 2026 so
far, with a calibrated lap simulator, statistical models validated out of sample, and an
interactive report.

**Read first:** the [technical note](docs/technical_note.md), regenerated from the results on every run, and the report site (`make report && make serve`, then open <http://localhost:8765>).

## Main findings

- **Slow corners are where the Aston Martin loses most, in both seasons.** About half a second of a one-second qualifying gap to pole in 2025 and about 1.2 s of 3.5 s in 2026, across two cars built to different rules with the same drivers.
- **In 2026 the straight-line deficit has two parts.** The car starts each main straight about 6.5 km/h down at corner exit, holds that through the first half, then loses another ~3 km/h in the second half, where 2026 cars run out of deployable energy. Extra drag would spread that loss evenly, so the late timing fits deployment ending earlier than on rival cars. The 2025 car shows no such pattern.
- **Power vs drag cannot be separated from public timing data.** Over one straight the two are almost perfectly collinear. An earlier version of this project claimed a 36 kW power deficit; independent review showed it was an artefact of road gradient and unlike-for-like comparison, and it is withdrawn in the note.
- **A data finding for anyone using this archive:** the GPS and car-data streams are offset by about 0.11 s and GPS is interpolated. That misplaces samples by about 9 m at 300 km/h, enough to corrupt braking-point comparisons. The pipeline corrects it per lap.

Exact figures and 90% intervals are in the technical note, which is generated from
`data/processed/season.json`, so the text cannot drift from the data.

## What is in here

| Area | Module | What it does |
|---|---|---|
| Data | `data/repository.py` | Cached access to the TracingInsights archive; offline once fetched |
| Alignment | `data/alignment.py` | Projects every lap onto one reference path; finds the GPS vs car-data clock offset per lap; time from the measured channel |
| Geometry | `physics/kinematics.py` | Curvature from time-domain splines of raw GPS fixes, median over the field; humid-air density; wind in the car frame |
| Lap simulator | `physics/lapsim.py` | Quasi-steady point mass with friction ellipse, power and drag; sensitivities; iso-lap-time grids |
| Calibration | `modeling/calibration.py` | MAP + Laplace posterior with effective sample size, Metropolis check, Gaussian-process discrepancy |
| Grip | `physics/vehicle_params.py` | Grip vs dynamic pressure at matched reference points; drag/power fits |
| Straights | `modeling/energy.py`, `modeling/powertrain.py` | Position-matched speed along each straight; energy clipping; joint power/drag fit with gravity removed |
| Corner model | `modeling/corner_model.py` | Physics, ML and hybrid models of corner speed, validated by whole event; conformal intervals; exact Shapley |
| Race pace | `modeling/race_pace.py` | Fuel and tyre-degradation fixed effects; stint-level uncertainty |
| Season | `modeling/season.py` | Supertimes, car vs driver variance, Bayesian changepoints, upgrade difference-in-differences with placebo tests |
| Energy | `modeling/energy.py` | 2026 full-throttle speed loss (clipping) |
| Report | `report/` | Static site (Plotly) and a JavaScript port of the lap simulator for the in-browser setup sandbox |

## Run it

```bash
make install
```

```bash
make test
```

```bash
make all
```

```bash
make serve
```

`make all` fetches about 40 events (around 60 MB, cached under `data/telemetry_cache`), processes them in parallel (under a minute on a laptop), runs the season analyses, and writes `site/` and `docs/technical_note.md`. After the first fetch everything runs offline. The tests need no network: they use a small Silverstone 2025 fixture in `backend/tests/fixtures`.

## How it is tested

- Physics against analytic answers: a constant-radius circle settles on the friction ellipse, a long straight reaches the drag-limited terminal speed, braking distance matches kinematics, curvature of a circle is 1/R.
- Statistical recovery on synthetic data with known truth: lap-sim parameters, grip lines, drag and power, fuel and tyre effects, changepoints, upgrade effects. Interval *coverage* is checked by Monte Carlo, not just point estimates.
- Leakage guards: the corner model's folds never split an event, and target speeds are never features.
- Exact Shapley efficiency, conformal coverage, placebo-test calibration under the null, and race-pace interval coverage with autocorrelated errors.
- Independent review: separate physics, statistics and code reviews were run against the full results, and every claim in the report was revised to what survived them.
- The JavaScript simulator matches the Python one to 1e-9.
- An end-to-end run on real Silverstone data must close on the official lap-time gap.

## Data quality gates

Every lap is checked against limits that real broken laps fail: GPS distance to the reference line, GPS position vs the timing line at both ends, consistency of speed with the timing channel, GPS speed vs wheel speed, sample gaps, and speed trap vs peak speed. Every event's curvature must integrate to the circuit's own turn count (zero for the figure-of-eight at Suzuka). Events that fail are listed with reasons in the report; three 2026 events are excluded because their archived telemetry has dropouts of up to 350 m, and two more have source files missing.

## Limits

Public data has no ride heights, tyre temperatures, fuel loads or ERS state, so grip and aero figures are effective point-mass values and “deployed power” includes energy strategy. Upgrade windows are short. Details are in the technical note.

## Sources

Telemetry: [TracingInsights](https://github.com/TracingInsights). Regulations and declared upgrades: FIA documents listed in [data/reference/SOURCES.md](data/reference/SOURCES.md). Independent work; not affiliated with Aston Martin Aramco F1 Team.
