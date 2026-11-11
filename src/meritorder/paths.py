from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
REFERENCE = DATA / "reference"
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"

USER_AGENT = "epm-merit-order-model/0.1 (+https://github.com/DataWithSyed/epm-merit-order-model; research)"
