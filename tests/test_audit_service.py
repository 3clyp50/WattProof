from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import wattproof.adapters as adapters
import wattproof.tariffs as tariffs
from wattproof.adapters import PGE_3CE_ADAPTER
from wattproof.audit import UnsupportedBillError, audit_bill
from wattproof.audit_service import audit_extraction
from wattproof.fixtures import load_sample
from wattproof.models import BillExtraction, TextFact
from wattproof.tariffs import SourceIntegrityError, TariffBundle, load_tariff_bundle
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


def _changed_charge_amount(
    bill: BillExtraction,
    charge_id: str,
    delta: Decimal,
) -> BillExtraction:
    charges = tuple(
        charge.model_copy(
            update={
                "billed_amount": charge.billed_amount.model_copy(
                    update={"value": charge.billed_amount.value + delta}
                )
            }
        )
        if charge.id == charge_id
        else charge
        for charge in bill.charges
    )
    return bill.model_copy(update={"charges": charges})


def _assert_internal_fallback(bill: BillExtraction) -> None:
    assert PGE_3CE_ADAPTER.matches(bill) is False
    result = audit_extraction(bill)
    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None
    assert all(line.scope != "published_tariff" for line in result.lines)


def test_exact_pg_and_e_bill_keeps_tariff_verified_result() -> None:
    bill = load_sample("authentic")
    legacy = audit_bill(bill)
    result = audit_extraction(bill)

    assert result.schema_version == "2.0"
    assert result.verification_level == "tariff_verified"
    assert result.tariff is not None
    assert result.tariff.id == "pge_3ce_e_tou_c_2022_h2"
    assert result.discrepancy_total == Decimal("0.00")
    line_ids = {line.id for line in result.lines}
    assert all(
        set(request.grounded_audit_line_ids) <= line_ids
        for request in result.review_requests
    )
    assert tuple(request.provider for request in result.review_requests) == (
        bill.delivery_provider.value,
        bill.generation_provider.value,
    )
    sections = {line.id: line.section_id for line in result.lines}
    expected_sections = ("pge_delivery", "cca_generation")
    for request, expected_section in zip(
        result.review_requests,
        expected_sections,
        strict=True,
    ):
        assert request.provider in request.subject
        assert request.provider in request.body
        assert request.requires_user_review is True
        assert request.grounded_audit_line_ids
        assert all(
            sections[line_id] == expected_section
            for line_id in request.grounded_audit_line_ids
        )
        own_labels = {
            line.label
            for line in result.lines
            if line.id in request.grounded_audit_line_ids
        }
        other_labels = {
            line.label
            for line in result.lines
            if line.section_id in set(expected_sections) - {expected_section}
        }
        assert all(label in request.body for label in own_labels)
        assert all(label not in request.body for label in other_labels)
    assert result.review_requests[0].subject != result.review_requests[1].subject
    assert result.review_requests[0].body != result.review_requests[1].body
    assert {
        line_id
        for request in result.review_requests
        for line_id in request.grounded_audit_line_ids
    } == set(legacy.review_request.grounded_audit_line_ids)


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


def test_unknown_charge_identifiers_cannot_claim_tariff_verification() -> None:
    bill = load_sample("authentic")
    renamed = tuple(
        charge.model_copy(update={"id": f"unknown_charge_{index}"})
        for index, charge in enumerate(bill.charges)
    )
    bill = bill.model_copy(update={"charges": renamed})

    _assert_internal_fallback(bill)
    result = audit_extraction(bill)
    line_ids = {line.id for line in result.lines}
    assert all(
        set(request.grounded_audit_line_ids) <= line_ids
        for request in result.review_requests
    )


def test_tariff_charge_in_wrong_section_fails_closed() -> None:
    bill = load_sample("authentic")
    charges = tuple(
        charge.model_copy(update={"section": "cca_generation"})
        if charge.id == "pge_peak_energy"
        else charge
        for charge in bill.charges
    )

    _assert_internal_fallback(bill.model_copy(update={"charges": charges}))


def test_non_usd_legacy_bill_fails_closed() -> None:
    bill = load_sample("authentic")
    charges = tuple(
        charge.model_copy(
            update={
                "billed_amount": charge.billed_amount.model_copy(
                    update={"unit": "EUR"}
                )
            }
        )
        for charge in bill.charges
    )
    money_fields = (
        "delivery_subtotal",
        "generation_subtotal",
        "current_charges",
        "outstanding_balance",
        "amount_due",
    )
    updates = {
        field: getattr(bill, field).model_copy(update={"unit": "EUR"})
        for field in money_fields
    }
    updates["charges"] = charges

    _assert_internal_fallback(bill.model_copy(update=updates))


def test_unsupported_tariff_operand_unit_fails_closed() -> None:
    bill = load_sample("authentic")
    charges = tuple(
        charge.model_copy(
            update={
                "quantity": charge.quantity.model_copy(update={"unit": "MWh"})
            }
        )
        if charge.id == "pge_peak_energy" and charge.quantity is not None
        else charge
        for charge in bill.charges
    )

    _assert_internal_fallback(bill.model_copy(update={"charges": charges}))


@pytest.mark.parametrize("malformation", ["missing_rule", "wrong_rule_kind"])
def test_malformed_archived_rule_set_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    bundle = load_tariff_bundle(verify_sources=False)
    rules = dict(bundle.rules)
    if malformation == "missing_rule":
        rules.pop("pge_peak_energy")
    else:
        rules["pge_peak_energy"] = replace(
            rules["pge_peak_energy"],
            kind="unsupported_rule",
        )
    malformed = replace(bundle, rules=rules)

    def load_malformed_bundle(*, verify_sources: bool = True) -> TariffBundle:
        del verify_sources
        return malformed

    monkeypatch.setattr(adapters, "load_tariff_bundle", load_malformed_bundle)

    _assert_internal_fallback(load_sample("authentic"))


def test_percentage_rule_dependencies_must_precede_dependent_charge() -> None:
    bill = load_sample("authentic")
    charges = list(bill.charges)
    uut = next(charge for charge in charges if charge.id == "cca_nov_uut")
    charges.remove(uut)
    insert_at = next(
        index for index, charge in enumerate(charges) if charge.id == "cca_nov_peak"
    )
    charges.insert(insert_at, uut)

    _assert_internal_fallback(bill.model_copy(update={"charges": tuple(charges)}))


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


def test_generation_discrepancy_addresses_generation_provider() -> None:
    bill = _changed_charge_amount(
        load_sample("authentic"),
        "cca_nov_peak",
        Decimal("3.00"),
    )

    result = audit_extraction(bill)

    assert len(result.review_requests) == 1
    request = result.review_requests[0]
    assert request.provider == bill.generation_provider.value
    assert request.grounded_audit_line_ids == ("cca_nov_peak",)
    assert request.requires_user_review is True
    assert set(request.grounded_audit_line_ids) <= {
        line.id for line in result.lines
    }


def test_mixed_provider_discrepancies_split_provider_requests() -> None:
    bill = _changed_charge_amount(
        load_sample("authentic"),
        "pge_peak_energy",
        Decimal("5.00"),
    )
    bill = _changed_charge_amount(
        bill,
        "cca_nov_peak",
        Decimal("3.00"),
    )

    result = audit_extraction(bill)

    assert tuple(request.provider for request in result.review_requests) == (
        bill.delivery_provider.value,
        bill.generation_provider.value,
    )
    assert tuple(
        request.grounded_audit_line_ids for request in result.review_requests
    ) == (("pge_peak_energy",), ("cca_nov_peak",))
    sections = {line.id: line.section_id for line in result.lines}
    for request in result.review_requests:
        assert request.requires_user_review is True
        expected_section = (
            "pge_delivery"
            if request.provider == bill.delivery_provider.value
            else "cca_generation"
        )
        assert all(
            sections[line_id] == expected_section
            for line_id in request.grounded_audit_line_ids
        )


def test_reconciliation_only_amount_due_root_gets_neutral_request() -> None:
    bill = load_sample("authentic")
    bill = bill.model_copy(
        update={
            "amount_due": bill.amount_due.model_copy(
                update={"value": bill.amount_due.value + Decimal("2.00")}
            )
        }
    )

    result = audit_extraction(bill)
    lines = {line.id: line for line in result.lines}

    assert result.verdict == "possible_discrepancy"
    assert tuple(request.provider for request in result.review_requests) == (
        "Consolidated statement",
    )
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("amount_due",)
    assert lines["amount_due"].label in request.body
    assert "not attributed to a particular provider" in request.body
    assert "does not allege provider error" in request.body
    assert "PG&E peak energy" not in request.body
    assert "3CE November Energy Commission tax" not in request.body
    assert request.requires_user_review is True


def test_tariff_and_independent_statement_roots_both_receive_drafts() -> None:
    bill = _changed_charge_amount(
        load_sample("authentic"),
        "pge_peak_energy",
        Decimal("5.00"),
    )
    bill = _changed_charge_amount(
        bill,
        "cca_nov_peak",
        Decimal("3.00"),
    )
    bill = bill.model_copy(
        update={
            "amount_due": bill.amount_due.model_copy(
                update={"value": bill.amount_due.value + Decimal("2.00")}
            )
        }
    )

    result = audit_extraction(bill)
    lines = {line.id: line for line in result.lines}

    assert result.verdict == "possible_discrepancy"
    assert tuple(request.provider for request in result.review_requests) == (
        bill.delivery_provider.value,
        bill.generation_provider.value,
        "Consolidated statement",
    )
    assert tuple(
        request.grounded_audit_line_ids for request in result.review_requests
    ) == (("pge_peak_energy",), ("cca_nov_peak",), ("amount_due",))
    grounded = tuple(
        line_id
        for request in result.review_requests
        for line_id in request.grounded_audit_line_ids
    )
    assert len(grounded) == len(set(grounded))
    assert "delivery_subtotal" not in grounded
    assert "generation_subtotal" not in grounded
    assert lines["delivery_subtotal"].root_cause_id == "pge_peak_energy"
    assert lines["generation_subtotal"].root_cause_id == "cca_nov_peak"
    assert lines["amount_due"].label in result.review_requests[2].body
    assert lines["pge_peak_energy"].label not in result.review_requests[2].body
    assert lines["cca_nov_peak"].label not in result.review_requests[2].body


def test_section_level_reconciliation_root_routes_to_section_provider() -> None:
    bill = load_sample("authentic")
    delta = Decimal("2.00")
    bill = bill.model_copy(
        update={
            "delivery_subtotal": bill.delivery_subtotal.model_copy(
                update={"value": bill.delivery_subtotal.value + delta}
            ),
            "current_charges": bill.current_charges.model_copy(
                update={"value": bill.current_charges.value + delta}
            ),
            "amount_due": bill.amount_due.model_copy(
                update={"value": bill.amount_due.value + delta}
            ),
        }
    )

    result = audit_extraction(bill)
    lines = {line.id: line for line in result.lines}

    assert result.verdict == "possible_discrepancy"
    assert tuple(request.provider for request in result.review_requests) == (
        bill.delivery_provider.value,
    )
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("delivery_subtotal",)
    assert lines["delivery_subtotal"].root_cause_id is None
    assert lines["delivery_subtotal"].label in request.body
    assert bill.delivery_provider.value in request.body
    assert "3CE generation lines sum to subtotal" not in request.body


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
