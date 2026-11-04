"""Loads the synthetic sample datasets shipped in data/samples."""

import json
from functools import lru_cache
from pathlib import Path

from app.seed.historical_incidents import SeedHistoricalIncident

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"


@lru_cache
def load_historical_incidents() -> tuple[SeedHistoricalIncident, ...]:
    """Resolved incidents indexed into Qdrant on first start."""
    rows = json.loads((SAMPLE_DIR / "historical_incidents.json").read_text(encoding="utf-8"))
    return tuple(SeedHistoricalIncident.model_validate(row) for row in rows)
