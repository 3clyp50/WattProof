from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .audit import UnsupportedBillError, audit_bill, validate_pge_3ce_bill
from .models import (
    AuditLine,
    AuditResult,
    AuditStatus,
    BillExtraction,
    ChargeLine,
    EvidenceBase,
)
from .tariffs import TariffBundle, load_tariff_bundle
from .utility_models import (
    AuditScope,
    AuditStatusV2,
    EvidenceRef,
    ProviderReviewRequest,
    UtilityAuditLine,
    UtilityAuditResult,
)

_TOLERANCE = Decimal("0.01")
_DELIVERY_CHARGE_IDS = frozenset(
    {
        "pge_peak_energy",
        "pge_off_peak_energy",
        "pge_baseline_credit",
        "pge_generation_credit",
        "pge_pcia",
        "pge_franchise_fee",
        "pge_uut",
    }
)
_GENERATION_CHARGE_IDS = frozenset(
    {
        "cca_nov_peak",
        "cca_nov_off_peak",
        "cca_nov_energy_commission_tax",
        "cca_nov_uut",
        "cca_dec_peak",
        "cca_dec_off_peak",
        "cca_dec_energy_commission_tax",
        "cca_dec_uut",
    }
)
_EXPECTED_CHARGE_IDS = _DELIVERY_CHARGE_IDS | _GENERATION_CHARGE_IDS
_QUANTITY_RATE_CHARGE_IDS = frozenset(
    {
        "pge_peak_energy",
        "pge_off_peak_energy",
        "pge_baseline_credit",
        "cca_nov_peak",
        "cca_nov_off_peak",
        "cca_dec_peak",
        "cca_dec_off_peak",
    }
)
_PERCENT_RATE_CHARGE_IDS = frozenset(
    {"pge_uut", "cca_nov_uut", "cca_dec_uut"}
)
_NO_PRINTED_OPERAND_CHARGE_IDS = frozenset(
    {
        "pge_generation_credit",
        "pge_pcia",
        "pge_franchise_fee",
        "cca_nov_energy_commission_tax",
        "cca_dec_energy_commission_tax",
    }
)
_EXPECTED_RULE_STRUCTURE = {
    "pge_peak_energy": (
        "quantity_times_rate",
        (),
        ("pge_nov", "pge_dec"),
    ),
    "pge_off_peak_energy": (
        "quantity_times_rate",
        (),
        ("pge_nov", "pge_dec"),
    ),
    "pge_baseline_credit": ("quantity_times_rate", (), ("baseline",)),
    "pge_franchise_fee": ("quantity_times_rate", (), ("3ce",)),
    "cca_nov_peak": ("quantity_times_rate", (), ("3ce",)),
    "cca_nov_off_peak": ("quantity_times_rate", (), ("3ce",)),
    "cca_dec_peak": ("quantity_times_rate", (), ("3ce",)),
    "cca_dec_off_peak": ("quantity_times_rate", (), ("3ce",)),
    "cca_nov_uut": (
        "percent_of_lines",
        ("cca_nov_peak", "cca_nov_off_peak"),
        (),
    ),
    "cca_dec_uut": (
        "percent_of_lines",
        ("cca_dec_peak", "cca_dec_off_peak"),
        (),
    ),
}
_EXPECTED_LIMITATION_IDS = frozenset(
    {
        "pge_generation_credit",
        "pge_pcia",
        "pge_uut",
        "cca_nov_energy_commission_tax",
        "cca_dec_energy_commission_tax",
    }
)
_EXPECTED_CITATION_IDS = frozenset({"pge_nov", "pge_dec", "baseline", "3ce"})


@runtime_checkable
class TariffAdapter(Protocol):
    """Immutable-behavior contract for an exact tariff verifier."""

    def matches(self, bill: BillExtraction) -> bool:
        """Return whether this adapter can verify the complete bill identity."""

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        """Audit a bill already known to match this adapter."""


def _bundle_has_expected_structure(bundle: TariffBundle) -> bool:
    version = bundle.version
    if (
        version.id != "pge_3ce_e_tou_c_2022_h2"
        or version.provider
        != "Pacific Gas and Electric Company + Central Coast Community Energy"
        or version.schedule != "E-TOU-C / MBRETCH1 3Cchoice"
        or version.jurisdiction != "California"
        or version.effective_start != date(2022, 6, 1)
        or version.effective_end != date(2022, 12, 31)
    ):
        return False
    if set(bundle.citation_map) != _EXPECTED_CITATION_IDS:
        return False
    if set(bundle.rules) != set(_EXPECTED_RULE_STRUCTURE):
        return False
    if set(bundle.limitations) != _EXPECTED_LIMITATION_IDS:
        return False
    if any(not limitation.strip() for limitation in bundle.limitations.values()):
        return False
    return all(
        (rule.kind, rule.line_ids, rule.citations) == expected
        for rule_id, expected in _EXPECTED_RULE_STRUCTURE.items()
        for rule in (bundle.rules[rule_id],)
    )


def _charge_has_supported_operands(charge: ChargeLine) -> bool:
    if charge.billed_amount.unit != "USD":
        return False
    if charge.id in _QUANTITY_RATE_CHARGE_IDS:
        return (
            charge.quantity is not None
            and charge.quantity.unit == "kWh"
            and charge.rate is not None
            and charge.rate.unit == "USD/kWh"
        )
    if charge.id in _PERCENT_RATE_CHARGE_IDS:
        return (
            charge.quantity is None
            and charge.rate is not None
            and charge.rate.unit == "fraction"
        )
    if charge.id in _NO_PRINTED_OPERAND_CHARGE_IDS:
        return charge.quantity is None and charge.rate is None
    return False


def _bill_has_expected_structure(bill: BillExtraction) -> bool:
    charges_by_id = {charge.id: charge for charge in bill.charges}
    if (
        len(bill.charges) != len(_EXPECTED_CHARGE_IDS)
        or set(charges_by_id) != _EXPECTED_CHARGE_IDS
    ):
        return False
    if any(
        charge.section
        != ("pge_delivery" if charge.id in _DELIVERY_CHARGE_IDS else "cca_generation")
        for charge in bill.charges
    ):
        return False
    if any(not _charge_has_supported_operands(charge) for charge in bill.charges):
        return False
    seen_charge_ids: set[str] = set()
    for charge in bill.charges:
        rule_structure = _EXPECTED_RULE_STRUCTURE.get(charge.id)
        if (
            rule_structure is not None
            and rule_structure[0] == "percent_of_lines"
            and not set(rule_structure[1]) <= seen_charge_ids
        ):
            return False
        seen_charge_ids.add(charge.id)
    if any(
        fact.unit != "USD"
        for fact in (
            bill.delivery_subtotal,
            bill.generation_subtotal,
            bill.current_charges,
            bill.outstanding_balance,
            bill.amount_due,
        )
    ):
        return False
    return (
        bill.billing_days.unit == "days"
        and bill.total_usage.unit == "kWh"
        and bill.peak_usage.unit == "kWh"
        and bill.off_peak_usage.unit == "kWh"
        and bill.baseline_allowance.unit == "kWh"
        and bill.daily_baseline_quantity.unit == "kWh/day"
    )


def _supports_tariff_application(
    bill: BillExtraction,
    bundle: TariffBundle,
) -> bool:
    return _bundle_has_expected_structure(bundle) and _bill_has_expected_structure(bill)


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


def _currency(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def _issue_detail(line: AuditLine) -> str:
    if (
        line.status == "discrepancy"
        and line.expected_amount is not None
        and line.delta is not None
    ):
        detail = (
            f"- {line.label}: the statement shows {_currency(line.billed_amount)}; "
            f"the recomputed value is {_currency(line.expected_amount)}; "
            f"the difference is {_currency(abs(line.delta))}.\n"
            f"  Calculation: {line.formula}."
        )
    elif line.status == "needs_review":
        detail = (
            f"- {line.label}: the reported operands need review before WattProof "
            "can reach a conclusion."
        )
    else:
        detail = f"- {line.label}: this issue needs calculation detail."
    detail += f"\n  Rendered-page evidence is recorded on page {line.source_page}."
    if line.citations:
        sources = "; ".join(
            f"{citation.label}: {citation.source_url}"
            for citation in line.citations
        )
        detail += f"\n  Archived sources: {sources}."
    return detail


def _generated_issue_request_body(
    bill: BillExtraction,
    provider: str,
    lines: tuple[AuditLine, ...],
) -> str:
    details = tuple(_issue_detail(line) for line in lines)
    synthetic_notice = (
        "This is a synthetic demo request; no real customer bill contained "
        "these errors.\n\n"
        if bill.fixture_kind == "synthetic"
        else ""
    )
    return (
        f"Hello,\n\n{synthetic_notice}Please review these {provider} statement "
        f"relationships dated {bill.statement_date.value.isoformat()}:\n"
        + "\n".join(details)
        + "\n\nPlease confirm the reported operands and calculation detail. "
        "I will verify my account details before sending. Thank you."
    )


def _validated_grounding(
    grounded_ids: tuple[str, ...],
    line_ids: set[str],
) -> tuple[str, ...]:
    missing = tuple(line_id for line_id in grounded_ids if line_id not in line_ids)
    if missing:
        raise ValueError(
            "Provider review request references missing audit lines: "
            + ", ".join(missing)
        )
    return grounded_ids


def _clean_provider_request(
    bill: BillExtraction,
    provider: str,
    lines: tuple[AuditLine, ...],
) -> ProviderReviewRequest:
    details: list[str] = []
    for line in lines:
        if line.status == "verified":
            finding = (
                "WattProof recomputed this line and it agreed with the printed "
                f"amount. Calculation: {line.formula}."
            )
        elif line.status == "cannot_verify":
            finding = (
                "WattProof could not independently recompute this line from the "
                "currently archived sources."
            )
        else:
            finding = (
                "WattProof recorded this line as "
                f"{line.status.replace('_', ' ')} and needs calculation detail."
            )
        if line.citations:
            sources = "; ".join(
                f"{citation.label}: {citation.source_url}"
                for citation in line.citations
            )
            finding += f" Archived sources: {sources}."
        details.append(f"- {line.label}: {finding}")
    body = (
        f"Hello,\n\nPlease confirm these {provider} charge calculations on my "
        f"statement dated {bill.statement_date.value.isoformat()}. WattProof's "
        "notes below are limited to lines attributed to your organization:\n"
        + "\n".join(details)
        + "\n\nPlease provide the applicable rates or calculation detail for the "
        "listed lines. I will verify my account details before sending. Thank you."
    )
    return ProviderReviewRequest(
        provider=provider,
        subject=f"Request for {provider} charge calculation detail",
        body=body,
        grounded_audit_line_ids=tuple(line.id for line in lines),
        requires_user_review=True,
    )


def _draft_issue_lines(
    lines: tuple[UtilityAuditLine, ...],
) -> tuple[UtilityAuditLine, ...]:
    candidates = tuple(
        line for line in lines if line.status in {"discrepancy", "needs_review"}
    )
    represented_roots = {
        line.id for line in candidates if line.root_cause_id is None
    }
    return tuple(
        line
        for line in candidates
        if line.root_cause_id is None or line.root_cause_id not in represented_roots
    )


def _consolidated_issue_request(
    lines: tuple[AuditLine, ...],
) -> ProviderReviewRequest:
    details = "\n".join(_issue_detail(line) for line in lines)
    return ProviderReviewRequest(
        provider="Consolidated statement",
        subject="Request to review consolidated statement calculations",
        body=(
            "Hello,\n\nPlease review the following cross-section statement "
            "relationships. This request is not attributed to a particular "
            "provider and does not allege provider error:\n"
            f"{details}\n\nPlease confirm the statement roll-forward and calculation "
            "detail. I will verify my account details before sending. Thank you."
        ),
        grounded_audit_line_ids=tuple(line.id for line in lines),
        requires_user_review=True,
    )


def _provider_review_requests(
    bill: BillExtraction,
    result: AuditResult,
    mapped_lines: tuple[UtilityAuditLine, ...],
) -> tuple[ProviderReviewRequest, ...]:
    line_ids = {line.id for line in mapped_lines}
    section_by_id = _section_by_line_id(bill)
    provider_sections = (
        ("pge_delivery", bill.delivery_provider.value),
        ("cca_generation", bill.generation_provider.value),
    )
    issue_lines = _draft_issue_lines(mapped_lines)
    if not issue_lines:
        review = result.review_request
        grounded = _validated_grounding(
            review.grounded_audit_line_ids,
            line_ids,
        )
        result_lines = {line.id: line for line in result.lines}
        clean_requests = tuple(
            _clean_provider_request(
                bill,
                provider,
                tuple(
                    result_lines[line_id]
                    for line_id in grounded
                    if section_by_id.get(line_id) == section_id
                ),
            )
            for section_id, provider in provider_sections
            if any(section_by_id.get(line_id) == section_id for line_id in grounded)
        )
        partitioned = tuple(
            line_id
            for request in clean_requests
            for line_id in request.grounded_audit_line_ids
        )
        if len(partitioned) != len(grounded) or set(partitioned) != set(grounded):
            raise ValueError(
                "Provider review request grounding has no supported provider section"
            )
        return clean_requests

    requests: list[ProviderReviewRequest] = []
    result_lines = {line.id: line for line in result.lines}
    legacy_review = result.review_request
    for section_id, provider in provider_sections:
        provider_issue_lines = tuple(
            line
            for line in issue_lines
            if line.section_id == section_id
        )
        if not provider_issue_lines:
            continue
        grounded = _validated_grounding(
            tuple(line.id for line in provider_issue_lines),
            line_ids,
        )
        provider_lines = tuple(result_lines[line_id] for line_id in grounded)
        if grounded == legacy_review.grounded_audit_line_ids:
            subject = legacy_review.subject
            body = legacy_review.body
        else:
            subject = f"Request to review {provider} statement calculations"
            body = _generated_issue_request_body(
                bill,
                provider,
                provider_lines,
            )
        requests.append(
            ProviderReviewRequest(
                provider=provider,
                subject=subject,
                body=body,
                grounded_audit_line_ids=grounded,
                requires_user_review=True,
            )
        )
    neutral_issue_lines = tuple(
        line for line in issue_lines if line.section_id is None
    )
    if neutral_issue_lines:
        neutral_grounded = _validated_grounding(
            tuple(line.id for line in neutral_issue_lines),
            line_ids,
        )
        requests.append(
            _consolidated_issue_request(
                tuple(result_lines[line_id] for line_id in neutral_grounded)
            )
        )
    issue_ids = tuple(line.id for line in issue_lines)
    partitioned = tuple(
        line_id
        for request in requests
        for line_id in request.grounded_audit_line_ids
    )
    if len(partitioned) != len(issue_ids) or set(partitioned) != set(issue_ids):
        raise ValueError("Issue draft grounding has no supported provider section")
    return tuple(requests)


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
    review_requests = _provider_review_requests(bill, result, mapped_lines)
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
        review_requests=review_requests,
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
        if not _supports_tariff_application(bill, unchecked_bundle):
            return False

        verified_bundle = load_tariff_bundle(verify_sources=True)
        validate_pge_3ce_bill(bill, verified_bundle)
        return _supports_tariff_application(bill, verified_bundle)

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        return _map_result(bill, audit_bill(bill))


PGE_3CE_ADAPTER = Pge3ceAdapter()
TARIFF_ADAPTERS: tuple[TariffAdapter, ...] = (PGE_3CE_ADAPTER,)
