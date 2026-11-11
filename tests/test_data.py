import json

import pandas as pd
import pytest

from meritorder import data as D
from meritorder.paths import PROCESSED


def test_month_chunks_cover_range():
    ch = D.month_chunks("2025-01-15", "2025-03-10")
    assert ch[0][0] == pd.Timestamp("2025-01-15")
    assert ch[-1][1] == pd.Timestamp("2025-03-10")
    assert len(ch) == 3


def test_parse_v2_handles_dst_offsets():
    payload = {"data": [
        {"timestamp": "2025-10-26T02:00:00+02:00", "values": {"day_ahead_price": 50.0}},
        {"timestamp": "2025-10-26T02:00:00+01:00", "values": {"day_ahead_price": 40.0}},
    ]}
    df = D.parse_v2(payload, {"day_ahead_price": "da_price_eur_mwh"})
    assert len(df) == 2 and df.index.is_unique
    assert str(df.index.tz) == "Europe/Berlin"


def test_licence_gate():
    with pytest.raises(RuntimeError):
        D._licence_ok({"license": "Proprietary"}, "x")
    D._licence_ok({"license": "CC BY 4.0"}, "x")


@pytest.mark.skipif(not (PROCESSED / "hourly_panel.csv").exists(), reason="processed panel not built")
def test_processed_panel_sanity():
    h, m, inst = D.load_processed()
    assert h.index.is_unique and h["da_price_eur_mwh"].notna().all()
    assert {"lignite_mw", "residual_load_mw", "net_trade_mw"} <= set(h.columns)
    months = h.index.tz_localize(None).to_period("M").unique()
    assert set(months) <= set(m.index)
    assert m.loc[months, ["gas_eur_mwh_th", "coal_eur_mwh_th", "eua_eur_t"]].notna().all().all()
    assert inst.loc[2025, "fossil_gas"] > 30
