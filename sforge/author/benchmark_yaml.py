from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml


def ensure_base(bench_path: Path, key: str) -> Literal["exists", "missing"]:
    return "exists" if load_base_spec(bench_path, key) is not None else "missing"


def load_base_spec(bench_path: Path, key: str) -> dict | None:
    with bench_path.open() as fh:
        data = yaml.safe_load(fh) or {}
    base_images = data.get("base_images") or {}
    entry = base_images.get(key)
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry
    return {"value": entry}
