from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import Citation, TariffVersion


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RATE_DATA_PATH = Path(__file__).with_name("data") / "rates.json"


class SourceIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class RateRule:
    kind: str
    rate: Decimal
    citations: tuple[str, ...] = ()
    line_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TariffBundle:
    version: TariffVersion
    citation_map: dict[str, Citation]
    rules: dict[str, RateRule]
    limitations: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_tariff_bundle(*, verify_sources: bool = True) -> TariffBundle:
    raw: dict[str, Any] = json.loads(RATE_DATA_PATH.read_text(encoding="utf-8"))
    citation_map = {
        key: Citation.model_validate(value)
        for key, value in raw["citations"].items()
    }

    if verify_sources:
        for citation in citation_map.values():
            source_path = PROJECT_ROOT / citation.local_path
            if not source_path.is_file():
                raise SourceIntegrityError(f"Missing tariff snapshot: {source_path}")
            actual_hash = _sha256(source_path)
            if actual_hash != citation.sha256:
                raise SourceIntegrityError(
                    f"Tariff snapshot hash mismatch: {citation.local_path}"
                )

    version = TariffVersion.model_validate(
        {
            "id": raw["id"],
            "provider": raw["provider"],
            "schedule": raw["schedule"],
            "jurisdiction": raw["jurisdiction"],
            "effective_start": raw["effective_start"],
            "effective_end": raw["effective_end"],
            "retrieved_on": raw["retrieved_on"],
            "citations": tuple(citation_map.values()),
        }
    )
    rules = {
        line_id: RateRule(
            kind=rule["kind"],
            rate=Decimal(rule["rate"]),
            citations=tuple(
                rule.get("citations", (rule["citation"],) if "citation" in rule else ())
            ),
            line_ids=tuple(rule.get("line_ids", ())),
        )
        for line_id, rule in raw["rules"].items()
    }
    return TariffBundle(
        version=version,
        citation_map=citation_map,
        rules=rules,
        limitations=raw["limitations"],
    )
