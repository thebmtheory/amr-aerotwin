# Track Science: where Aston Martin loses time

Physics-first analysis of public Formula 1 timing data: where the Aston Martin loses lap
time, why, and what each fix would be worth. It covers every Grand Prix of 2025 and 2026 so
far, with a calibrated lap simulator, statistical models validated out of sample, and an
interactive report.

**Read first:** the [technical note](docs/technical_note.md), regenerated from the results on every run, and the report site (`make report && make serve`, then open <http://localhost:8765>).

**Single-event report:** [Aston Martin at Silverstone](reports/british-grand-prix.html), every team at the 2025 and 2026 British Grands Prix: qualifying order, where the time goes by section and corner, the straights, grip vs straight-line speed, race pace and season context. `make event-report EVENT="British Grand Prix"` rebuilds it, or any other event.

## Main findings

<!-- findings:start -->
- **In 2026 Aston Martin loses time on the straights at about twice the rate of any other team.** Measured as time lost to the pole lap per second spent in each part of the lap, it loses 3.8% on the straights against at most 1.7% for any other team (Cadillac, 4.05% off pole over a lap against Aston Martin's 4.01%): 2.2 times as much, 90% interval 1.8 to 2.9. Every other team more than 1% off pole loses less per second on the straights than in the corners (ratios 0.22 to 0.61, against 0.92 for Aston Martin), as did Aston Martin in 2025 (0.21).
- **The straight-line loss builds late.** Along each main straight the car starts 5.7 km/h down, holds that through the first half and loses 3.0 km/h more in the second half (90% interval 1.5 to 4.5), at full throttle, on 5 of 6 straights at 5 events. Extra drag, deployment ending earlier and harvesting at full throttle all fit that shape; public timing data cannot tell them apart.
- **The car decides the 2026 qualifying order:** in the median event, between-team differences explain 94% of the variance in qualifying gaps, against 51% in 2025.
- **What did not survive review is withdrawn, not hidden.** An early 36 kW power-deficit claim (an artefact of road gradient and unlike-for-like comparison), a "slow corners are the biggest loss" claim (cars simply spend most time there) and two wind claims (wind data proved uninformative) are documented as withdrawn in the technical note.
<!-- findings:end -->

Exact figures and 90% intervals are in the technical note, which is generated from
`data/processed/season.json`, so the text cannot drift from the data.

## What is in here

| Area | Module | What it does |
|---|---|---|
| Data | `data/repository.py` | Cached access to the TracingInsights archive; offline once fetched |
| Alignment | `data/alignment.py` | Projects every lap onto one reference path; finds the GPS vs car-data clock offset per lap; time from the measured channel |
| Geometry | `physics/kinematics.py` | Curvature from time-domain splines of raw GPS fixes, median over the field; humid-air density |
| Lap simulator | `physics/lapsim.py` | Quasi-steady point mass with friction ellipse, power and drag; sensitivities; iso-lap-time grids |
| Calibration | `modeling/calibration.py` | MAP + Laplace posterior with effective sample size, Metropolis check, Gaussian-process discrepancy |
| Grip | `physics/vehicle_params.py` | Grip vs dynamic pressure at matched reference points; drag/power fits |
| Straights | `modeling/lap_compare.py`, `modeling/energy.py`, `modeling/powertrain.py` | Loss rates by section for every team; position-matched speed along each straight; energy clipping; power/drag fit with gravity removed (reported only where identifiable) |
| Corner model | `modeling/corner_model.py` | Physics, ML and hybrid models of corner speed, validated by whole event; conformal intervals; exact Shapley |
| Race pace | `modeling/race_pace.py` | Fuel and tyre-degradation fixed effects; delete-one-stint jackknife intervals |
| Season | `modeling/season.py` | Supertimes, car vs driver variance, Bayesian changepoints, upgrade difference-in-differences with placebo tests |
| Energy | `modeling/energy.py` | 2026 full-throttle speed loss (clipping) |
| Report | `report/` | Static site (Plotly) and a JavaScript port of the lap simulator for the in-browser setup sandbox |
| Event report | `report/event_report.py` | One circuit, every team: section and corner times, corner speeds checked against GPS, full-throttle speed loss on the straights |

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

`make all` fetches about 40 events (around 130 MB, cached under `data/telemetry_cache`), processes them in parallel and runs the season analyses (one to two minutes on a laptop after the download), and writes `site/` and `docs/technical_note.md`. After the first fetch everything runs offline. The tests need no network: they use a small Silverstone 2025 fixture in `backend/tests/fixtures`.

## How it is tested

- Physics against analytic answers: a constant-radius circle settles on the friction ellipse, a long straight reaches the drag-limited terminal speed, braking distance matches kinematics, curvature of a circle is 1/R.
- Statistical recovery on synthetic data with known truth: lap-sim parameters, grip lines, drag and power, fuel and tyre effects, changepoints, upgrade effects. Interval *coverage* is checked by Monte Carlo, not just point estimates.
- Leakage guards: the corner model's folds never split an event, and target speeds are never features.
- Exact Shapley efficiency, conformal coverage, placebo-test calibration under the null, and race-pace interval coverage with autocorrelated errors.
- Independent review: separate physics, statistics and code reviews were run against the full results, and every claim in the report was revised to what survived them.
- The JavaScript simulator matches the Python one to 1e-9.
- An end-to-end run on real Silverstone data must close on the official lap-time gap.

## Data quality gates

<!-- gates:start -->
Every lap is checked against limits that real broken laps fail: GPS distance to the reference line, GPS position vs the timing line at both ends, consistency of speed with the timing channel, GPS speed vs wheel speed, sample gaps, speed trap vs peak speed, frozen car data (speed and rpm stuck for over 100 m, as on both Aston Martins at Baku 2026) and car-data stalls (speed, throttle and brake held for 0.5–1.5 s while GPS shows the car braking, then a jump no car can make). The feed's 104% "invalid throttle" marker is repaired rather than rejected. Every event's curvature must integrate to the circuit's own turn count (zero for the figure-of-eight at Suzuka). 717 of 758 laps pass. Events that fail are listed with reasons in the report; 3 (Chinese 2026, Italian 2026, Japanese 2026) have too few laps that pass, because of telemetry dropouts, and 2 (Bahrain 2026, Spanish 2026) have source files missing from the archive.
<!-- gates:end -->

## Limits

Public data has no ride heights, tyre temperatures, fuel loads or ERS state, so grip and aero figures are effective point-mass values and “deployed power” includes energy strategy. Upgrade windows are short. Details are in the technical note.

## Sources

Telemetry: [TracingInsights](https://github.com/TracingInsights). Regulations and declared upgrades: FIA documents listed in [data/reference/SOURCES.md](data/reference/SOURCES.md). Independent work; not affiliated with Aston Martin Aramco F1 Team.
