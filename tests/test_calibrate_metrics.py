import numpy as np
import pandas as pd
import pytest

from meritorder.calibrate import fit_linear, rolling_linear
from meritorder.metrics import basic, regime_table, sign_hit_rate


def test_basic_metrics_known_values():
    m = basic(np.array([0.0, 10.0, 20.0]), np.array([1.0, 12.0, 17.0]))
    assert m["mae"] == pytest.approx(2.0)
    assert m["bias"] == pytest.approx(0.0)
    assert m["rmse"] == pytest.approx(np.sqrt((1 + 4 + 9) / 3))


def test_fit_linear_recovers():
    x = np.linspace(0, 100, 50)
    a, b = fit_linear(3.0 + 1.5 * x, x)
    assert a == pytest.approx(3.0)
    assert b == pytest.approx(1.5)


def test_rolling_linear_is_out_of_sample():
    idx = pd.date_range("2025-09-01", "2026-02-28 23:00", freq="1h", tz="Europe/Berlin")
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.uniform(50, 150, len(idx))}, index=idx)
    df["y"] = 5 + 1.2 * df["x"] + rng.normal(0, 1, len(idx))
    base = rolling_linear(df, "y", "x", 90, "2026-01-01")
    df2 = df.copy()
    df2.loc[df2.index >= pd.Timestamp("2026-02-01", tz="Europe/Berlin"), "y"] += 1000  # future shock
    pert = rolling_linear(df2, "y", "x", 90, "2026-01-01")
    jan = (df.index >= pd.Timestamp("2026-01-01", tz="Europe/Berlin")) & (df.index < pd.Timestamp("2026-02-01", tz="Europe/Berlin"))
    assert np.allclose(base[jan], pert[jan])
    assert base[df.index < pd.Timestamp("2026-01-01", tz="Europe/Berlin")].isna().all()


def test_regime_table_and_sign_hits():
    y = np.r_[-10.0, -5.0, np.linspace(10, 100, 96), 500.0, 600.0]
    df = pd.DataFrame({"da_price_eur_mwh": y, "model_price": y * 0.9})
    t = regime_table(df)
    assert set(t.index) == {"negative_price", "normal", "scarcity_top5pct"}
    assert t.loc["negative_price", "n"] == 2
    s = sign_hit_rate(y, y * 0.9)
    assert s["precision"] == 1.0 and s["recall"] == 1.0
