# Assumptions register: merit-order model (step 2)

IDs continue the umbrella register (A-D* = data, from step 1). **ASSUMED** means an engineering judgement, not an observation. All of them can be changed in `src/meritorder/fleet.py`.

| ID | Parameter | Value | Basis |
|---|---|---|---|
| A-M1 | Installed thermal capacity | Energy-Charts yearly stock (2025 for 2025 hours, 2026 for 2026 hours) | Observed (Energy-Charts `installed_power`) |
| A-M2 | CO₂ emission factors | lignite 101,000; other bituminous coal 94,600; natural gas 56,100; gas/diesel oil 74,100 kg CO₂/TJ (NCV) | IPCC 2006 Guidelines for National GHG Inventories, Vol. 2 Energy, Ch. 2 Stationary Combustion, Table 2.2 (defaults; checked against the PDF on 2026-11-11) |
| A-M3 | Lignite net efficiency range | 0.31 to 0.43 | ASSUMED fleet spread (old 1970s units to modern BoA-type) |
| A-M4 | Hard-coal net efficiency range | 0.34 to 0.46 | ASSUMED |
| A-M5 | Gas split and efficiency | 60 % CCGT at 0.46 to 0.60; 40 % peaker/steam/engines at 0.30 to 0.42 | ASSUMED |
| A-M6 | Oil efficiency | 0.28 to 0.38 | ASSUMED |
| A-M7 | Availability (share of installed offered) | lignite 0.85, hard coal 0.65, gas 0.85, oil 0.50 | ASSUMED; hard coal is lower because part of the fleet sits in reserves or is out of the market |
| A-M8 | VOM | lignite 4, hard coal 4, CCGT 3, peaker 5, oil 5 €/MWh_el | ASSUMED |
| A-M9 | Delivered-fuel adders | coal +2, gas +2, oil +10 €/MWh_th over the benchmark | ASSUMED freight, handling and network |
| A-M10 | Lignite fuel cost | 4 €/MWh_th | ASSUMED mine-mouth marginal cost (no market price exists) |
| A-M11 | Oil heat content | 5.8 MMBtu/bbl | ASSUMED conventional crude heat content |
| A-M12 | Thermal must-run | 2 % quantile of observed 2025 hourly output per fuel, priced at the surplus price | Data-derived (train window only) |
| A-M13 | Must-run non-thermal supply | observed biomass, hydro (RoR + reservoir), waste, geothermal, others, coal-derived gas | Observed (Energy-Charts) |
| A-M14 | Surplus price | 0 €/MWh when demand on the stack ≤ 0 | ASSUMED (C2 grid tested −40 to 0) |
| A-M15 | Efficiency bands | 10 equal-capacity bands per technology, linear in η | ASSUMED smoothing |
| A-M16 | Train / test split | 2025 / 2026-01..10 | Design choice; C3 refits monthly on the trailing 90 days |
