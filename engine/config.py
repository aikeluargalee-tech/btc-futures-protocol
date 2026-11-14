"""Configuration loader for BTC Futures Swing Trading Protocol v1.0."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "protocol_params.json"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load protocol parameters from JSON without altering core logic."""
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        return json.load(fh)
