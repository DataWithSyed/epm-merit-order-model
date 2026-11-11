"""Thermal fleet definition for the DE stack.

Installed capacities come from Energy-Charts (`installed_gw.csv`, end-of-year
stock). Everything else here is an ASSUMED engineering parameter, documented in
docs/assumptions.md (IDs A-M*). Emission factors are IPCC 2006 Guidelines,
Vol. 2 (Energy), Ch. 2, Table 2.2 default CO2 factors.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# IPCC 2006 default CO2 emission factors (kg CO2 / TJ) -> t CO2 / MWh_th (x 0.0036)
EF_T_PER_MWH_TH = {
    "lignite": 101_000 * 3.6e-6,     # 0.3636
    "hard_coal": 94_600 * 3.6e-6,    # 0.3406 (other bituminous coal)
    "gas": 56_100 * 3.6e-6,          # 0.2020 (natural gas)
    "oil": 74_100 * 3.6e-6,          # 0.2668 (gas/diesel oil)
}


@dataclass(frozen=True)
class TechSpec:
    name: str
    fuel: str                 # lignite | hard_coal | gas | oil
    capacity_key: str         # column in installed_gw.csv
    capacity_share: float     # share of that column assigned to this tech
    eff_low: float            # ASSUMED net electrical efficiency range
    eff_high: float
    availability: float       # ASSUMED share of installed capacity offered
    vom: float                # ASSUMED variable O&M, EUR/MWh_el
    fuel_adder: float = 0.0   # ASSUMED delivered-fuel adder, EUR/MWh_th


@dataclass(frozen=True)
class FleetParams:
    techs: tuple[TechSpec, ...]
    n_bands: int = 10
    lignite_fuel_eur_mwh_th: float = 4.0   # ASSUMED mine-mouth marginal fuel cost
    mustrun_quantile: float = 0.02          # thermal must-run = this quantile of observed output (train only)
    surplus_price: float = 0.0              # price when demand is below thermal must-run
    scarcity_u0: float = 1.0                # utilisation above which a scarcity adder applies
    scarcity_gamma: float = 0.0             # EUR/MWh per unit utilisation above u0 (quadratic)
    avail_scale: float = 1.0                # multiplier on all availabilities (calibration knob)
    eff_shift: float = 0.0                  # additive shift on all efficiencies (calibration knob)
    extra: dict = field(default_factory=dict)

    def with_(self, **kw) -> "FleetParams":
        return replace(self, **kw)


DEFAULT_TECHS = (
    TechSpec("lignite", "lignite", "fossil_brown_coal_lignite", 1.0, 0.31, 0.43, 0.85, 4.0),
    TechSpec("hard_coal", "hard_coal", "fossil_hard_coal", 1.0, 0.34, 0.46, 0.65, 4.0, fuel_adder=2.0),
    TechSpec("gas_ccgt", "gas", "fossil_gas", 0.60, 0.46, 0.60, 0.85, 3.0, fuel_adder=2.0),
    TechSpec("gas_peaker", "gas", "fossil_gas", 0.40, 0.30, 0.42, 0.85, 5.0, fuel_adder=2.0),
    TechSpec("oil", "oil", "fossil_oil", 1.0, 0.28, 0.38, 0.50, 5.0, fuel_adder=10.0),
)

DEFAULT_PARAMS = FleetParams(techs=DEFAULT_TECHS)
