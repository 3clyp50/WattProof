from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .audit import (
    UnsupportedBillError,
    audit_bill_with_bundle,
    round_money,
    validate_pge_3ce_bill,
    validate_pge_3ce_identity,
)
from .models import (
    AuditLine,
    AuditResult,
    AuditStatus,
    BillExtraction,
    ChargeLine,
    Citation,
    EvidenceBase,
    TariffVersion,
)
from .numeric import abs_exact, add_exact, subtract_exact, sum_exact
from .tariffs import RateRule, TariffBundle, load_tariff_bundle
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
_ARCHIVED_PRINTED_RATE_CHARGE_IDS = _QUANTITY_RATE_CHARGE_IDS | frozenset(
    {"cca_nov_uut", "cca_dec_uut"}
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
_EXPECTED_CITATIONS = {
    "pge_nov": Citation(
        label="PG&E historic residential inclusive TOU rates, June-November 2022",
        source_url=(
            "https://www.pge.com/assets/rates/tariffs/"
            "Res_Inclu_TOU_220601-221130.xlsx"
        ),
        local_path="sources/pge-residential-inclu-tou-2022-06-01-to-2022-11-30.xlsx",
        effective_start=date(2022, 6, 1),
        effective_end=date(2022, 11, 30),
        sha256="d25d2042a895e1715fd0bdd5166cfa513d5aa1c715ab0dc51382e034dd093958",
    ),
    "pge_dec": Citation(
        label="PG&E historic residential inclusive TOU rates, December 2022",
        source_url=(
            "https://www.pge.com/assets/rates/tariffs/"
            "Res_Inclu_TOU_221201-221231.xlsx"
        ),
        local_path="sources/pge-residential-inclu-tou-2022-12-01-to-2022-12-31.xlsx",
        effective_start=date(2022, 12, 1),
        effective_end=date(2022, 12, 31),
        sha256="2bae786f92efa2eba420adc35e50b80dab71726a43d45f664283fbf744981589",
    ),
    "baseline": Citation(
        label="PG&E residential baseline quantities",
        source_url=(
            "https://www.pge.com/assets/rates/tariffs/ResElecBaselineCurrent.xlsx"
        ),
        local_path="sources/pge-residential-baseline-2022-06-01-present.xlsx",
        effective_start=date(2022, 6, 1),
        effective_end=None,
        sha256="f9069d80c963341d81adcac87684c6a4b0893b9d6fda21cba11fb2f34dc36bfe",
    ),
    "3ce": Citation(
        label="3CE residential generation rates effective March 1, 2022",
        source_url=(
            "https://3cenergy.org/wp-content/uploads/2023/03/"
            "3CE-Residential-Rate-Sheet-Mar1.22_FINAL-1.pdf"
        ),
        local_path="sources/3ce-residential-rate-sheet-effective-2022-03-01.pdf",
        effective_start=date(2022, 3, 1),
        effective_end=None,
        sha256="774a4f035824713acb0671935f6276516ff33f30026cd008947b170b2543b279",
    ),
}
_EXPECTED_VERSION = TariffVersion(
    id="pge_3ce_e_tou_c_2022_h2",
    provider="Pacific Gas and Electric Company + Central Coast Community Energy",
    schedule="E-TOU-C / MBRETCH1 3Cchoice",
    jurisdiction="California",
    effective_start=date(2022, 6, 1),
    effective_end=date(2022, 12, 31),
    retrieved_on=date(2026, 7, 19),
    citations=tuple(_EXPECTED_CITATIONS.values()),
)
_EXPECTED_RULES = {
    "pge_peak_energy": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.39193"),
        citations=("pge_nov", "pge_dec"),
    ),
    "pge_off_peak_energy": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.37460"),
        citations=("pge_nov", "pge_dec"),
    ),
    "pge_baseline_credit": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("-0.09054"),
        citations=("baseline",),
    ),
    "pge_franchise_fee": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.00099"),
        citations=("3ce",),
    ),
    "cca_nov_peak": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.13800"),
        citations=("3ce",),
    ),
    "cca_nov_off_peak": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.09000"),
        citations=("3ce",),
    ),
    "cca_dec_peak": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.13800"),
        citations=("3ce",),
    ),
    "cca_dec_off_peak": RateRule(
        kind="quantity_times_rate",
        rate=Decimal("0.09000"),
        citations=("3ce",),
    ),
    "cca_nov_uut": RateRule(
        kind="percent_of_lines",
        rate=Decimal("0.01000"),
        line_ids=("cca_nov_peak", "cca_nov_off_peak"),
    ),
    "cca_dec_uut": RateRule(
        kind="percent_of_lines",
        rate=Decimal("0.01000"),
        line_ids=("cca_dec_peak", "cca_dec_off_peak"),
    ),
}
_EXPECTED_LIMITATIONS = {
    "pge_generation_credit": (
        "The matching archived generation-credit component source is unavailable."
    ),
    "pge_pcia": (
        "The available 3CE sheet calculates $4.50 rather than the printed $4.53, "
        "so WattProof will not force a match."
    ),
    "pge_uut": "The precise PG&E taxable base and rounding rule are not sourced.",
    "cca_nov_energy_commission_tax": (
        "The exact effective Energy Commission tax source is not archived."
    ),
    "cca_dec_energy_commission_tax": (
        "The exact effective Energy Commission tax source is not archived."
    ),
}


@runtime_checkable
class TariffAdapter(Protocol):
    """Immutable-behavior contract for an exact tariff verifier."""

    def matches(self, bill: BillExtraction) -> bool:
        """Return whether this adapter can verify the complete bill identity."""

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        """Audit a bill already known to match this adapter."""

    def audit_if_supported(
        self,
        bill: BillExtraction,
    ) -> UtilityAuditResult | None:
        """Audit from one verified snapshot, or return None when unsupported."""


def _bundle_has_expected_structure(bundle: TariffBundle) -> bool:
    return (
        bundle.version == _EXPECTED_VERSION
        and bundle.citation_map == _EXPECTED_CITATIONS
        and bundle.rules == _EXPECTED_RULES
        and bundle.limitations == _EXPECTED_LIMITATIONS
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


def _bill_has_expected_structure(
    bill: BillExtraction,
    bundle: TariffBundle,
) -> bool:
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
        rule = _EXPECTED_RULES.get(charge.id)
        if (
            rule is not None
            and rule.kind == "percent_of_lines"
            and not set(rule.line_ids) <= seen_charge_ids
        ):
            return False
        seen_charge_ids.add(charge.id)
    for charge_id in _ARCHIVED_PRINTED_RATE_CHARGE_IDS:
        printed_rate = charges_by_id[charge_id].rate
        rule = bundle.rules[charge_id]
        if printed_rate is None or printed_rate.value != rule.rate:
            return False
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
    return _bundle_has_expected_structure(bundle) and _bill_has_expected_structure(
        bill,
        bundle,
    )


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
    confidence = Decimal("0") if fact is None else fact.confidence
    return EvidenceRef(
        page=line.source_page,
        text=line.source_text,
        confidence=confidence,
        provenance="rendered_page",
    )


@dataclass(frozen=True, slots=True)
class _ReconciledValue:
    amount: Decimal
    root_ids: frozenset[str]
    provable: bool


def _money_reconciles(billed: Decimal, expected: Decimal) -> bool:
    return abs_exact(subtract_exact(billed, expected)) <= _TOLERANCE


def _root_causes(
    bill: BillExtraction,
    result: AuditResult,
) -> dict[str, str]:
    legacy_lines = {line.id: line for line in result.lines}
    roots: dict[str, str] = {}
    section_values: list[_ReconciledValue] = []
    section_subtotals = (
        ("pge_delivery", "delivery_subtotal", bill.delivery_subtotal.value),
        ("cca_generation", "generation_subtotal", bill.generation_subtotal.value),
    )
    for section_id, subtotal_id, billed_subtotal in section_subtotals:
        charge_values: list[_ReconciledValue] = []
        for charge in bill.charges:
            if charge.section != section_id:
                continue
            line = legacy_lines[charge.id]
            if line.status == "discrepancy" and line.expected_amount is not None:
                charge_values.append(
                    _ReconciledValue(
                        line.expected_amount,
                        frozenset((line.id,)),
                        True,
                    )
                )
            else:
                charge_values.append(
                    _ReconciledValue(
                        charge.billed_amount.value,
                        frozenset(),
                        True,
                    )
                )

        corrected_subtotal = sum_exact(tuple(value.amount for value in charge_values))
        root_ids = set().union(*(value.root_ids for value in charge_values))
        provable = all(value.provable for value in charge_values)
        subtotal_line = legacy_lines[subtotal_id]
        if subtotal_line.status == "discrepancy":
            if (
                provable
                and len(root_ids) == 1
                and _money_reconciles(billed_subtotal, corrected_subtotal)
            ):
                roots[subtotal_id] = next(iter(root_ids))
            else:
                root_ids.add(subtotal_id)
        section_values.append(
            _ReconciledValue(
                corrected_subtotal,
                frozenset(root_ids),
                provable,
            )
        )

    corrected_current = sum_exact(tuple(value.amount for value in section_values))
    current_root_ids = set().union(
        *(value.root_ids for value in section_values)
    )
    current_provable = all(value.provable for value in section_values)
    current_line = legacy_lines["current_charges"]
    if current_line.status == "discrepancy":
        if (
            current_provable
            and len(current_root_ids) == 1
            and _money_reconciles(
                bill.current_charges.value,
                corrected_current,
            )
        ):
            roots["current_charges"] = next(iter(current_root_ids))
        else:
            current_root_ids.add("current_charges")
    current_value = _ReconciledValue(
        corrected_current,
        frozenset(current_root_ids),
        current_provable,
    )

    amount_due_line = legacy_lines["amount_due"]
    corrected_due = add_exact(current_value.amount, bill.outstanding_balance.value)
    if (
        amount_due_line.status == "discrepancy"
        and current_value.provable
        and len(current_value.root_ids) == 1
        and _money_reconciles(bill.amount_due.value, corrected_due)
    ):
        roots["amount_due"] = next(iter(current_value.root_ids))
    return roots


def _currency(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs_exact(value):.2f}"


def _issue_detail(line: AuditLine) -> str:
    if (
        line.status == "discrepancy"
        and line.expected_amount is not None
        and line.delta is not None
    ):
        detail = (
            f"- {line.label}: the statement shows {_currency(line.billed_amount)}; "
            f"the recomputed value is {_currency(line.expected_amount)}; "
            f"the difference is {_currency(abs_exact(line.delta))}.\n"
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
    synthetic_notice = (
        "This is a synthetic demo request; no real customer bill contained "
        "this demo condition.\n\n"
        if bill.fixture_kind == "synthetic"
        else ""
    )
    body = (
        f"Hello,\n\n{synthetic_notice}Please confirm these {provider} charge "
        "calculations on my "
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
    bill: BillExtraction,
    lines: tuple[AuditLine, ...],
) -> ProviderReviewRequest:
    details = "\n".join(_issue_detail(line) for line in lines)
    synthetic_notice = (
        "This is a synthetic demo request; no real customer bill contained "
        "these errors.\n\n"
        if bill.fixture_kind == "synthetic"
        else ""
    )
    return ProviderReviewRequest(
        provider="Consolidated statement",
        subject="Request to review consolidated statement calculations",
        body=(
            f"Hello,\n\n{synthetic_notice}Please review the following cross-section "
            "statement "
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
                bill,
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
    discrepancy_total = round_money(
        sum_exact(
            tuple(
                abs_exact(line.delta)
                for line in mapped_lines
                if line.status == "discrepancy"
                and line.unit == "USD"
                and line.root_cause_id is None
                and line.delta is not None
            )
        )
    )
    headline = result.headline
    if result.verdict == "possible_discrepancy":
        headline = (
            f"Possible {_currency(discrepancy_total)} source-supported discrepancy"
        )
    return UtilityAuditResult(
        schema_version="2.0",
        fixture_kind=result.fixture_kind,
        verdict=result.verdict,
        verification_level="tariff_verified",
        headline=headline,
        discrepancy_total=discrepancy_total,
        currency=bill.current_charges.unit,
        lines=mapped_lines,
        tariff=result.tariff,
        comparison=result.comparison,
        review_requests=review_requests,
    )


@dataclass(frozen=True, slots=True)
class Pge3ceAdapter:
    """Exact adapter for the archived PG&E/3CE E-TOU-C tariff bundle."""

    @staticmethod
    def _verified_bundle_if_supported(
        bill: BillExtraction,
    ) -> TariffBundle | None:
        try:
            validate_pge_3ce_identity(bill)
        except UnsupportedBillError:
            return None

        verified_bundle = load_tariff_bundle(verify_sources=True)
        try:
            validate_pge_3ce_bill(bill, verified_bundle)
        except UnsupportedBillError:
            return None
        if not _supports_tariff_application(bill, verified_bundle):
            return None
        return verified_bundle

    def matches(self, bill: BillExtraction) -> bool:
        return self._verified_bundle_if_supported(bill) is not None

    def audit_if_supported(
        self,
        bill: BillExtraction,
    ) -> UtilityAuditResult | None:
        bundle = self._verified_bundle_if_supported(bill)
        if bundle is None:
            return None
        return _map_result(bill, audit_bill_with_bundle(bill, bundle))

    def audit(self, bill: BillExtraction) -> UtilityAuditResult:
        result = self.audit_if_supported(bill)
        if result is None:
            raise UnsupportedBillError(
                "This bill is unsupported by the archived PG&E/3CE adapter."
            )
        return result


PGE_3CE_ADAPTER = Pge3ceAdapter()
TARIFF_ADAPTERS: tuple[TariffAdapter, ...] = (PGE_3CE_ADAPTER,)
