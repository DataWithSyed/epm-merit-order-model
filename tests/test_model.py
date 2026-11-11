import numpy as np
import pandas as pd
import pytest

from meritorder.fleet import DEFAULT_PARAMS, EF_T_PER_MWH_TH
from meritorder.model import build_stack, clear, run_model, stack_demand, thermal_mustrun

INST = pd.Series({"fossil_brown_coal_lignite": 14.776, "fossil_hard_coal": 15.063,
                  "fossil_gas": 35.314, "fossil_oil": 3.535})
MONTH = pd.Series({"gas_eur_mwh_th": 35.0, "coal_eur_mwh_th": 12.0, "oil_eur_mwh_th": 40.0, "eua_eur_t": 75.0})


def test_ipcc_emission_factors():
    assert EF_T_PER_MWH_TH["gas"] == pytest.approx(0.20196, abs=1e-5)
    assert EF_T_PER_MWH_TH["hard_coal"] == pytest.approx(0.34056, abs=1e-5)
    assert EF_T_PER_MWH_TH["lignite"] == pytest.approx(0.3636, abs=1e-4)


def test_stack_sorted_and_capacity_matches_availability():
    st = build_stack(MONTH, INST, DEFAULT_PARAMS, {"lignite": 2000.0})
    assert st["srmc"].is_monotonic_increasing
    expect = sum(INST[t.capacity_key] * 1000 * t.capacity_share * t.availability for t in DEFAULT_PARAMS.techs)
    assert st["cum_mw"].iloc[-1] == pytest.approx(expect)
    mr = st[st["tech"].str.endswith("_mustrun")]
    assert mr["cap_mw"].sum() == pytest.approx(2000.0)
    assert (mr["srmc"] == DEFAULT_PARAMS.surplus_price).all()


def test_srmc_hand_calculation_best_ccgt_band():
    st = build_stack(MONTH, INST, DEFAULT_PARAMS)
    band = st[(st["tech"] == "gas_ccgt") & np.isclose(st["eff"], 0.60)].iloc[0]
    expect = (35.0 + 2.0) / 0.60 + 0.2020 / 0.60 * 75.0 + 3.0
    assert band["srmc"] == pytest.approx(expect, rel=1e-3)


def test_clear_edges_and_monotonicity():
    st = build_stack(MONTH, INST, DEFAULT_PARAMS)
    d = np.linspace(-5000, 80000, 400)
    p, u = clear(d, st, DEFAULT_PARAMS)
    assert np.all(p[d <= 0] == DEFAULT_PARAMS.surplus_price)
    assert np.all(np.diff(p) >= -1e-9)
    assert p[-1] == pytest.approx(st["srmc"].iloc[-1])
    assert u[-1] > 1


def test_scarcity_adder_only_above_u0():
    st = build_stack(MONTH, INST, DEFAULT_PARAMS)
    prm = DEFAULT_PARAMS.with_(scarcity_u0=0.9, scarcity_gamma=10.0)
    total = st["cum_mw"].iloc[-1]
    p0, _ = clear(np.array([0.5 * total, 1.0 * total]), st, DEFAULT_PARAMS)
    p1, _ = clear(np.array([0.5 * total, 1.0 * total]), st, prm)
    assert p1[0] == pytest.approx(p0[0])
    assert p1[1] - p0[1] == pytest.approx(10.0 * 100 * 0.1 ** 2)


def test_fuel_and_carbon_sensitivities():
    st_lo = build_stack(MONTH, INST, DEFAULT_PARAMS)
    m_hi = MONTH.copy()
    m_hi["gas_eur_mwh_th"] = 70.0
    st_hi = build_stack(m_hi, INST, DEFAULT_PARAMS)
    d = np.array([45000.0])
    assert clear(d, st_hi, DEFAULT_PARAMS)[0][0] > clear(d, st_lo, DEFAULT_PARAMS)[0][0]
    # carbon raises lignite SRMC more than CCGT SRMC per EUR/t
    m_c = MONTH.copy()
    m_c["eua_eur_t"] = 85.0
    st_c = build_stack(m_c, INST, DEFAULT_PARAMS)
    def best(st, tech):
        return st[st["tech"] == tech]["srmc"].min()
    assert best(st_c, "lignite") - best(st_lo, "lignite") > best(st_c, "gas_ccgt") - best(st_lo, "gas_ccgt")


def _toy_hourly(n=48):
    idx = pd.date_range("2025-03-01", periods=n, freq="1h", tz="Europe/Berlin")
    rng = np.random.default_rng(0)
    h = pd.DataFrame(index=idx)
    h["residual_load_mw"] = 30000 + 10000 * np.sin(np.arange(n) / 24 * 2 * np.pi)
    for c in ["biomass_mw", "waste_mw", "geothermal_mw", "others_mw", "hydro_ror_mw", "hydro_res_mw", "coal_gas_mw"]:
        h[c] = 500.0
    h["net_trade_mw"] = rng.normal(0, 2000, n)
    h["ps_gen_mw"] = 300.0
    h["ps_cons_mw"] = -200.0
    for c in ["lignite_mw", "hard_coal_mw", "gas_mw", "oil_mw"]:
        h[c] = rng.uniform(1000, 5000, n)
    h["da_price_eur_mwh"] = 90.0
    return h


def test_stack_demand_modes():
    h = _toy_hourly()
    iso = stack_demand(h, "isolated")
    assert np.allclose(iso, h["residual_load_mw"] - 3500)
    tr = stack_demand(h, "trade_exogenous")
    assert np.allclose(tr, iso - h["net_trade_mw"] - 100)
    with pytest.raises(ValueError):
        stack_demand(h, "nope")


def test_thermal_mustrun_quantile():
    h = _toy_hourly()
    mr = thermal_mustrun(h, 0.02)
    assert mr["gas"] == pytest.approx(h["gas_mw"].quantile(0.02))


def test_run_model_end_to_end_toy():
    h = _toy_hourly()
    monthly = pd.DataFrame([MONTH], index=pd.PeriodIndex(["2025-03"], freq="M"))
    inst = pd.DataFrame([INST], index=[2025])
    out = run_model(h, monthly, inst, DEFAULT_PARAMS, thermal_mustrun(h, 0.02), "isolated")
    assert out["model_price"].notna().all()
    # higher demand -> weakly higher price
    order = np.argsort(out["demand_mw"].to_numpy())
    assert np.all(np.diff(out["model_price"].to_numpy()[order]) >= -1e-9)
