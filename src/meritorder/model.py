"""Merit-order construction and market clearing."""
from __future__ import annotations

import numpy as np
import pandas as pd

from meritorder.fleet import EF_T_PER_MWH_TH, FleetParams

MUSTRUN_RES_COLS = ["biomass_mw", "waste_mw", "geothermal_mw", "others_mw",
                    "hydro_ror_mw", "hydro_res_mw", "coal_gas_mw"]
THERMAL_OBS = {"lignite": "lignite_mw", "hard_coal": "hard_coal_mw", "gas": "gas_mw", "oil": "oil_mw"}


def fuel_price(fuel: str, m: pd.Series, p: FleetParams) -> float:
    if fuel == "lignite":
        return p.lignite_fuel_eur_mwh_th
    return float(m[{"hard_coal": "coal_eur_mwh_th", "gas": "gas_eur_mwh_th", "oil": "oil_eur_mwh_th"}[fuel]])


def build_stack(month_row: pd.Series, installed_gw: pd.Series, p: FleetParams,
                mustrun_mw: dict[str, float] | None = None) -> pd.DataFrame:
    """Return the sorted supply stack for one month.

    Columns: tech, fuel, eff, srmc (EUR/MWh_el), cap_mw, cum_mw.
    Thermal must-run (MW by fuel) is pulled out of the bands and placed at the
    bottom of the stack at ``surplus_price``.
    """
    rows = []
    mustrun_mw = mustrun_mw or {}
    eua = float(month_row["eua_eur_t"])
    for t in p.techs:
        cap = float(installed_gw[t.capacity_key]) * 1000 * t.capacity_share
        avail = cap * min(1.0, t.availability * p.avail_scale)
        # must-run of this fuel is shared across its techs by installed share
        fuel_cap = sum(float(installed_gw[x.capacity_key]) * 1000 * x.capacity_share
                       for x in p.techs if x.fuel == t.fuel)
        mr = mustrun_mw.get(t.fuel, 0.0) * (cap / fuel_cap if fuel_cap else 0.0)
        mr = min(mr, avail)
        if mr > 0:
            rows.append((t.name + "_mustrun", t.fuel, np.nan, p.surplus_price, mr))
        flex = avail - mr
        effs = np.linspace(t.eff_high, t.eff_low, p.n_bands) + p.eff_shift
        effs = np.clip(effs, 0.15, 0.65)
        fp = fuel_price(t.fuel, month_row, p) + t.fuel_adder
        ef = EF_T_PER_MWH_TH[t.fuel]
        for e in effs:
            srmc = fp / e + ef / e * eua + t.vom
            rows.append((t.name, t.fuel, e, srmc, flex / p.n_bands))
    st = pd.DataFrame(rows, columns=["tech", "fuel", "eff", "srmc", "cap_mw"])
    st = st.sort_values("srmc", kind="stable").reset_index(drop=True)
    st["cum_mw"] = st["cap_mw"].cumsum()
    return st


def clear(demand_mw: np.ndarray, stack: pd.DataFrame, p: FleetParams) -> tuple[np.ndarray, np.ndarray]:
    """Uniform-price clearing of an inelastic demand against the stack.

    Price = SRMC of the marginal band, linearly interpolated with the previous
    band across the band's capacity (smooths the step function). Demand below
    0 or inside the must-run block clears at ``surplus_price``. Demand above
    available capacity clears at the top SRMC. A quadratic scarcity adder
    gamma * max(0, u - u0)^2 * 100 applies on utilisation u = D / available.
    Returns (price, utilisation).
    """
    cum = stack["cum_mw"].to_numpy()
    srmc = stack["srmc"].to_numpy()
    total = cum[-1]
    d = np.asarray(demand_mw, dtype=float)
    idx = np.searchsorted(cum, np.clip(d, 0, None), side="left")
    idx = np.clip(idx, 0, len(cum) - 1)
    lo_cum = np.where(idx > 0, cum[np.maximum(idx - 1, 0)], 0.0)
    lo_p = np.where(idx > 0, srmc[np.maximum(idx - 1, 0)], srmc[0])
    frac = np.clip((d - lo_cum) / np.maximum(cum[idx] - lo_cum, 1e-9), 0, 1)
    price = lo_p + frac * (srmc[idx] - lo_p)
    price = np.where(d <= 0, p.surplus_price, price)
    u = d / total
    adder = p.scarcity_gamma * 100 * np.clip(u - p.scarcity_u0, 0, None) ** 2
    return price + adder, u


def stack_demand(h: pd.DataFrame, mode: str = "trade_exogenous") -> pd.Series:
    """Demand that the domestic thermal stack must serve (MW).

    trade_exogenous: residual load - must-run RES/hydro/waste - realised net imports
                     - realised pumped-storage net output (all observed ex post).
    isolated:        residual load - must-run RES/hydro/waste (no trade, no storage).
    """
    mr = h[MUSTRUN_RES_COLS].sum(axis=1)
    d = h["residual_load_mw"] - mr
    if mode == "trade_exogenous":
        d = d - h["net_trade_mw"] - (h["ps_gen_mw"] + h["ps_cons_mw"])
    elif mode != "isolated":
        raise ValueError(mode)
    return d


def thermal_mustrun(h_train: pd.DataFrame, q: float) -> dict[str, float]:
    return {f: float(h_train[c].quantile(q)) for f, c in THERMAL_OBS.items()}


def run_model(h: pd.DataFrame, monthly: pd.DataFrame, installed: pd.DataFrame, p: FleetParams,
              mustrun_mw: dict[str, float], mode: str = "trade_exogenous") -> pd.DataFrame:
    """Hourly model prices for every hour in ``h``."""
    d = stack_demand(h, mode)
    months = h.index.tz_localize(None).to_period("M") if h.index.tz is not None else h.index.to_period("M")
    out = pd.DataFrame(index=h.index)
    out["demand_mw"] = d
    out["model_price"] = np.nan
    out["utilisation"] = np.nan
    out["marginal_fuel"] = ""
    for m in pd.unique(months):
        mask = np.asarray(months == m)
        yr = m.year if m.year in installed.index else max(installed.dropna(how="all").index)
        st = build_stack(monthly.loc[m], installed.loc[yr], p, mustrun_mw)
        price, u = clear(d.to_numpy()[mask], st, p)
        out.loc[mask, "model_price"] = price
        out.loc[mask, "utilisation"] = u
        idx = np.clip(np.searchsorted(st["cum_mw"].to_numpy(), d.to_numpy()[mask]), 0, len(st) - 1)
        lab = st["tech"].to_numpy()[idx]
        lab = np.where(d.to_numpy()[mask] <= 0, "surplus", lab)
        out.loc[mask, "marginal_fuel"] = lab
    return out
