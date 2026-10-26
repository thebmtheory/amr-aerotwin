# Reference data sources

All figures were checked against primary FIA documents on 2026-10-25.

## Regulations used in `domain.py`

| Item | Value | Source |
|---|---|---|
| 2025 minimum mass (car + driver, no fuel) | 800 kg | [FIA 2025 Technical Regulations, Issue 03, Art. 4.1](https://www.fia.com/sites/default/files/documents/fia_2025_formula_1_technical_regulations_-_issue_03_-_2025-04-07.pdf) |
| 2026 minimum mass, qualifying | 726 kg + Nominal Tyre Mass (~44 kg, implied by FIA's 768 kg headline) | [FIA 2026 Section C, Issue 20, Art. C4.1](https://api.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf) |
| 2026 minimum mass, other sessions | 724 kg + Nominal Tyre Mass (~768 kg) | same |
| 2026 MGU-K power | 350 kW, tapered as P = 1800 - 5v kW above 290 km/h (0 at 345 km/h) without Overtake | same, Art. C5.2.7-C5.2.8 |
| 2026 ERS recharge per lap | 8.5 MJ (can be reduced per circuit; as low as 4 MJ in qualifying) | same, Art. C5.2.10 |
| 2026 aero | Corner Mode / Straight Mode active aero; DRS removed | same, Art. C3.10-C3.11 |
| 2026 public "drs" channel | Always 0; active-aero and ERS state are not published | [FastF1 discussion #861](https://github.com/theOehrly/Fast-F1/discussions/861) |

The Nominal Tyre Mass itself is not published in a primary source, so the 2026 masses
carry an assumption of about ±2 kg. Fitted ClA scales linearly with mass (2 kg = 0.26%).

## `amr_upgrades.csv`

Aston Martin entries from the FIA "Car Presentation Submissions" document for each Grand
Prix (one PDF per event, linked per row). Events where Aston Martin declared "No updates
submitted" are omitted. `major_performance_upgrade` values:
`launch` (season-launch car), `major` (declared multi-part performance package),
`partial`, `minor`, `circuit` (circuit-specific wing/cooling, not a permanent upgrade).

Telemetry: the public [TracingInsights](https://github.com/TracingInsights) archive of
F1 live timing (one repository per season).
