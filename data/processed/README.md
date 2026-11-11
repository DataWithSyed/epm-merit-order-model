# Processed panels (derived, attributed)

- `hourly_panel.csv`: hourly means of 15-min Energy-Charts v2 data, 2025-01-01 to 2026-10-31 (Europe/Berlin), with timestamps stored in UTC. Sources: Energy-Charts.info (Fraunhofer ISE) public net generation / load / cross-border trade; DE-LU day-ahead price from Bundesnetzagentur | SMARD.de. CC BY 4.0. Sign convention: `net_trade_mw` > 0 means net import; `ps_cons_mw` is negative (consumption).
- `monthly_drivers.csv`: World Bank Pink Sheet (CC BY 4.0) gas Europe / coal South Africa / Brent, ECB USD per EUR, converted to €/MWh_th (conversions in `src/meritorder/data.py`); EUA = DEHSt German auction average (`data/reference/eua_dehst_annual.csv`, carried over from step 1).
- `installed_gw.csv`: Energy-Charts yearly installed capacity (GW).

Rebuild with `python scripts/fetch_data.py`.
