#!/usr/bin/env python3
"""Run the merit-order model, calibration variants and benchmarks; write results/ and figures/.

Train (calibration) window: 2025-01-01 .. 2025-12-31 (Europe/Berlin).
Test (out-of-sample) window: 2026-01-01 .. 2026-10-31.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from meritorder.calibrate import fit_linear, rolling_linear, structural_grid  # noqa: E402
from meritorder.data import load_processed  # noqa: E402
from meritorder.fleet import DEFAULT_PARAMS  # noqa: E402
from meritorder.metrics import basic, grouped, regime_table, sign_hit_rate  # noqa: E402
from meritorder.model import build_stack, run_model, stack_demand, thermal_mustrun  # noqa: E402
from meritorder.paths import FIGURES, RESULTS  # noqa: E402

SPLIT = "2026-01-01"
Y = "da_price_eur_mwh"


def r2(d: dict) -> dict:
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    h, monthly, inst = load_processed()
    split = pd.Timestamp(SPLIT, tz=h.index.tz)
    tr_mask = h.index < split
    h_tr = h[tr_mask]
    mr = thermal_mustrun(h_tr, DEFAULT_PARAMS.mustrun_quantile)

    df = h[[Y]].copy()
    months = h.index.tz_localize(None).to_period("M")

    # M0: textbook stack, isolated zone (main specification)
    m0 = run_model(h, monthly, inst, DEFAULT_PARAMS, mr, "isolated")
    df["M0_stack"] = m0["model_price"]
    df["demand_mw"] = m0["demand_mw"]
    df["utilisation"] = m0["utilisation"]
    df["marginal"] = m0["marginal_fuel"]
    # M0-trade: same stack, realised net imports + pumped storage as exogenous
    df["M0_trade_exog"] = run_model(h, monthly, inst, DEFAULT_PARAMS, mr, "trade_exogenous")["model_price"]

    # C1: static linear markup fitted on 2025
    a, b = fit_linear(df.loc[tr_mask, Y].to_numpy(), df.loc[tr_mask, "M0_stack"].to_numpy())
    df["C1_linear_2025"] = a + b * df["M0_stack"]

    # C2: structural grid calibration on 2025 (availability, efficiency shift, surplus price, scarcity)
    best, log = structural_grid(h_tr, monthly, inst, DEFAULT_PARAMS, "isolated")
    log.head(25).to_csv(RESULTS / "structural_grid_top25.csv", index=False)
    df["C2_structural_2025"] = run_model(h, monthly, inst, best, mr, "isolated")["model_price"]

    # C3: rolling 90-day linear recalibration of M0, refit before each test month (out-of-sample)
    df["C3_rolling90_linear"] = rolling_linear(df, Y, "M0_stack", 90, SPLIT)

    # Benchmarks
    eua = monthly["eua_eur_t"]
    ccgt = (monthly["gas_eur_mwh_th"] + 2.0) / 0.50 + 0.2020 / 0.50 * eua + 3.0
    df["B1_flat_ccgt_srmc"] = ccgt.reindex(months).to_numpy()
    # B2: OLS on residual load and CCGT SRMC (statistical, fit on 2025)
    X = np.column_stack([np.ones(len(df)), stack_demand(h, "isolated").to_numpy() / 1000, df["B1_flat_ccgt_srmc"].to_numpy()])
    coef = np.linalg.lstsq(X[tr_mask], df.loc[tr_mask, Y].to_numpy(), rcond=None)[0]
    df["B2_ols_resload_srmc"] = X @ coef

    variants = ["M0_stack", "M0_trade_exog", "C1_linear_2025", "C2_structural_2025",
                "C3_rolling90_linear", "B1_flat_ccgt_srmc", "B2_ols_resload_srmc"]
    te = df[~tr_mask]
    tr = df[tr_mask]
    summary = {"train_window": "2025-01-01..2025-12-31", "test_window": "2026-01-01..2026-10-31",
               "n_train": int(tr_mask.sum()), "n_test": int((~tr_mask).sum()),
               "thermal_mustrun_mw": {k: round(v, 1) for k, v in mr.items()},
               "C1_coeffs": {"a": round(a, 3), "b": round(b, 4)},
               "B2_coeffs": [round(float(c), 4) for c in coef],
               "C2_params": {k: getattr(best, k) for k in ["avail_scale", "eff_shift", "surplus_price", "scarcity_u0", "scarcity_gamma"]},
               "realised": {"train_mean": round(float(tr[Y].mean()), 2), "test_mean": round(float(te[Y].mean()), 2),
                            "test_negative_share": round(float((te[Y] < 0).mean()), 4)},
               "metrics": {}}
    rows = []
    for v in variants:
        d_te = basic(te[Y], te[v])
        d_tr = basic(tr[Y], tr[v]) if tr[v].notna().all() else {}
        neg = sign_hit_rate(te[Y], te[v], 0.0)
        summary["metrics"][v] = {"test": r2(d_te), "train": r2(d_tr), "test_negative_hours": r2(neg)}
        rows.append({"variant": v, **{f"test_{k}": d_te[k] for k in ["mae", "rmse", "bias", "corr"]},
                     **{f"train_{k}": d_tr.get(k, np.nan) for k in ["mae", "rmse", "bias", "corr"]},
                     "neg_precision": neg["precision"], "neg_recall": neg["recall"]})
    tab = pd.DataFrame(rows).round(3)
    tab.to_csv(RESULTS / "metrics_summary.csv", index=False)

    # Breakdowns for main + best variant on the test window
    for v in ["M0_stack", "C3_rolling90_linear"]:
        tmp = te.rename(columns={v: "model_price"})
        grouped(tmp, tmp.index.hour).round(2).to_csv(RESULTS / f"by_hour_{v}.csv")
        grouped(tmp, tmp.index.tz_localize(None).to_period("M").astype(str)).round(2).to_csv(RESULTS / f"by_month_{v}.csv")
        regime_table(tmp).round(2).to_csv(RESULTS / f"by_regime_{v}.csv")
        summary.setdefault("regimes", {})[v] = regime_table(tmp).round(2).to_dict(orient="index")
    # by month across both windows for main model
    allm = df.rename(columns={"M0_stack": "model_price"})
    grouped(allm, months.astype(str)).round(2).to_csv(RESULTS / "by_month_M0_stack_all.csv")
    summary["marginal_tech_share_test"] = te["marginal"].value_counts(normalize=True).round(4).to_dict()
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    df.to_csv(RESULTS / "hourly_model_prices.csv.gz", float_format="%.3f", compression="gzip")

    # ---------- figures ----------
    # 1 merit order curve for two months
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for mlab in ["2025-06", "2026-10"]:
        p = pd.Period(mlab, "M")
        st = build_stack(monthly.loc[p], inst.loc[p.year], DEFAULT_PARAMS, mr)
        ax.step(np.r_[0, st["cum_mw"]] / 1000, np.r_[st["srmc"].iloc[0], st["srmc"]], where="pre",
                label=f"{mlab}: gas {monthly.loc[p, 'gas_eur_mwh_th']:.1f} €/MWh_th, EUA {monthly.loc[p, 'eua_eur_t']:.2f} €/t")
    ax.set_xlabel("cumulative available thermal capacity (GW)")
    ax.set_ylabel("SRMC (€/MWh_el)")
    ax.set_title("DE thermal merit order (M0, ASSUMED efficiencies, Energy-Charts capacities)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "01_merit_order_curves.png", dpi=120)
    plt.close(fig)

    # 2 daily mean model vs realised
    daily = df[[Y, "M0_stack", "C3_rolling90_linear"]].resample("1D").mean()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(daily.index, daily[Y], lw=1.0, color="k", label="realised DE-LU DA")
    ax.plot(daily.index, daily["M0_stack"], lw=1.0, label="M0 stack model")
    ax.plot(daily.index, daily["C3_rolling90_linear"], lw=1.0, label="C3 rolling-90d recalibrated (test only)")
    ax.axvline(split, color="grey", ls="--", lw=0.8)
    ax.text(split, ax.get_ylim()[1] * 0.95, " out-of-sample →", fontsize=8)
    ax.set_ylabel("€/MWh (daily mean)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "02_daily_model_vs_realised.png", dpi=120)
    plt.close(fig)

    # 3 scatter test hours
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.scatter(te["M0_stack"], te[Y], s=2, alpha=0.25)
    lim = [-100, 500]
    ax.plot(lim, lim, color="k", lw=0.8)
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("M0 model price (€/MWh)")
    ax.set_ylabel("realised DA (€/MWh)")
    ax.set_title("Test hours 2026-01..10")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "03_scatter_test.png", dpi=120)
    plt.close(fig)

    # 4 MAE by hour of day, test
    bh0 = pd.read_csv(RESULTS / "by_hour_M0_stack.csv", index_col=0)
    bh3 = pd.read_csv(RESULTS / "by_hour_C3_rolling90_linear.csv", index_col=0)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.plot(bh0.index, bh0["mae"], marker="o", label="M0 MAE")
    ax.plot(bh3.index, bh3["mae"], marker="o", label="C3 MAE")
    ax.plot(bh0.index, bh0["bias"], ls="--", label="M0 bias")
    ax.plot(bh3.index, bh3["bias"], ls="--", label="C3 bias")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("hour of day (Europe/Berlin)")
    ax.set_ylabel("€/MWh")
    ax.set_title("Out-of-sample error by hour (2026-01..10)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "04_error_by_hour.png", dpi=120)
    plt.close(fig)

    print(tab.to_string(index=False))
    print(json.dumps({k: summary[k] for k in ["C1_coeffs", "C2_params", "thermal_mustrun_mw", "realised", "marginal_tech_share_test"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
