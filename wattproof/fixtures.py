from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from .models import BillExtraction

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = PROJECT_ROOT / "fixtures"


def load_sample(kind: Literal["authentic", "synthetic"]) -> BillExtraction:
    authentic_path = FIXTURES_DIR / "authentic-extraction.json"
    raw: dict[str, Any] = json.loads(
        authentic_path.read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    if kind == "authentic":
        return BillExtraction.model_validate(raw)

    alteration_path = FIXTURES_DIR / "synthetic-altered-extraction.json"
    alteration = json.loads(
        alteration_path.read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    charge_id = alteration["alterations"]["charge_id"]
    for line in raw["charges"]:
        if line["id"] == charge_id:
            billed = alteration["alterations"]["billed_amount"]
            line["billed_amount"]["value"] = billed
            line["billed_amount"]["source_text"] = (
                f"SYNTHETIC DEMO: PG&E peak charge altered to ${billed}"
            )
            break
    else:
        raise ValueError(f"Synthetic alteration target not found: {charge_id}")

    raw["fixture_kind"] = "synthetic"
    raw["synthetic_notice"] = alteration["notice"]
    raw["document_sha256"] = hashlib.sha256(alteration_path.read_bytes()).hexdigest()
    return BillExtraction.model_validate(raw)
