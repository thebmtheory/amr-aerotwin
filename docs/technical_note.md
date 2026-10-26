# Where Aston Martin loses time: technical note

*Generated from `data/processed/season.json` by `aerotwin report`. Public data only; not affiliated with Aston Martin Aramco F1 Team. Intervals are 90% bootstrap intervals over events unless stated.*

## Findings

1. **In 2026 Aston Martin loses time on the straights at about twice the rate of any other team.** Loss rate = time lost to the pole lap in a section ÷ the pole lap's time there, summed over events. Aston Martin's 2026 straight-line rate is 3.78% [3.34, 4.16] against 4.30% in the corners, a ratio of 0.88 [0.73 to 1.10]. Every other team's straight-line rate is between 0.19% and 1.69%; Aston Martin's is 2.23 times the highest of them (Cadillac) [1.79 to 2.86, the maximum over rivals taken inside each bootstrap draw], so "twice" is the central estimate, not a lower bound (77% of bootstrap draws exceed 2). Teams at least 1% off pole over a lap have straights-to-corners ratios between 0.20 and 0.61. Cadillac, as slow over a lap (4.05% vs 4.14%), loses 1.69% on the straights. Nearer the front the ratio is unstable because the corner deficit is close to zero; Ferrari is the one front-runner that loses more on the straights (1.03%) than in the corners (0.11%), at a much lower level than Aston Martin. In 2025 Aston Martin's ratio was 0.21 [0.05 to 0.40], in line with the field. Raw seconds by corner type are misleading here: cars spend the most time in slow corners, so slow corners carry the most seconds for almost every team.
2. **Where on the straight.** Compared piece by piece along the main straights (those clear of the timing line), Aston Martin starts 5.7 km/h down, holds that through the first half (−0.9 km/h [-2.8 to 0.6]) and loses 3.1 km/h more in the second half [-4.5 to -1.6], at full throttle, on 5 of 6 straights at 5 events. The shape does not identify the cause: a point-mass simulation reproduces it with extra drag alone, and energy deployment ending earlier or harvesting at full throttle fit it as well. The 2025 car shows no growth (−0.2 km/h [-1.4 to 0.8]). Main straights cost 0.28 s per lap [0.19 to 0.37] in 2026.
3. **Power vs drag is not identifiable from public timing data.** Over one straight the two terms are collinear; fits need at least 200 m of clean straight and a 60 km/h speed range and are reported only where that holds. An earlier version of this project claimed a ~36 kW power deficit; it came from not correcting for gradient and comparing cars on different stretches of track, and is withdrawn.
4. **The car decides the 2026 order.** In the median event the between-team share of qualifying-gap variance is 51% in 2025 and 94% in 2026 (laps outside 107% of the best excluded).
5. **Physics accounting.** Giving the pole car's calibrated simulator Aston Martin's measured grip and top-speed gap accounts for 89% of its mean 2026 gap [74, 100%] over 6 events (event-level R² 0.54). It is an accounting, not a forecast.
6. **The 2026 Hungary upgrade: suggestive, not established.** A changepoint model not told upgrade dates rates the Hungarian Grand Prix the most likely shift (posterior 0.39 vs 0.30 for no change), step −1.40% [-2.33 to -0.30]. Fast-corner grip vs the other teams went 93.3% → 100.0% (7 events before, 2 after). The placebo-based test cannot reach p < 0.09 with ten rivals, so it cannot settle this.
7. **Wind is left out, on evidence.** Rotating the wind direction through 360° across 11 windy sessions, no orientation improves the acceleration fit by more than a few percent and the assumed one was best in 9% of them (chance: 8%). Session-level wind readings are not informative enough, so dynamic pressure uses ground speed. Earlier wind claims are withdrawn.
8. **Data note.** Placing car data by GPS position needs a per-lap timing correction in this archive (median 0.11 s, about 9 m at 300 km/h); the archive's odometer distance is unaffected. Frozen car-data stretches (e.g. Baku 2026) and the feed's 104% throttle marker are detected and handled.

## Data

Fastest valid qualifying lap of every driver at 37 Grands Prix (2025 and 2026 to date), plus every lap of each race, from the public TracingInsights archive of F1 live timing. Car data (speed, throttle, brake, gear, rpm) arrives at roughly 4–10 Hz and GPS at about 4 Hz. 723 of 758 laps pass the automated data checks. Excluded events and reasons are listed in the report. Regulation figures (minimum mass, MGU-K taper) and Aston Martin's declared upgrades come from FIA documents (data/reference/SOURCES.md).

## Method

1. **Alignment.** Each lap is projected onto the pole lap's path. The archive linearly interpolates GPS onto car-data timestamps; original fixes are identified (whole-decimetre coordinates) and the clock offset between the GPS and car-data streams (median 0.11 s) is estimated per lap by matching GPS-derived speed to wheel speed. Time comes from the measured timing channel, pinned to zero at the line and the official lap time at the end.
2. **Geometry.** Curvature is a smoothing spline of x(t), y(t) through raw fixes (time-domain, so position noise does not scale with speed), with the smoothing level chosen per event by the GPS-speed cross-check, then the median across all drivers. Integrated curvature must match the circuit's turn count (one for most circuits, zero for figure-of-eight Suzuka).
3. **Lap simulator.** Quasi-steady point mass: grip μ(g + qC<sub>L</sub>A/m) on a friction ellipse, power limit, drag and rolling resistance, closed-lap forward/backward passes. Calibrated to each measured lap by MAP with weak log-normal priors; Laplace posterior with an AR(1) effective sample size; checked against a Metropolis sampler; a Gaussian process on the residual shows where point-mass physics fails.
4. **Grip.** One near-limit point per corner (flat-out corners excluded) gives a line of limit acceleration against dynamic pressure; it is read only at two event-wide reference pressures because tyre load sensitivity makes absolute μ and C<sub>L</sub>A unidentifiable from public data.
5. **Straights.** Main straights from the pole lap are split into ten equal pieces; each team's speed in each piece is compared with the other teams' median. Joint power and drag fits use the acceleration phase only (up to the field-median peak), gravity removed with GPS altitude, tow-free samples, 2026 speeds below the MGU-K taper.
6. **Corner model.** Minimum corner speed at unseen circuits, cross-validated by whole circuit. Physics baseline: the lap simulator on the held-out track with a nominal car from the training events' calibrations only. Hybrid: gradient boosting on its residual. Split-conformal intervals; exact baseline Shapley values of the reported model.
7. **Race pace.** Fixed effects for driver, compound and per-compound tyre degradation plus a fuel term per lap on green-flag laps; intervals from a delete-one-stint jackknife, checked for coverage of the fuel effect and of team gaps with autocorrelated errors.
8. **Season.** Supertime gaps; per-event one-way random-effects variance split; single-changepoint model with exact normal-inverse-gamma evidence, effect averaged over the changepoint posterior and prior sensitivity reported; upgrade difference-in-differences (team and event fixed effects, team-specific track-type slopes) with permutation p-values (team and time placebos), Holm adjustment and minimum detectable effect.

## Validation

- Automated tests (backend/tests): analytic physics (constant-radius circle, terminal speed, braking distance), parameter recovery and interval coverage on synthetic data, leakage guards, exact Shapley efficiency, JavaScript–Python simulator parity, and an end-to-end run on real Silverstone data.
- Corner model, out of sample by whole circuit: steady-state formula R² 0.63, lap sim on GPS geometry alone R² 0.91, gradient boosting R² 0.79, hybrid R² 0.93 (RMSE 19.8 km/h); within-corner R² ≈ 0 for all models. Conformal coverage 89.4% at a 90% target (median event 94%, worst 33%).
- Lap-sim accounting of the 2026 gap: 89% of the mean gap [74, 100%], rank correlation with events r = 0.97, but event-level R² < 0: an accounting, not a forecast.
- Upgrade effects (difference-in-differences, 4 events either side):
  - 2025 Emilia Romagna Grand Prix: −0.90% (detectable ≥ 0.72%; team placebo p = 0.10, Holm-adjusted 0.45; time placebo p = 0.05; 4/4 events)
  - 2025 British Grand Prix: −0.03% (detectable ≥ 0.73%; team placebo p = 0.90, Holm-adjusted 1.00; time placebo p = 0.95; 4/4 events)
  - 2025 Belgian Grand Prix: +0.05% (detectable ≥ 0.79%; team placebo p = 1.00, Holm-adjusted 1.00; time placebo p = 0.95; 4/4 events)
  - 2026 Hungarian Grand Prix: −2.26% (detectable ≥ 0.69%; team placebo p = 0.09, Holm-adjusted 0.45; time placebo p = 0.11; 4/4 events)
  - 2026 Dutch Grand Prix: −1.71% (detectable ≥ 0.82%; team placebo p = 0.09, Holm-adjusted 0.45; time placebo p = 0.22; 4/4 events)

## Limitations

- Public telemetry has no ride heights, suspension, tyre temperatures, fuel loads or ERS state. Grip and aero figures are effective point-mass values.
- Energy deployment is inferred from speed; the ERS state is not published, so the late-straight loss could also reflect harvesting strategy or top-end drag in active-aero straight mode.
- Laps are set at different times in a session (a car knocked out in Q1 sets its best lap on a greener track than pole). Track evolution mostly adds grip, so it inflates corner loss rates more than straight-line ones.
- Upgrade windows are short (four events) and tracks differ; placebo tests guard against chance but not against every confounder. Overlapping windows (Hungary and Dutch GP 2026) are not independent.
- Mass is the regulation minimum plus an assumed 5 kg of qualifying fuel; a 2 kg error moves C<sub>L</sub>A estimates by about 0.25%.

## What this would look like with team data

With ERS state-of-charge, MGU-K torque and engine maps, the power-equivalent deficit could be split into ICE output, deployment strategy and harvesting losses. With ride-height and aero-map data, the grip-vs-dynamic-pressure line becomes a direct track-to-tunnel correlation check. The calibration and discrepancy framework is built so that higher-fidelity simulation outputs can replace the point-mass model without changing the rest of the pipeline.
