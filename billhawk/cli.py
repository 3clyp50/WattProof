from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from .audit import UnsupportedBillError, audit_bill
from .extract import (
    ExtractionUnavailableError,
    InvalidDocumentError,
    UnsupportedDocumentError,
    extract_pdf,
)
from .fixtures import load_sample


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="billhawk",
        description="Audit the supported PG&E/3CE statement with deterministic math.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--sample",
        choices=("authentic", "synthetic"),
        default="authentic",
        help="run a bundled sample (default: authentic)",
    )
    source.add_argument("--file", type=Path, help="extract a native PDF")
    parser.add_argument("--json", action="store_true", help="print the full JSON result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        bill = extract_pdf(args.file) if args.file else load_sample(args.sample)
        result = audit_bill(bill)
    except (
        ExtractionUnavailableError,
        InvalidDocumentError,
        UnsupportedBillError,
        UnsupportedDocumentError,
        ValidationError,
        ValueError,
    ) as error:
        print(f"BillHawk could not audit this document: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    verified = sum(line.status == "verified" for line in result.lines)
    unavailable = sum(line.status == "cannot_verify" for line in result.lines)
    print(result.headline)
    print(f"Verified checks: {verified}; cannot verify: {unavailable}")
    if bill.synthetic_notice:
        print(bill.synthetic_notice)
    for line in result.lines:
        if line.status == "discrepancy":
            print(
                f"- {line.label}: billed ${line.billed_amount:.2f}, "
                f"expected ${line.expected_amount:.2f}, delta ${line.delta:.2f}"
            )
    print(f"Plan comparison: {result.comparison.headline}")
    return 0
