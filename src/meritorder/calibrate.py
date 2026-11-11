"""Calibration variants, all fitted on the training window only."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from meritorder.fleet import FleetParams
from meritorder.model import run_model, thermal_mustrun


def fit_linear(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """OLS y = a + b x."""
    X = np.column_stack([np.ones_like(x), x])
    a, b = np.linalg.lstsq(X, y, rcond=None)[0]
    return float(a), float(b)


def structural_grid(h_train: pd.DataFrame, monthly: pd.DataFrame, installed: pd.DataFrame,
                    base: FleetParams, mode: str = "isolated", grid: dict | None = None) -> tuple[FleetParams, pd.DataFrame]:
    """Exhaustive grid search on train MAE over the physical knobs.

    Knobs: avail_scale, eff_shift, surplus_price, scarcity_u0, scarcity_gamma.
    Returns the best params and the evaluation log.
    """
    grid = grid or {
        "avail_scale": [0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
        "eff_shift": [-0.06, -0.04, -0.02, 0.0, 0.02],
        "surplus_price": [-40.0, -20.0, -10.0, -5.0, 0.0],
        "scarcity_u0": [0.7, 0.8, 0.9],
        "scarcity_gamma": [0.0, 5.0, 10.0, 20.0, 40.0],
    }
    mr = thermal_mustrun(h_train, base.mustrun_quantile)
    y = h_train["da_price_eur_mwh"].to_numpy()
    cache: dict[tuple, float] = {}

    def score(p: FleetParams) -> float:
        key = tuple(getattr(p, k) for k in grid)
        if key not in cache:
            f = run_model(h_train, monthly, installed, p, mr, mode)["model_price"].to_numpy()
            cache[key] = float(np.mean(np.abs(f - y)))
        return cache[key]

    best = base
    best_s = score(best)
    keys = list(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        cand = base.with_(**dict(zip(keys, combo)))
        s = score(cand)
        if s < best_s - 1e-9:
            best, best_s = cand, s
    log = pd.DataFrame([dict(zip(grid, k), train_mae=v) for k, v in cache.items()]).sort_values("train_mae")
    return best, log


def rolling_linear(df: pd.DataFrame, y: str, x: str, window_days: int = 90,
                   start: str | pd.Timestamp = "2026-01-01") -> pd.Series:
    """Out-of-sample monthly recalibration: for each month >= start, fit y=a+bx on the
    trailing ``window_days`` before the month start and apply to that month."""
    out = pd.Series(np.nan, index=df.index)
    months = df.index.tz_localize(None).to_period("M")
    for m in pd.unique(months[df.index >= pd.Timestamp(start, tz=df.index.tz)]):
        m0 = pd.Timestamp(m.start_time).tz_localize(df.index.tz)
        trn = df[(df.index < m0) & (df.index >= m0 - pd.Timedelta(days=window_days))]
        a, b = fit_linear(trn[y].to_numpy(), trn[x].to_numpy())
        mask = months == m
        out[mask] = a + b * df.loc[mask, x]
    return out
