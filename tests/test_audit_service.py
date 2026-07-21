from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import wattproof.tariffs as tariffs
from wattproof.adapters import PGE_3CE_ADAPTER
from wattproof.audit import UnsupportedBillError, audit_bill
from wattproof.audit_service import audit_extraction
from wattproof.fixtures import load_sample
from wattproof.models import BillExtraction, TextFact
from wattproof.tariffs import SourceIntegrityError
from wattproof.utility_fixtures import load_utility_sample


def _changed_text(
    bill: BillExtraction,
    field: str,
    value: str,
) -> BillExtraction:
    original = getattr(bill, field)
    assert isinstance(original, TextFact)
    return bill.model_copy(
        update={
            field: original.model_copy(
                update={"value": value, "source_text": value}
            )
        }
    )


def test_exact_pg_and_e_bill_keeps_tariff_verified_result() -> None:
    result = audit_extraction(load_sample("authentic"))

    assert result.schema_version == "2.0"
    assert result.verification_level == "tariff_verified"
    assert result.tariff is not None
    assert result.tariff.id == "pge_3ce_e_tou_c_2022_h2"
    assert result.discrepancy_total == Decimal("0.00")


def test_synthetic_error_remains_exactly_five_dollars() -> None:
    result = audit_extraction(load_sample("synthetic"))

    assert result.verification_level == "tariff_verified"
    assert result.discrepancy_total == Decimal("5.00")


def test_unsupported_legacy_provider_falls_back_to_internal() -> None:
    bill = _changed_text(
        load_sample("authentic"),
        "delivery_provider",
        "Example Utility",
    )

    result = audit_extraction(bill)

    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None


def test_duke_never_matches_pg_and_e_adapter() -> None:
    result = audit_extraction(load_utility_sample("duke"))

    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivery_provider", "Fake Pacific Gas and Electric Company Services"),
        ("delivery_provider", "Not PG&E"),
        ("generation_provider", "Central Coast Community Energy Holdings"),
        ("generation_provider", "Not 3CE"),
        ("delivery_schedule", "E-TOU-C-PLUS"),
        ("generation_schedule", "MBRETCH1 3Cchoice Plus"),
    ],
)
def test_substring_and_collision_identities_fail_closed(
    field: str,
    value: str,
) -> None:
    bill = _changed_text(load_sample("authentic"), field, value)

    assert PGE_3CE_ADAPTER.matches(bill) is False
    result = audit_extraction(bill)
    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None
    with pytest.raises(UnsupportedBillError):
        audit_bill(bill)


def test_exact_identities_are_compared_after_case_and_space_normalization() -> None:
    bill = load_sample("authentic")
    replacements = {
        "delivery_provider": "  PACIFIC   GAS AND ELECTRIC COMPANY ",
        "generation_provider": " central coast COMMUNITY energy ",
        "delivery_schedule": " e-tou-c ",
        "generation_schedule": "  mbretch1   3Cchoice ",
    }
    for field, value in replacements.items():
        bill = _changed_text(bill, field, value)

    assert PGE_3CE_ADAPTER.matches(bill) is True
    assert audit_extraction(bill).verification_level == "tariff_verified"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivery_schedule", "E-TOU-D"),
        ("generation_schedule", "MBRETCH2 3Cchoice"),
    ],
)
def test_schedule_mismatch_fails_closed(field: str, value: str) -> None:
    bill = _changed_text(load_sample("authentic"), field, value)

    result = audit_extraction(bill)

    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_start", date(2022, 5, 31)),
        ("service_end", date(2023, 1, 1)),
    ],
)
def test_effective_period_mismatch_fails_closed(field: str, value: date) -> None:
    bill = load_sample("authentic")
    original = getattr(bill, field)
    outside_period = bill.model_copy(
        update={field: original.model_copy(update={"value": value})}
    )

    result = audit_extraction(outside_period)

    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None


def test_archived_source_integrity_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(tariffs, "PROJECT_ROOT", tmp_path)

    with pytest.raises(SourceIntegrityError, match="Missing tariff snapshot"):
        audit_extraction(load_sample("authentic"))


def test_unified_mapping_preserves_legacy_semantics_and_provenance() -> None:
    bill = load_sample("synthetic")
    charges = []
    corrected_fact = None
    for charge in bill.charges:
        if charge.id == "pge_peak_energy":
            corrected_fact = charge.billed_amount.model_copy(
                update={"status": "user_corrected", "original_value": "36.44"}
            )
            charge = charge.model_copy(update={"billed_amount": corrected_fact})
        charges.append(charge)
    assert corrected_fact is not None
    bill = bill.model_copy(update={"charges": tuple(charges)})

    legacy = audit_bill(bill)
    result = audit_extraction(bill)
    legacy_lines = {line.id: line for line in legacy.lines}
    lines = {line.id: line for line in result.lines}
    tariff_line = lines["pge_peak_energy"]

    assert result.verdict == legacy.verdict
    assert result.headline == legacy.headline
    assert result.discrepancy_total == legacy.discrepancy_total
    assert result.tariff == legacy.tariff
    assert result.comparison == legacy.comparison
    assert tariff_line.scope == "published_tariff"
    assert tariff_line.formula == legacy_lines["pge_peak_energy"].formula
    assert tariff_line.inputs == legacy_lines["pge_peak_energy"].inputs
    assert tariff_line.expected_amount == legacy_lines["pge_peak_energy"].expected_amount
    assert tariff_line.delta == legacy_lines["pge_peak_energy"].delta
    assert tariff_line.citations == legacy_lines["pge_peak_energy"].citations
    assert tariff_line.billed_status == "user_corrected"
    assert tariff_line.billed_original_value == "36.44"
    assert len(tariff_line.evidence) == 1
    assert tariff_line.evidence[0].page == corrected_fact.source_page
    assert tariff_line.evidence[0].text == corrected_fact.source_text
    assert tariff_line.evidence[0].confidence == Decimal(
        str(corrected_fact.confidence)
    )
    assert tariff_line.evidence[0].provenance == "rendered_page"
    assert lines["delivery_subtotal"].scope == "statement_reconciliation"
    assert lines["delivery_subtotal"].root_cause_id == "pge_peak_energy"
    assert len(result.review_requests) == 1
    request = result.review_requests[0]
    assert request.provider == bill.delivery_provider.value
    assert request.subject == legacy.review_request.subject
    assert request.body == legacy.review_request.body
    assert request.grounded_audit_line_ids == ("pge_peak_energy",)
    assert request.requires_user_review is True


def test_unrelated_reconciliation_discrepancy_is_not_collapsed_into_tariff_root() -> None:
    bill = load_sample("synthetic")
    amount_due = bill.amount_due.model_copy(
        update={"value": bill.amount_due.value + Decimal("2.00")}
    )
    bill = bill.model_copy(update={"amount_due": amount_due})

    result = audit_extraction(bill)
    lines = {line.id: line for line in result.lines}

    assert lines["delivery_subtotal"].root_cause_id == "pge_peak_energy"
    assert lines["amount_due"].status == "discrepancy"
    assert lines["amount_due"].root_cause_id is None


def test_multiple_tariff_discrepancies_do_not_collapse_subtotal_symptom() -> None:
    bill = load_sample("synthetic")
    charges = tuple(
        charge.model_copy(
            update={
                "billed_amount": charge.billed_amount.model_copy(
                    update={"value": charge.billed_amount.value + Decimal("2.00")}
                )
            }
        )
        if charge.id == "pge_off_peak_energy"
        else charge
        for charge in bill.charges
    )
    bill = bill.model_copy(update={"charges": charges})

    result = audit_extraction(bill)
    lines = {line.id: line for line in result.lines}

    assert lines["pge_peak_energy"].status == "discrepancy"
    assert lines["pge_off_peak_energy"].status == "discrepancy"
    assert lines["delivery_subtotal"].status == "discrepancy"
    assert lines["delivery_subtotal"].root_cause_id is None
