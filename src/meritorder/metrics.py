"""Error metrics for model vs realised day-ahead prices."""
from __future__ import annotations

import numpy as np
import pandas as pd


def basic(y: np.ndarray, f: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, float)
    f = np.asarray(f, float)
    e = f - y
    return {
        "n": int(len(y)),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e ** 2))),
        "bias": float(np.mean(e)),
        "corr": float(np.corrcoef(y, f)[0, 1]) if len(y) > 2 and np.std(f) > 0 else float("nan"),
    }


def grouped(df: pd.DataFrame, by: pd.Series | np.ndarray, y: str = "da_price_eur_mwh", f: str = "model_price") -> pd.DataFrame:
    rows = {}
    for k, g in df.groupby(by):
        rows[k] = basic(g[y].to_numpy(), g[f].to_numpy())
    return pd.DataFrame(rows).T


def regime_table(df: pd.DataFrame, y: str = "da_price_eur_mwh", f: str = "model_price",
                 scarcity_q: float = 0.95) -> pd.DataFrame:
    """Errors in negative-price hours, scarcity hours (top 5 % realised price) and the rest."""
    thr = df[y].quantile(scarcity_q)
    reg = np.where(df[y] < 0, "negative_price", np.where(df[y] >= thr, f"scarcity_top{int((1-scarcity_q)*100)}pct", "normal"))
    t = grouped(df, reg, y, f)
    t["mean_realised"] = df.groupby(reg)[y].mean()
    t["mean_model"] = df.groupby(reg)[f].mean()
    return t


def sign_hit_rate(y: np.ndarray, f: np.ndarray, thr: float = 0.0) -> dict[str, float]:
    """Precision / recall of model for realised price <= thr hours."""
    y = np.asarray(y) <= thr
    f = np.asarray(f) <= thr
    tp = float(np.sum(y & f))
    return {"precision": tp / max(f.sum(), 1), "recall": tp / max(y.sum(), 1),
            "realised_count": int(y.sum()), "model_count": int(f.sum())}
