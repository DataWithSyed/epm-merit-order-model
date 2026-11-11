#!/usr/bin/env python3
"""Fetch public data and write data/processed/{hourly_panel,monthly_drivers,installed_gw}.csv."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from meritorder.data import build_hourly, build_monthly, fetch_installed  # noqa: E402
from meritorder.paths import PROCESSED  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-10-31")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    h = build_hourly(a.start, a.end, a.refresh)
    out = h.copy()
    out.index = out.index.tz_convert("UTC")
    out.index.name = "timestamp"
    out.round(3).to_csv(PROCESSED / "hourly_panel.csv")
    months = pd.period_range(a.start, a.end, freq="M")
    build_monthly(months, a.refresh).to_csv(PROCESSED / "monthly_drivers.csv")
    fetch_installed(a.refresh).to_csv(PROCESSED / "installed_gw.csv")
    print(f"hourly rows {len(h)}; price NaN {h['da_price_eur_mwh'].isna().sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
