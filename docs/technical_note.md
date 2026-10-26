# Where Aston Martin loses time: technical note

*Generated from `data/processed/season.json` by `aerotwin report`. Public data only; not affiliated with Aston Martin Aramco F1 Team. All intervals are 90%; unless stated, comparisons are with the median of the other teams at the same event.*

## Findings

1. **Slow corners are Aston Martin's biggest loss in both seasons.** Splitting the qualifying gap to pole by track section (model-free, sums to the official gap): 0.45 s [0.32, 0.59] of 0.95 s in 2025 and 1.24 s [0.95, 1.54] of 3.46 s in 2026. It persists across two cars built to different rules, with the same drivers, so it reflects something durable (set-up, mechanical grip and traction, or driving style); public data cannot say which.
2. **In 2026 the straight-line deficit has two parts.** Compared piece by piece along each main straight, Aston Martin starts 6.5 km/h down at corner exit [-7.5, -5.4], changes little in the first half (−1.2 km/h [-2.1 to -0.1]) and loses −3.3 km/h [-4.9 to -1.7] in the second half: 2.8 times the first-half change, where extra drag would give about 1.06 times and a power deficit would bite earlier. A loss that appears halfway down the straight fits electrical deployment ending earlier than on rival cars. The car's speed drop after peak is +2.0 km/h larger than the field's [0.5, 3.8]. The 2025 car shows no such growth (+0.6 km/h [-0.2 to 1.4]).
3. **Lap-time cost.** The main straights cost 0.33 s per lap [0.23 to 0.44] in 2026, of which 0.10 s [0.04 to 0.16] is the speed lost along the straight; most of the 3.5 s gap is in the corners.
4. **Power vs drag is not identifiable from public data.** A joint fit of deployed power and drag area on the energy-rich part of each straight (gravity removed with GPS altitude, leave-one-out field, tow-free samples) gives correlation 0.99 between the two and intervals of -101 to 223 kW and -0.20 to 1.15 m². An earlier version of this project claimed a ~36 kW power deficit; it did not survive gradient correction and like-for-like comparison, and is withdrawn.
5. **The car decides the 2026 order.** Between-team share of qualifying-gap variance: 24% pooled in 2025 (median event 47%) vs 88% in 2026 (median event 93%).
6. **The 2026 Hungary upgrade: suggestive, not established.** A changepoint model not told upgrade dates rates the Hungarian Grand Prix the most likely shift (posterior 0.27), but no change is about as plausible (0.48). Fast-corner grip vs the other teams went 93.2% → 99.3% (shift +6.1 ± 6.6 points, 2 clean events after).
7. **Wind is not estimable** from session-level weather data (fast-corner interval about ±1.5 km/h per m/s); the prototype's 0.41 s crosswind attribution has no support.
8. **Data finding.** In the public TracingInsights archive (F1 live timing processed with FastF1) the GPS and car-data streams are offset by about 0.11 s, and GPS is linearly interpolated onto car-data timestamps. Uncorrected, that misplaces samples by about 9 m at 300 km/h, enough to corrupt any braking-point comparison. This project detects original fixes, estimates the offset per lap from GPS-vs-wheel speed, and corrects it.

## Data

Fastest valid qualifying lap of every driver at 37 Grands Prix (2025 and 2026 to date), plus every lap of each race, from the public TracingInsights archive of F1 live timing. Car data (speed, throttle, brake, gear, rpm) arrives at roughly 4–10 Hz and GPS at about 4 Hz. 731 of 758 laps pass the automated data checks. Excluded events and reasons are listed in the report. Regulation figures (minimum mass, MGU-K taper) and Aston Martin's declared upgrades come from FIA documents (data/reference/SOURCES.md).

## Method

1. **Alignment.** Each lap is projected onto the pole lap's path. The archive linearly interpolates GPS onto car-data timestamps; original fixes are identified (whole-decimetre coordinates) and the clock offset between the GPS and car-data streams (median 0.11 s) is estimated per lap by matching GPS-derived speed to wheel speed. Time comes from the measured timing channel, pinned to zero at the line and the official lap time at the end.
2. **Geometry.** Curvature is a smoothing spline of x(t), y(t) through raw fixes (time-domain, so position noise does not scale with speed), with the smoothing level chosen per event by the GPS-speed cross-check, then the median across all drivers. Integrated curvature must match the circuit's turn count (one for most circuits, zero for figure-of-eight Suzuka).
3. **Lap simulator.** Quasi-steady point mass: grip μ(g + qC<sub>L</sub>A/m) on a friction ellipse, power limit, drag and rolling resistance, closed-lap forward/backward passes. Calibrated to each measured lap by MAP with weak log-normal priors; Laplace posterior with an AR(1) effective sample size; checked against a Metropolis sampler; a Gaussian process on the residual shows where point-mass physics fails.
4. **Grip.** One near-limit point per corner (flat-out corners excluded) gives a line of limit acceleration against dynamic pressure; it is read only at two event-wide reference pressures because tyre load sensitivity makes absolute μ and C<sub>L</sub>A unidentifiable from public data.
5. **Straights.** Main straights from the pole lap are split into ten equal pieces; each team's speed in each piece is compared with the other teams' median. Joint power and drag fits use the acceleration phase only (up to the field-median peak), gravity removed with GPS altitude, tow-free samples, 2026 speeds below the MGU-K taper.
6. **Corner model.** Minimum corner speed at unseen circuits, cross-validated by whole circuit. Physics baseline: the lap simulator on the held-out track with a nominal car from the training events' calibrations only. Hybrid: gradient boosting on its residual. Split-conformal intervals; exact baseline Shapley values of the reported model.
7. **Race pace.** Fixed effects for driver, compound and per-compound tyre degradation plus a fuel term per lap on green-flag laps; intervals from a wild cluster bootstrap by driver (Webb weights), checked for coverage with autocorrelated errors.
8. **Season.** Supertime gaps; per-event one-way random-effects variance split; single-changepoint model with exact normal-inverse-gamma evidence, effect averaged over the changepoint posterior and prior sensitivity reported; upgrade difference-in-differences (team and event fixed effects, team-specific track-type slopes) with permutation p-values (team and time placebos), Holm adjustment and minimum detectable effect.

## Validation

- Automated tests (backend/tests): analytic physics (constant-radius circle, terminal speed, braking distance), parameter recovery and interval coverage on synthetic data, leakage guards, exact Shapley efficiency, JavaScript–Python simulator parity, and an end-to-end run on real Silverstone data.
- Corner model, out of sample by whole circuit: steady-state formula R² 0.63, lap sim on GPS geometry alone R² 0.91, gradient boosting R² 0.77, hybrid R² 0.92 (RMSE 20.6 km/h); within-corner R² ≈ 0 for all models. Conformal coverage 89.3% at a 90% target (median event 93%).
- Lap-sim accounting of the 2026 gap: 72% of the mean gap [46, 92%], rank correlation with events r = 0.78, but event-level R² < 0: an accounting, not a forecast.
- Upgrade effects (difference-in-differences, 4 events either side):
  - 2025 Emilia Romagna Grand Prix: −0.89% (detectable ≥ 0.71%; team placebo p = 0.10, Holm-adjusted 0.45; time placebo p = 0.05; 4/4 events)
  - 2025 British Grand Prix: −0.03% (detectable ≥ 0.73%; team placebo p = 0.90, Holm-adjusted 1.00; time placebo p = 0.95; 4/4 events)
  - 2025 Belgian Grand Prix: +0.05% (detectable ≥ 0.79%; team placebo p = 1.00, Holm-adjusted 1.00; time placebo p = 0.95; 4/4 events)
  - 2026 Hungarian Grand Prix: −2.19% (detectable ≥ 1.02%; team placebo p = 0.09, Holm-adjusted 0.45; time placebo p = 0.12; 3/3 events)
  - 2026 Dutch Grand Prix: −1.43% (detectable ≥ 0.84%; team placebo p = 0.09, Holm-adjusted 0.45; time placebo p = 0.38; 3/3 events)

## Limitations

- Public telemetry has no ride heights, suspension, tyre temperatures, fuel loads or ERS state. Grip and aero figures are effective point-mass values.
- Energy deployment is inferred from speed; the ERS state is not published, so the late-straight loss could also reflect harvesting strategy or top-end drag in active-aero straight mode.
- Upgrade windows are short (four events) and tracks differ; placebo tests guard against chance but not against every confounder. Overlapping windows (Hungary and Dutch GP 2026) are not independent.
- Mass is the regulation minimum plus an assumed 5 kg of qualifying fuel; a 2 kg error moves C<sub>L</sub>A estimates by about 0.25%.

## What this would look like with team data

With ERS state-of-charge, MGU-K torque and engine maps, the power-equivalent deficit could be split into ICE output, deployment strategy and harvesting losses. With ride-height and aero-map data, the grip-vs-dynamic-pressure line becomes a direct track-to-tunnel correlation check. The calibration and discrepancy framework is built so that higher-fidelity simulation outputs can replace the point-mass model without changing the rest of the pipeline.
