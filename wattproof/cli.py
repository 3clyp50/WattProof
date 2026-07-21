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
from .numeric import format_decimal_exact, format_fixed_exact, format_usd_exact
from .tariffs import SourceIntegrityError
from .utility_fixtures import load_utility_sample
from .utility_models import VerificationLevel, root_cause_ids_for

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


def _display_value(value: Decimal | None, unit: str, currency: str) -> str:
    if value is None:
        return "unavailable"
    if unit == currency:
        if currency == "USD":
            return format_usd_exact(value)
        return f"{format_fixed_exact(value, Decimal('0.01'))} {currency}"
    return f"{format_decimal_exact(value)} {unit}"


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
    except SourceIntegrityError as error:
        print(
            f"WattProof could not audit this document: {error.public_message}",
            file=sys.stderr,
        )
        return 2
    except (
        ExtractionUnavailableError,
        InvalidDocumentError,
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

    published_matches = sum(
        line.status == "verified" and line.scope == "published_tariff"
        for line in result.lines
    )
    printed_math_agreements = sum(
        line.status == "verified" and line.scope == "printed_math"
        for line in result.lines
    )
    reconciliation_agreements = sum(
        line.status == "verified" and line.scope == "statement_reconciliation"
        for line in result.lines
    )
    unavailable = sum(line.status == "cannot_verify" for line in result.lines)
    print(result.headline)
    print(f"Verification level: {VERIFICATION_LABELS[result.verification_level]}")
    print(
        f"Published tariff matches: {published_matches}; "
        f"Printed-math agreements: {printed_math_agreements}; "
        f"Statement reconciliations: {reconciliation_agreements}; "
        f"cannot verify: {unavailable}"
    )
    if isinstance(bill, BillExtraction) and bill.synthetic_notice:
        print(bill.synthetic_notice)
    for line in result.lines:
        if line.status == "discrepancy":
            root_ids = root_cause_ids_for(line)
            dependency = (
                f" (derived from roots: {', '.join(root_ids)})"
                if root_ids
                else ""
            )
            print(
                f"- {line.label}: billed "
                f"{_display_value(line.billed_amount, line.unit, result.currency)}, "
                f"expected "
                f"{_display_value(line.expected_amount, line.unit, result.currency)}, "
                f"delta {_display_value(line.delta, line.unit, result.currency)}"
                f"{dependency}"
            )
    if result.comparison is not None:
        print(f"Plan comparison: {result.comparison.headline}")
    return 0
