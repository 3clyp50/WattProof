from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from .audit import UnsupportedBillError
from .audit_service import Extraction, audit_extraction
from .extract import (
    ExtractionUnavailableError,
    InvalidDocumentError,
    UnsupportedDocumentError,
    extract_pdf,
)
from .fixtures import load_sample
from .models import BillExtraction
from .tariffs import SourceIntegrityError
from .utility_fixtures import load_utility_sample
from .utility_models import VerificationLevel

SAMPLE_CHOICES = (
    "authentic",
    "synthetic",
    "duke",
    "centerpoint",
    "bloomington",
)
VERIFICATION_LABELS: dict[VerificationLevel, str] = {
    "evidence_extracted": "Evidence extracted",
    "internally_reconciled": "Internally reconciled",
    "tariff_verified": "Tariff verified",
}


def _load_bundled_sample(kind: str) -> Extraction:
    if kind == "authentic":
        return load_sample("authentic")
    if kind == "synthetic":
        return load_sample("synthetic")
    if kind == "duke":
        return load_utility_sample("duke")
    if kind == "centerpoint":
        return load_utility_sample("centerpoint")
    if kind == "bloomington":
        return load_utility_sample("bloomington")
    raise ValueError(f"Unsupported bundled sample: {kind}")


def _money(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"${value:.2f}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wattproof",
        description="Audit a utility statement with deterministic math.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--sample",
        choices=SAMPLE_CHOICES,
        default="authentic",
        help="run a bundled sample (default: authentic)",
    )
    source.add_argument("--file", type=Path, help="extract a native PDF")
    parser.add_argument("--json", action="store_true", help="print the full JSON result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        bill = extract_pdf(args.file) if args.file else _load_bundled_sample(args.sample)
        result = audit_extraction(bill)
    except (
        ExtractionUnavailableError,
        InvalidDocumentError,
        SourceIntegrityError,
        UnsupportedBillError,
        UnsupportedDocumentError,
        ValidationError,
        ValueError,
    ) as error:
        print(f"WattProof could not audit this document: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    verified = sum(line.status == "verified" for line in result.lines)
    unavailable = sum(line.status == "cannot_verify" for line in result.lines)
    print(result.headline)
    print(f"Verification level: {VERIFICATION_LABELS[result.verification_level]}")
    print(f"Verified checks: {verified}; cannot verify: {unavailable}")
    if isinstance(bill, BillExtraction) and bill.synthetic_notice:
        print(bill.synthetic_notice)
    for line in result.lines:
        if line.status == "discrepancy":
            print(
                f"- {line.label}: billed {_money(line.billed_amount)}, "
                f"expected {_money(line.expected_amount)}, delta {_money(line.delta)}"
            )
    if result.comparison is not None:
        print(f"Plan comparison: {result.comparison.headline}")
    return 0
