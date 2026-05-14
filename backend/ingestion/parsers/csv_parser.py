"""Parse CSV EHR exports into raw dicts that ``cleaner.clean_record`` can consume.

Handles plain ``.csv`` and gzipped ``.csv.gz`` files. Header names are kept
as-is (the cleaner's field-alias table accepts both Synthea's UPPERCASE
columns and MIMIC's lower_snake_case columns).
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path
from typing import Any


def _open(path: Path):
    """Open ``path`` as text, transparently decompressing ``.gz``."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def parse_csv_file(path: str | Path) -> list[dict[str, Any]]:
    """Read one CSV (or .csv.gz) into a list of row dicts."""
    p = Path(path)
    with _open(p) as f:
        return list(csv.DictReader(f))
