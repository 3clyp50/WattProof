from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .audit import UnsupportedBillError, audit_bill, validate_pge_3ce_bill
from .models import AuditLine, AuditResult, AuditStatus, BillExtraction, EvidenceBase
from .tariffs import load_tariff_bundle
from .utility_models import (
    AuditScope,
    AuditStatusV2,
    EvidenceRef,
    ProviderReviewRequest,
    UtilityAuditLine,
    UtilityAuditResult,
)

_TOLERANCE = Decimal("0.01")


@runtime_checkable
class TariffAdapter(Protocol):
    """Immutable-behavior contract for an exact tariff verifier."""

    def matches(self, bill: BillExtraction) -> bool:
        """Return whether this adapter can verify the complete bill identity."""

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        """Audit a bill already known to match this adapter."""


def _mapped_status(status: AuditStatus) -> AuditStatusV2:
    if status == "verified":
        return "verified"
    if status == "discrepancy":
        return "discrepancy"
    if status == "cannot_verify":
        return "cannot_verify"
    if status == "needs_review":
        return "needs_review"
    if status == "estimated":
        return "cannot_verify"
    raise ValueError(f"Unsupported legacy audit status: {status}")


def _mapped_scope(line: AuditLine) -> AuditScope:
    if line.category == "tariff":
        return "published_tariff"
    return "statement_reconciliation"


def _facts_by_line_id(bill: BillExtraction) -> dict[str, EvidenceBase]:
    facts: dict[str, EvidenceBase] = {
        charge.id: charge.billed_amount for charge in bill.charges
    }
    facts.update(
        {
            "delivery_subtotal": bill.delivery_subtotal,
            "generation_subtotal": bill.generation_subtotal,
            "current_charges": bill.current_charges,
            "amount_due": bill.amount_due,
            "meter_delta": bill.total_usage,
        }
    )
    return facts


def _section_by_line_id(bill: BillExtraction) -> dict[str, str | None]:
    sections: dict[str, str | None] = {
        charge.id: charge.section for charge in bill.charges
    }
    sections.update(
        {
            "delivery_subtotal": "pge_delivery",
            "generation_subtotal": "cca_generation",
            "current_charges": None,
            "amount_due": None,
            "meter_delta": "pge_delivery",
        }
    )
    return sections


def _evidence(line: AuditLine, fact: EvidenceBase | None) -> EvidenceRef:
    confidence = Decimal("0") if fact is None else Decimal(str(fact.confidence))
    return EvidenceRef(
        page=line.source_page,
        text=line.source_text,
        confidence=confidence,
        provenance="rendered_page",
    )


def _root_causes(
    bill: BillExtraction,
    result: AuditResult,
) -> dict[str, str]:
    legacy_lines = {line.id: line for line in result.lines}
    roots: dict[str, str] = {}
    section_subtotals = (
        ("pge_delivery", "delivery_subtotal", bill.delivery_subtotal.value),
        ("cca_generation", "generation_subtotal", bill.generation_subtotal.value),
    )
    for section_id, subtotal_id, billed_subtotal in section_subtotals:
        subtotal_line = legacy_lines[subtotal_id]
        if subtotal_line.status != "discrepancy":
            continue
        section_charges = tuple(
            charge for charge in bill.charges if charge.section == section_id
        )
        direct_discrepancies = tuple(
            legacy_lines[charge.id]
            for charge in section_charges
            if legacy_lines[charge.id].category == "tariff"
            and legacy_lines[charge.id].status == "discrepancy"
            and legacy_lines[charge.id].expected_amount is not None
        )
        if len(direct_discrepancies) != 1:
            continue
        direct = direct_discrepancies[0]
        direct_expected = direct.expected_amount
        if direct_expected is None:
            continue
        corrected_sum = sum(
            (
                direct_expected
                if charge.id == direct.id
                else charge.billed_amount.value
                for charge in section_charges
            ),
            Decimal("0"),
        )
        if abs(billed_subtotal - corrected_sum) <= _TOLERANCE:
            roots[subtotal_id] = direct.id
    return roots


def _map_result(bill: BillExtraction, result: AuditResult) -> UtilityAuditResult:
    facts = _facts_by_line_id(bill)
    sections = _section_by_line_id(bill)
    root_causes = _root_causes(bill, result)
    mapped_lines = tuple(
        UtilityAuditLine(
            id=line.id,
            section_id=sections.get(line.id),
            label=line.label,
            scope=_mapped_scope(line),
            unit=line.unit,
            billed_amount=line.billed_amount,
            billed_status=facts[line.id].status if line.id in facts else None,
            billed_original_value=(
                facts[line.id].original_value if line.id in facts else None
            ),
            expected_amount=line.expected_amount,
            delta=line.delta,
            formula=line.formula,
            inputs=line.inputs,
            evidence=(_evidence(line, facts.get(line.id)),),
            citations=line.citations,
            status=_mapped_status(line.status),
            limitation=line.limitation,
            root_cause_id=root_causes.get(line.id),
        )
        for line in result.lines
    )
    review = result.review_request
    review_request = ProviderReviewRequest(
        provider=bill.delivery_provider.value,
        subject=review.subject,
        body=review.body,
        grounded_audit_line_ids=review.grounded_audit_line_ids,
        requires_user_review=review.requires_user_review,
    )
    return UtilityAuditResult(
        schema_version="2.0",
        fixture_kind=result.fixture_kind,
        verdict=result.verdict,
        verification_level="tariff_verified",
        headline=result.headline,
        discrepancy_total=result.discrepancy_total,
        currency=bill.current_charges.unit,
        lines=mapped_lines,
        tariff=result.tariff,
        comparison=result.comparison,
        review_requests=(review_request,),
    )


@dataclass(frozen=True, slots=True)
class Pge3ceAdapter:
    """Exact adapter for the archived PG&E/3CE E-TOU-C tariff bundle."""

    def matches(self, bill: BillExtraction) -> bool:
        unchecked_bundle = load_tariff_bundle(verify_sources=False)
        try:
            validate_pge_3ce_bill(bill, unchecked_bundle)
        except UnsupportedBillError:
            return False

        verified_bundle = load_tariff_bundle(verify_sources=True)
        validate_pge_3ce_bill(bill, verified_bundle)
        return True

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        return _map_result(bill, audit_bill(bill))


PGE_3CE_ADAPTER = Pge3ceAdapter()
TARIFF_ADAPTERS: tuple[TariffAdapter, ...] = (PGE_3CE_ADAPTER,)
