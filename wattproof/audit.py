from __future__ import annotations

import unicodedata
from decimal import Decimal

from .models import (
    AuditLine,
    AuditResult,
    AuditStatus,
    BillExtraction,
    ChargeLine,
    Citation,
    PlanComparison,
    ReviewRequest,
)
from .numeric import (
    abs_exact,
    add_exact,
    format_decimal_exact,
    format_usd_exact,
    multiply_exact,
    quantize_exact,
    subtract_exact,
    sum_exact,
)
from .tariffs import RateRule, TariffBundle, load_tariff_bundle

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")


class UnsupportedBillError(ValueError):
    pass


def round_money(value: Decimal) -> Decimal:
    return quantize_exact(value, CENT)


def _status(delta: Decimal) -> AuditStatus:
    return "verified" if abs_exact(delta) <= TOLERANCE else "discrepancy"


def _currency(value: Decimal) -> str:
    return format_usd_exact(value)


def _rate(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${format_decimal_exact(abs_exact(value))}/kWh"


def _citation(bundle: TariffBundle, rule: RateRule) -> tuple[Citation, ...]:
    return tuple(bundle.citation_map[key] for key in rule.citations)


def _normalized_identity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


_DELIVERY_PROVIDER_ALIASES = frozenset(
    _normalized_identity(value)
    for value in (
        "Pacific Gas and Electric Company",
        "Pacific Gas & Electric Company",
        "PG&E",
    )
)
_GENERATION_PROVIDER_ALIASES = frozenset(
    _normalized_identity(value)
    for value in (
        "Central Coast Community Energy",
        "3CE",
    )
)
_DELIVERY_SCHEDULE_ALIASES = frozenset((_normalized_identity("E-TOU-C"),))
_GENERATION_SCHEDULE_ALIASES = frozenset(
    (_normalized_identity("MBRETCH1 3Cchoice"),)
)


def validate_pge_3ce_identity(bill: BillExtraction) -> None:
    """Require exact supported PG&E/3CE provider and schedule identities."""

    provider = _normalized_identity(bill.delivery_provider.value)
    if provider not in _DELIVERY_PROVIDER_ALIASES:
        raise UnsupportedBillError(
            "The MVP supports PG&E residential delivery bills only."
        )
    delivery_schedule = _normalized_identity(bill.delivery_schedule.value)
    if delivery_schedule not in _DELIVERY_SCHEDULE_ALIASES:
        raise UnsupportedBillError(
            "The MVP supports only PG&E E-TOU-C for this verified rate period."
        )
    generation_provider = _normalized_identity(bill.generation_provider.value)
    if generation_provider not in _GENERATION_PROVIDER_ALIASES:
        raise UnsupportedBillError(
            "The MVP supports Central Coast Community Energy generation only."
        )
    generation_schedule = _normalized_identity(bill.generation_schedule.value)
    if generation_schedule not in _GENERATION_SCHEDULE_ALIASES:
        raise UnsupportedBillError(
            "The MVP supports only the 3CE MBRETCH1 3Cchoice schedule for this bill."
        )


def validate_pge_3ce_bill(bill: BillExtraction, bundle: TariffBundle) -> None:
    """Require an exact supported PG&E/3CE identity and archived rate period."""

    validate_pge_3ce_identity(bill)
    if (
        bill.service_start.value < bundle.version.effective_start
        or bill.service_end.value > bundle.version.effective_end
    ):
        raise UnsupportedBillError(
            "This bill falls outside the archived E-TOU-C tariff period."
        )


def _quantity_rule(
    bill: BillExtraction,
    line_id: str,
    rule: RateRule,
    billed_line: ChargeLine,
    bundle: TariffBundle,
) -> AuditLine:
    if line_id == "pge_franchise_fee":
        quantity = bill.total_usage.value
    elif billed_line.quantity is not None:
        quantity = billed_line.quantity.value
    else:
        raise ValueError(f"Missing quantity for calculable line: {line_id}")

    expected = round_money(multiply_exact(quantity, rule.rate))
    billed = billed_line.billed_amount.value
    delta = round_money(subtract_exact(billed, expected))
    return AuditLine(
        id=line_id,
        label=billed_line.label,
        category="tariff",
        unit="USD",
        billed_amount=billed,
        expected_amount=expected,
        delta=delta,
        formula=f"{format_decimal_exact(quantity)} kWh × {_rate(rule.rate)}",
        inputs={
            "quantity_kwh": format_decimal_exact(quantity),
            "official_rate_usd_per_kwh": format_decimal_exact(rule.rate),
            "rounding": "nearest cent, decimal half-up",
        },
        source_page=billed_line.billed_amount.source_page,
        source_text=billed_line.billed_amount.source_text,
        citations=_citation(bundle, rule),
        status=_status(delta),
    )


def _percentage_rule(
    line_id: str,
    rule: RateRule,
    billed_line: ChargeLine,
    billed_by_id: dict[str, Decimal],
) -> AuditLine:
    if billed_line.rate is None:
        raise ValueError(f"Missing printed rate for percentage line: {line_id}")
    printed_rate = billed_line.rate.value
    base = sum_exact(tuple(billed_by_id[item] for item in rule.line_ids))
    expected = round_money(multiply_exact(base, printed_rate))
    billed = billed_line.billed_amount.value
    delta = round_money(subtract_exact(billed, expected))
    return AuditLine(
        id=line_id,
        label=billed_line.label,
        category="tariff",
        unit="USD",
        billed_amount=billed,
        expected_amount=expected,
        delta=delta,
        formula=(
            f"{_currency(base)} taxable generation × "
            f"{format_decimal_exact(multiply_exact(printed_rate, Decimal('100')))}%"
        ),
        inputs={
            "taxable_generation_usd": format_decimal_exact(base),
            "printed_tax_rate": format_decimal_exact(printed_rate),
            "rounding": "nearest cent, decimal half-up",
        },
        source_page=billed_line.billed_amount.source_page,
        source_text=billed_line.billed_amount.source_text,
        citations=(),
        status=_status(delta),
        limitation=(
            "WattProof checked arithmetic using the percentage rate and base "
            "amounts printed on this statement; no independently archived source "
            "establishes that rate as the governing tariff."
        ),
    )


def _tariff_lines(
    bill: BillExtraction, bundle: TariffBundle
) -> tuple[AuditLine, ...]:
    results: list[AuditLine] = []
    billed_by_id = {
        billed_line.id: billed_line.billed_amount.value
        for billed_line in bill.charges
    }
    for billed_line in bill.charges:
        rule = bundle.rules.get(billed_line.id)
        if rule is None:
            results.append(
                AuditLine(
                    id=billed_line.id,
                    label=billed_line.label,
                    category="tariff",
                    unit="USD",
                    billed_amount=billed_line.billed_amount.value,
                    expected_amount=None,
                    delta=None,
                    formula="Not recomputed",
                    inputs={
                        "printed_amount_usd": format_decimal_exact(
                            billed_line.billed_amount.value
                        )
                    },
                    source_page=billed_line.billed_amount.source_page,
                    source_text=billed_line.billed_amount.source_text,
                    citations=(),
                    status="cannot_verify",
                    limitation=bundle.limitations.get(
                        billed_line.id,
                        "No deterministic rule is available for this charge.",
                    ),
                )
            )
            continue

        if rule.kind == "quantity_times_rate":
            result = _quantity_rule(
                bill, billed_line.id, rule, billed_line, bundle
            )
        elif rule.kind == "percent_of_lines":
            result = _percentage_rule(
                billed_line.id, rule, billed_line, billed_by_id
            )
        else:
            raise ValueError(f"Unknown rate rule kind: {rule.kind}")
        results.append(result)
    return tuple(results)


def _reconciliation_line(
    *,
    line_id: str,
    label: str,
    billed: Decimal,
    expected: Decimal,
    source_page: int,
    source_text: str,
    formula: str,
    inputs: dict[str, str],
) -> AuditLine:
    delta = round_money(subtract_exact(billed, expected))
    return AuditLine(
        id=line_id,
        label=label,
        category="reconciliation",
        unit="USD",
        billed_amount=billed,
        expected_amount=expected,
        delta=delta,
        formula=formula,
        inputs=inputs,
        source_page=source_page,
        source_text=source_text,
        status=_status(delta),
    )


def _reconciliation_lines(bill: BillExtraction) -> tuple[AuditLine, ...]:
    delivery_lines = [
        line.billed_amount.value
        for line in bill.charges
        if line.section == "pge_delivery"
    ]
    generation_lines = [
        line.billed_amount.value
        for line in bill.charges
        if line.section == "cca_generation"
    ]
    delivery_sum = sum_exact(tuple(delivery_lines))
    generation_sum = sum_exact(tuple(generation_lines))
    current_sum = add_exact(
        bill.delivery_subtotal.value, bill.generation_subtotal.value
    )
    due_sum = add_exact(bill.current_charges.value, bill.outstanding_balance.value)

    checks = [
        _reconciliation_line(
            line_id="delivery_subtotal",
            label="PG&E delivery lines sum to subtotal",
            billed=bill.delivery_subtotal.value,
            expected=delivery_sum,
            source_page=bill.delivery_subtotal.source_page,
            source_text=bill.delivery_subtotal.source_text,
            formula="sum of printed PG&E delivery lines",
            inputs={"line_sum_usd": format_decimal_exact(delivery_sum)},
        ),
        _reconciliation_line(
            line_id="generation_subtotal",
            label="3CE generation lines sum to subtotal",
            billed=bill.generation_subtotal.value,
            expected=generation_sum,
            source_page=bill.generation_subtotal.source_page,
            source_text=bill.generation_subtotal.source_text,
            formula="sum of printed 3CE generation lines",
            inputs={"line_sum_usd": format_decimal_exact(generation_sum)},
        ),
        _reconciliation_line(
            line_id="current_charges",
            label="Section subtotals sum to current charges",
            billed=bill.current_charges.value,
            expected=current_sum,
            source_page=bill.current_charges.source_page,
            source_text=bill.current_charges.source_text,
            formula="PG&E subtotal + 3CE subtotal",
            inputs={
                "pge_subtotal_usd": format_decimal_exact(
                    bill.delivery_subtotal.value
                ),
                "3ce_subtotal_usd": format_decimal_exact(
                    bill.generation_subtotal.value
                ),
            },
        ),
        _reconciliation_line(
            line_id="amount_due",
            label="Current charges and balance sum to amount due",
            billed=bill.amount_due.value,
            expected=due_sum,
            source_page=bill.amount_due.source_page,
            source_text=bill.amount_due.source_text,
            formula="current charges + outstanding balance",
            inputs={
                "current_charges_usd": format_decimal_exact(
                    bill.current_charges.value
                ),
                "outstanding_balance_usd": format_decimal_exact(
                    bill.outstanding_balance.value
                ),
            },
        ),
    ]
    checks.append(
        AuditLine(
            id="meter_delta",
            label="Meter reads agree with printed usage",
            category="reconciliation",
            unit="kWh",
            billed_amount=bill.total_usage.value,
            expected_amount=None,
            delta=None,
            formula="current meter read − prior meter read",
            inputs={
                "printed_usage_kwh": format_decimal_exact(bill.total_usage.value)
            },
            source_page=bill.total_usage.source_page,
            source_text=bill.total_usage.source_text,
            status="cannot_verify",
            limitation=(
                "The public sample omits current/prior reads and "
                "actual-versus-estimated status."
            ),
        )
    )
    return tuple(checks)


def _comparison() -> PlanComparison:
    return PlanComparison(
        status="cannot_verify",
        headline="A defensible plan comparison needs interval data",
        explanation=(
            "This bill reports only 4-9 p.m. peak and aggregate off-peak usage. "
            "It cannot reconstruct PG&E plans with different hour windows, so "
            "WattProof will not invent a savings estimate."
        ),
        required_data=(
            "hourly or 15-minute Green Button interval usage",
            "a representative date range covering seasonal use",
        ),
    )


def _review_request(
    bill: BillExtraction, lines: tuple[AuditLine, ...]
) -> ReviewRequest:
    discrepancies = [
        line
        for line in lines
        if line.category == "tariff" and line.status == "discrepancy"
    ]
    if discrepancies:
        line = discrepancies[0]
        synthetic_prefix = (
            "This is a synthetic demo request; no real customer bill contained this error.\n\n"
            if bill.fixture_kind == "synthetic"
            else ""
        )
        if line.citations:
            source_list = "\n".join(
                f"- {citation.label}: {citation.source_url}"
                for citation in line.citations
            )
            calculation_basis = (
                "Applying the published rate to the printed usage gives "
                f"{_currency(line.expected_amount or Decimal('0'))}, a difference of "
                f"{_currency(abs_exact(line.delta or Decimal('0')))}.\n\n"
                f"Calculation: {line.formula}.\n"
                f"Rate sources:\n{source_list}\n\n"
            )
        else:
            calculation_basis = (
                "Recomputing the printed rate and printed base amounts gives "
                f"{_currency(line.expected_amount or Decimal('0'))}, a difference of "
                f"{_currency(abs_exact(line.delta or Decimal('0')))}.\n\n"
                f"Calculation: {line.formula}.\n"
                f"Limit: {line.limitation}\n\n"
            )
        body = (
            f"Hello,\n\n{synthetic_prefix}Please review the {line.label} on "
            f"the statement dated {bill.statement_date.value.isoformat()}. The statement "
            f"shows {_currency(line.billed_amount)}. {calculation_basis}"
            "Please confirm the quantity and rate used and explain or correct the charge "
            "if appropriate. I will verify my account details before sending. Thank you."
        )
        return ReviewRequest(
            subject=f"Request to review {line.label}",
            body=body,
            grounded_audit_line_ids=(line.id,),
        )

    reconciliation_discrepancies = [
        line
        for line in lines
        if line.category == "reconciliation" and line.status == "discrepancy"
    ]
    if reconciliation_discrepancies:
        line = reconciliation_discrepancies[0]
        body = (
            f"Hello,\n\nPlease review the printed totals on my "
            f"{bill.delivery_provider.value} statement dated "
            f"{bill.statement_date.value.isoformat()}. One printed-total check does not "
            f"reconcile. The statement shows {_currency(line.billed_amount)} for "
            f"“{line.label},” while combining the other printed amounts gives "
            f"{_currency(line.expected_amount or Decimal('0'))}, a difference of "
            f"{_currency(abs_exact(line.delta or Decimal('0')))}.\n\n"
            f"Calculation using printed amounts: {line.formula}.\n\n"
            "Please confirm the total and correct it if appropriate. I will verify my "
            "account details before sending. Thank you."
        )
        return ReviewRequest(
            subject="Request to review printed electricity bill totals",
            body=body,
            grounded_audit_line_ids=(line.id,),
        )

    verified_rate_lines = (
        "pge_peak_energy",
        "pge_off_peak_energy",
        "pge_baseline_credit",
    )
    unsupported = tuple(
        line.id for line in lines if line.category == "tariff" and line.status == "cannot_verify"
    )
    body = (
        "Hello,\n\nPlease confirm the rate components applied to my E-TOU-C "
        f"statement dated {bill.statement_date.value.isoformat()}. The energy and baseline "
        "lines WattProof could recompute agree with the published rates, but the archived "
        "sources are insufficient to independently verify the generation credit, PCIA, "
        "and certain taxes. Please provide the applicable component rates or calculation "
        "detail.\n\nI will verify my account details before sending. Thank you."
    )
    return ReviewRequest(
        subject="Request for electricity charge calculation detail",
        body=body,
        grounded_audit_line_ids=verified_rate_lines + unsupported,
    )


def audit_bill_with_bundle(
    bill: BillExtraction,
    bundle: TariffBundle,
) -> AuditResult:
    """Audit with one caller-supplied tariff snapshot."""

    validate_pge_3ce_bill(bill, bundle)
    tariff_lines = _tariff_lines(bill, bundle)
    reconciliation_lines = _reconciliation_lines(bill)
    lines = tariff_lines + reconciliation_lines

    tariff_discrepancies = [
        line.delta
        for line in tariff_lines
        if line.status == "discrepancy" and line.delta is not None
    ]
    reconciliation_discrepancies = [
        line for line in reconciliation_lines if line.status == "discrepancy"
    ]
    discrepancy_total = round_money(
        sum_exact(tuple(abs_exact(delta) for delta in tariff_discrepancies))
    )
    if tariff_discrepancies:
        verdict = "possible_discrepancy"
        headline = f"Possible {_currency(discrepancy_total)} source-supported discrepancy"
    elif reconciliation_discrepancies:
        verdict = "needs_review"
        headline = "Printed bill totals need review"
    else:
        verdict = "reconciled"
        headline = "Reconciled where the archived sources support a calculation"

    return AuditResult(
        schema_version="1.0",
        fixture_kind=bill.fixture_kind,
        verdict=verdict,
        headline=headline,
        discrepancy_total=discrepancy_total,
        tariff=bundle.version,
        lines=lines,
        comparison=_comparison(),
        review_request=_review_request(bill, lines),
    )


def audit_bill(
    bill: BillExtraction, *, verify_sources: bool = True
) -> AuditResult:
    bundle = load_tariff_bundle(verify_sources=verify_sources)
    return audit_bill_with_bundle(bill, bundle)
