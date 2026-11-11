"""Data access for the merit-order model.

Fetch / cache / parse logic is adapted from step 1 of the lab,
https://github.com/DataWithSyed/epm-data-pipeline (commit 46e84fa), with the
Energy-Charts series map widened to the extra columns a stack model needs
(cross-border trade, oil, waste, others, pumped storage, coal-derived gas).

Sources (always attribute):
- Energy-Charts v2 API (Fraunhofer ISE), DE-LU day-ahead prices from
  Bundesnetzagentur | SMARD.de, CC BY 4.0
- World Bank Commodity Price Data (Pink Sheet), CC BY 4.0
- ECB Data Portal EXR/M.USD.EUR.SP00.A
- DEHSt German primary-auction EUA volume-weighted averages (carbon proxy)
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from meritorder.paths import PROCESSED, RAW, REFERENCE, USER_AGENT

EC_BASE = "https://api.energy-charts.info"
TZ = "Europe/Berlin"
WB_PINK_SHEET = (
    "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
    "related/CMO-Historical-Data-Monthly.xlsx"
)
ECB_FX_MONTHLY = (
    "https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A"
    "?format=csvdata&startPeriod=2018-01"
)

# Same conventions as step 1 (ASSUMED engineering conversions, register A-D6/A-D7)
MMBTU_PER_MWH = 3.412141156
COAL_MWH_TH_PER_T = 6000 * 4.1868 / 3600  # NAR 6000 kcal/kg -> 6.978 MWh_th/t
# ASSUMED: 1 bbl crude ~ 5.8 MMBtu (conventional crude heat content) -> MWh_th/bbl
BBL_MWH_TH = 5.8 / MMBTU_PER_MWH

POWER_SERIES = {
    "load": "load_mw",
    "residual_load": "residual_load_mw",
    "wind_onshore": "wind_onshore_mw",
    "wind_offshore": "wind_offshore_mw",
    "solar": "solar_mw",
    "fossil_gas": "gas_mw",
    "fossil_hard_coal": "hard_coal_mw",
    "fossil_brown_coal_lignite": "lignite_mw",
    "fossil_oil": "oil_mw",
    "fossil_coal_derived_gas": "coal_gas_mw",
    "nuclear": "nuclear_mw",
    "biomass": "biomass_mw",
    "waste": "waste_mw",
    "geothermal": "geothermal_mw",
    "others": "others_mw",
    "hydro_run_of_river": "hydro_ror_mw",
    "hydro_water_reservoir": "hydro_res_mw",
    "hydro_pumped_storage": "ps_gen_mw",
    "hydro_pumped_storage_consumption": "ps_cons_mw",
    "cross_border_electricity_trading": "net_trade_mw",
}


def http_get(url: str, dest: Path, *, refresh: bool = False, binary: bool = False,
             timeout: int = 120, max_attempts: int = 5) -> Path:
    """Download with on-disk cache (raw blobs stay git-ignored in data/raw)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not refresh:
        return dest
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 15)))
                continue
            if r.status_code >= 500 and attempt < max_attempts - 1:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            if binary:
                dest.write_bytes(r.content)
            else:
                dest.write_text(r.text, encoding="utf-8")
            return dest
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Download failed: {url}") from last


def month_chunks(start: str, end: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out = []
    a = s
    while a <= e:
        b = min((a + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1), e)
        out.append((a, b))
        a = b + pd.Timedelta(days=1)
    return out


def parse_v2(payload: dict, value_map: dict[str, str]) -> pd.DataFrame:
    rows = []
    for rec in payload.get("data") or []:
        vals = rec.get("values") or {}
        row = {"timestamp": rec.get("timestamp")}
        for src, dst in value_map.items():
            if src in vals:
                row[dst] = vals[src]
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(TZ)
    return df.set_index("timestamp").sort_index()


def _licence_ok(payload: dict, what: str) -> None:
    lic = payload.get("license") or ""
    if lic and "CC BY" not in lic.upper():
        raise RuntimeError(f"{what}: licence {lic!r} is not CC BY; refusing to process")


def fetch_prices(start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    parts = []
    for a, b in month_chunks(start, end):
        url = f"{EC_BASE}/v2/price?bzn=DE-LU&start={a:%Y-%m-%d}&end={b:%Y-%m-%d}"
        p = http_get(url, RAW / f"ec_v2_price_DE-LU_{a:%Y%m%d}_{b:%Y%m%d}.json", refresh=refresh)
        payload = json.loads(p.read_text(encoding="utf-8"))
        _licence_ok(payload, "DE-LU price")
        parts.append(parse_v2(payload, {"day_ahead_price": "da_price_eur_mwh"}))
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated(keep="last")]


def fetch_power(start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    parts = []
    for a, b in month_chunks(start, end):
        url = f"{EC_BASE}/v2/public_power?country=de&start={a:%Y-%m-%d}&end={b:%Y-%m-%d}"
        p = http_get(url, RAW / f"ec_v2_power_de_{a:%Y%m%d}_{b:%Y%m%d}.json", refresh=refresh)
        payload = json.loads(p.read_text(encoding="utf-8"))
        _licence_ok(payload, "DE public power")
        parts.append(parse_v2(payload, POWER_SERIES))
        time.sleep(0.5)
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated(keep="last")]


def fetch_installed(refresh: bool = False) -> pd.DataFrame:
    """Installed capacity (GW) by type at each year (Energy-Charts yearly)."""
    url = f"{EC_BASE}/v2/installed_power?country=de&time_step=yearly"
    p = http_get(url, RAW / "ec_v2_installed_de_yearly.json", refresh=refresh)
    payload = json.loads(p.read_text(encoding="utf-8"))
    rows = [{"year": pd.Timestamp(r["timestamp"]).year, **(r.get("values") or {})}
            for r in payload.get("data") or []]
    return pd.DataFrame(rows).set_index("year").sort_index()


def fetch_fuels(refresh: bool = False) -> pd.DataFrame:
    """World Bank Pink Sheet monthly gas Europe (USD/MMBtu), SA coal (USD/t), Brent (USD/bbl)."""
    path = http_get(WB_PINK_SHEET, RAW / "CMO-Historical-Data-Monthly.xlsx", refresh=refresh, binary=True)
    raw = pd.read_excel(path, sheet_name="Monthly Prices", header=None)
    hdr = raw.index[raw.iloc[:, 1].map(lambda x: "Crude oil, average" in str(x))][0]
    names = [str(x).strip() if pd.notna(x) else "" for x in raw.iloc[hdr]]
    data = raw.iloc[hdr + 2:].copy()
    data.columns = ["month"] + names[1:]
    data = data[data["month"].astype(str).str.match(r"^\d{4}M\d{2}$")]

    def col(prefix: str) -> str:
        hits = [c for c in names if c.startswith(prefix)]
        if not hits:
            raise KeyError(prefix)
        return hits[0]

    out = pd.DataFrame(
        {
            "gas_usd_mmbtu": pd.to_numeric(data[col("Natural gas, Europe")], errors="coerce").values,
            "coal_usd_t": pd.to_numeric(data[col("Coal, South Africa")], errors="coerce").values,
            "brent_usd_bbl": pd.to_numeric(data[col("Crude oil, Brent")], errors="coerce").values,
        },
        index=pd.PeriodIndex([str(m).replace("M", "-") for m in data["month"]], freq="M"),
    )
    return out.dropna(how="all")


def fetch_fx(refresh: bool = False) -> pd.Series:
    p = http_get(ECB_FX_MONTHLY, RAW / "ecb_usd_per_eur_monthly.csv", refresh=refresh)
    d = pd.read_csv(io.StringIO(p.read_text(encoding="utf-8")))
    return pd.Series(d["OBS_VALUE"].astype(float).values,
                     index=pd.PeriodIndex(d["TIME_PERIOD"], freq="M"), name="usd_per_eur")


def eua_by_year() -> pd.Series:
    ref = pd.read_csv(REFERENCE / "eua_dehst_annual.csv")
    return ref.set_index("year")["eua_eur_t"].astype(float)


def build_hourly(start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    """Hourly (mean of 15-min) panel indexed by Europe/Berlin time."""
    pr = fetch_prices(start, end, refresh)
    pw = fetch_power(start, end, refresh)
    h = pr.resample("1h").mean().join(pw.resample("1h").mean(), how="inner")
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).tz_localize(TZ)
    h = h[(h.index >= pd.Timestamp(start).tz_localize(TZ)) & (h.index < end_excl)]
    for c in POWER_SERIES.values():
        if c not in h.columns:
            h[c] = np.nan
    return h


def build_monthly(months: pd.PeriodIndex, refresh: bool = False) -> pd.DataFrame:
    fuels = fetch_fuels(refresh).reindex(months)
    fx = fetch_fx(refresh).reindex(months)
    eua = eua_by_year()
    out = pd.DataFrame(index=months)
    out["gas_usd_mmbtu"] = fuels["gas_usd_mmbtu"]
    out["coal_usd_t"] = fuels["coal_usd_t"]
    out["brent_usd_bbl"] = fuels["brent_usd_bbl"]
    out["usd_per_eur"] = fx
    out["gas_eur_mwh_th"] = out["gas_usd_mmbtu"] / out["usd_per_eur"] * MMBTU_PER_MWH
    out["coal_eur_mwh_th"] = out["coal_usd_t"] / out["usd_per_eur"] / COAL_MWH_TH_PER_T
    out["oil_eur_mwh_th"] = out["brent_usd_bbl"] / out["usd_per_eur"] / BBL_MWH_TH
    out["eua_eur_t"] = [eua.get(m.year, np.nan) for m in months]
    out.index.name = "month"
    return out


def load_processed() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the shipped processed panels (hourly, monthly, installed)."""
    h = pd.read_csv(PROCESSED / "hourly_panel.csv")
    h["timestamp"] = pd.to_datetime(h["timestamp"], utc=True).dt.tz_convert(TZ)
    h = h.set_index("timestamp")
    m = pd.read_csv(PROCESSED / "monthly_drivers.csv")
    m["month"] = pd.PeriodIndex(m["month"], freq="M")
    m = m.set_index("month")
    inst = pd.read_csv(PROCESSED / "installed_gw.csv").set_index("year")
    return h, m, inst
