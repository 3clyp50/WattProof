from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .utility_models import (
    AuditStatusV2,
    EvidenceRef,
    ProviderReviewRequest,
    ServiceSection,
    UtilityAuditLine,
    UtilityAuditResult,
    UtilityCharge,
    UtilityDocument,
)

CENT = Decimal("0.01")
MONEY_TOLERANCE = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def compatible_rate(quantity_unit: str, rate_unit: str, currency: str) -> bool:
    return rate_unit == f"{currency}/{quantity_unit}"


def _money_status(delta: Decimal) -> AuditStatusV2:
    return "verified" if abs(delta) <= MONEY_TOLERANCE else "discrepancy"


def _money_result(billed: Decimal, expected: Decimal) -> tuple[Decimal, AuditStatusV2]:
    delta = billed - expected
    return delta, _money_status(delta)


def _quantity_charge_line(
    charge: UtilityCharge,
    section: ServiceSection,
    currency: str,
) -> UtilityAuditLine:
    quantity = charge.quantity
    rate = charge.rate
    if quantity is None or rate is None:
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula="Cannot recompute: printed quantity or rate is unavailable",
            inputs={"printed_amount": f"{charge.amount.value} {currency}"},
            evidence=(charge.amount.evidence,),
            status="cannot_verify",
            limitation="The declared calculation is missing a printed quantity or rate.",
        )

    if not compatible_rate(quantity.unit, rate.unit, currency):
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula=(
                f"Cannot multiply {quantity.value} {quantity.unit} by "
                f"{rate.value} {rate.unit} as {currency}"
            ),
            inputs={
                "quantity": f"{quantity.value} {quantity.unit}",
                "rate": f"{rate.value} {rate.unit}",
                "required_rate_unit": f"{currency}/{quantity.unit}",
                "printed_amount": f"{charge.amount.value} {currency}",
            },
            evidence=(quantity.evidence, rate.evidence, charge.amount.evidence),
            status="needs_review",
            limitation="The printed quantity and rate units are incompatible.",
        )

    expected = round_money(quantity.value * rate.value)
    delta, status = _money_result(charge.amount.value, expected)
    return UtilityAuditLine(
        id=f"charge::{charge.id}",
        section_id=section.id,
        label=charge.label,
        scope="printed_math",
        unit=currency,
        billed_amount=charge.amount.value,
        expected_amount=expected,
        delta=delta,
        formula=(
            f"{quantity.value} {quantity.unit} × {rate.value} {rate.unit} "
            f"= {expected} {currency}"
        ),
        inputs={
            "quantity": f"{quantity.value} {quantity.unit}",
            "rate": f"{rate.value} {rate.unit}",
            "printed_amount": f"{charge.amount.value} {currency}",
            "rounding": "nearest 0.01, decimal half-up",
        },
        evidence=(quantity.evidence, rate.evidence, charge.amount.evidence),
        status=status,
    )


def _percentage_charge_line(
    charge: UtilityCharge,
    section: ServiceSection,
    currency: str,
    charges_by_id: dict[str, UtilityCharge],
) -> UtilityAuditLine:
    rate = charge.rate
    calculation = charge.calculation
    if rate is None or calculation is None:
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula="Cannot recompute: printed percentage rate is unavailable",
            inputs={"printed_amount": f"{charge.amount.value} {currency}"},
            evidence=(charge.amount.evidence,),
            status="cannot_verify",
            limitation="The declared percentage calculation is missing its printed rate.",
        )

    if not calculation.charge_ids:
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula="Cannot recompute: no printed percentage base is declared",
            inputs={
                "rate": f"{rate.value} {rate.unit}",
                "printed_amount": f"{charge.amount.value} {currency}",
            },
            evidence=(rate.evidence, charge.amount.evidence),
            status="cannot_verify",
            limitation="The percentage calculation has no declared printed base charges.",
        )

    if (
        len(calculation.charge_ids) != len(set(calculation.charge_ids))
        or charge.id in calculation.charge_ids
    ):
        available_ids = tuple(dict.fromkeys(calculation.charge_ids))
        available = tuple(
            charges_by_id[charge_id]
            for charge_id in available_ids
            if charge_id in charges_by_id
        )
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula="Cannot recompute: the declared percentage base is invalid",
            inputs={
                "rate": f"{rate.value} {rate.unit}",
                "referenced_charge_ids": ", ".join(calculation.charge_ids),
                "printed_amount": f"{charge.amount.value} {currency}",
            },
            evidence=(
                rate.evidence,
                *(item.amount.evidence for item in available),
                charge.amount.evidence,
            ),
            status="needs_review",
            limitation=(
                "Percentage base charge IDs must be unique and cannot reference "
                "the calculated charge itself."
            ),
        )

    missing_ids = tuple(
        charge_id
        for charge_id in calculation.charge_ids
        if charge_id not in charges_by_id
    )
    referenced = tuple(
        charges_by_id[charge_id]
        for charge_id in calculation.charge_ids
        if charge_id in charges_by_id
    )
    if missing_ids:
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula="Cannot recompute: a referenced printed charge is unavailable",
            inputs={
                "rate": f"{rate.value} {rate.unit}",
                "referenced_charge_ids": ", ".join(calculation.charge_ids),
                "missing_charge_ids": ", ".join(missing_ids),
                "printed_amount": f"{charge.amount.value} {currency}",
            },
            evidence=(
                rate.evidence,
                *(item.amount.evidence for item in referenced),
                charge.amount.evidence,
            ),
            status="cannot_verify",
            limitation="A declared percentage base charge is not available in the document.",
        )

    if rate.unit != "fraction":
        return UtilityAuditLine(
            id=f"charge::{charge.id}",
            section_id=section.id,
            label=charge.label,
            scope="printed_math",
            unit=currency,
            billed_amount=charge.amount.value,
            expected_amount=None,
            delta=None,
            formula=(
                f"Cannot apply {rate.value} {rate.unit} to the declared printed charges"
            ),
            inputs={
                "rate": f"{rate.value} {rate.unit}",
                "required_rate_unit": "fraction",
                **{
                    f"charge::{item.id}": f"{item.amount.value} {currency}"
                    for item in referenced
                },
                "printed_amount": f"{charge.amount.value} {currency}",
            },
            evidence=(
                rate.evidence,
                *(item.amount.evidence for item in referenced),
                charge.amount.evidence,
            ),
            status="needs_review",
            limitation="The printed percentage rate unit must be exactly fraction.",
        )

    printed_base = sum((item.amount.value for item in referenced), Decimal("0"))
    expected = round_money(rate.value * printed_base)
    delta, status = _money_result(charge.amount.value, expected)
    printed_terms = " + ".join(
        f"{item.amount.value} {currency}" for item in referenced
    )
    inputs = {
        "rate": f"{rate.value} {rate.unit}",
        **{
            f"charge::{item.id}": f"{item.amount.value} {currency}"
            for item in referenced
        },
        "printed_amount": f"{charge.amount.value} {currency}",
        "rounding": "nearest 0.01, decimal half-up",
    }
    return UtilityAuditLine(
        id=f"charge::{charge.id}",
        section_id=section.id,
        label=charge.label,
        scope="printed_math",
        unit=currency,
        billed_amount=charge.amount.value,
        expected_amount=expected,
        delta=delta,
        formula=(
            f"{rate.value} × ({printed_terms}) = {expected} {currency}"
        ),
        inputs=inputs,
        evidence=(
            rate.evidence,
            *(item.amount.evidence for item in referenced),
            charge.amount.evidence,
        ),
        status=status,
    )


def _fixed_charge_line(
    charge: UtilityCharge,
    section: ServiceSection,
    currency: str,
) -> UtilityAuditLine:
    return UtilityAuditLine(
        id=f"charge::{charge.id}",
        section_id=section.id,
        label=charge.label,
        scope="printed_math",
        unit=currency,
        billed_amount=charge.amount.value,
        expected_amount=None,
        delta=None,
        formula=f"Printed fixed amount: {charge.amount.value} {currency}",
        inputs={"printed_amount": f"{charge.amount.value} {currency}"},
        evidence=(charge.amount.evidence,),
        status="cannot_verify",
        limitation=(
            "This is a printed fixed amount without independent printed operands."
        ),
    )


def _charge_line(
    charge: UtilityCharge,
    section: ServiceSection,
    currency: str,
    charges_by_id: dict[str, UtilityCharge],
) -> UtilityAuditLine:
    calculation = charge.calculation
    if calculation is None:
        return _fixed_charge_line(charge, section, currency)
    if calculation.kind == "quantity_times_rate":
        return _quantity_charge_line(charge, section, currency)
    return _percentage_charge_line(charge, section, currency, charges_by_id)


def _printed_quantum(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("printed measurement must be a finite Decimal")
    return Decimal("1").scaleb(exponent)


def _meter_line(section: ServiceSection) -> UtilityAuditLine | None:
    meter = section.meter
    if meter is None:
        return None
    if not (
        meter.previous.unit == meter.current.unit == meter.usage.unit
    ):
        return UtilityAuditLine(
            id=f"meter::{section.id}",
            section_id=section.id,
            label=f"{section.provider.value} meter usage",
            scope="printed_math",
            unit=meter.usage.unit,
            billed_amount=meter.usage.value,
            expected_amount=None,
            delta=None,
            formula="Cannot subtract meter reads with incompatible printed units",
            inputs={
                "current": f"{meter.current.value} {meter.current.unit}",
                "previous": f"{meter.previous.value} {meter.previous.unit}",
                "printed_usage": f"{meter.usage.value} {meter.usage.unit}",
            },
            evidence=(
                meter.current.evidence,
                meter.previous.evidence,
                meter.usage.evidence,
            ),
            status="needs_review",
            limitation="Previous, current, and usage meter units must match exactly.",
        )
    quantum = _printed_quantum(meter.usage.value)
    expected = (meter.current.value - meter.previous.value).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    delta = (meter.usage.value - expected).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    return UtilityAuditLine(
        id=f"meter::{section.id}",
        section_id=section.id,
        label=f"{section.provider.value} meter usage",
        scope="printed_math",
        unit=meter.usage.unit,
        billed_amount=meter.usage.value,
        expected_amount=expected,
        delta=delta,
        formula=(
            f"{meter.current.value} {meter.current.unit} − "
            f"{meter.previous.value} {meter.previous.unit} "
            f"= {expected} {meter.usage.unit}"
        ),
        inputs={
            "current": f"{meter.current.value} {meter.current.unit}",
            "previous": f"{meter.previous.value} {meter.previous.unit}",
            "printed_usage": f"{meter.usage.value} {meter.usage.unit}",
            "precision": str(quantum),
        },
        evidence=(
            meter.current.evidence,
            meter.previous.evidence,
            meter.usage.evidence,
        ),
        status="verified" if meter.usage.value == expected else "discrepancy",
    )


def _conversion_lines(section: ServiceSection) -> tuple[UtilityAuditLine, ...]:
    lines: list[UtilityAuditLine] = []
    for conversion in section.conversions:
        required_factor_unit = (
            f"{conversion.result.unit}/{conversion.source.unit}"
        )
        if conversion.factor.unit != required_factor_unit:
            lines.append(
                UtilityAuditLine(
                    id=f"conversion::{section.id}::{conversion.id}",
                    section_id=section.id,
                    label=conversion.label,
                    scope="printed_math",
                    unit=conversion.result.unit,
                    billed_amount=conversion.result.value,
                    expected_amount=None,
                    delta=None,
                    formula="Cannot convert using incompatible printed units",
                    inputs={
                        "source": (
                            f"{conversion.source.value} {conversion.source.unit}"
                        ),
                        "factor": (
                            f"{conversion.factor.value} {conversion.factor.unit}"
                        ),
                        "required_factor_unit": required_factor_unit,
                        "printed_result": (
                            f"{conversion.result.value} {conversion.result.unit}"
                        ),
                    },
                    evidence=(
                        conversion.source.evidence,
                        conversion.factor.evidence,
                        conversion.result.evidence,
                    ),
                    status="needs_review",
                    limitation=(
                        "The conversion factor unit must exactly match result/source."
                    ),
                )
            )
            continue
        quantum = _printed_quantum(conversion.result.value)
        expected = (conversion.source.value * conversion.factor.value).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        delta = (conversion.result.value - expected).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        lines.append(
            UtilityAuditLine(
                id=f"conversion::{section.id}::{conversion.id}",
                section_id=section.id,
                label=conversion.label,
                scope="printed_math",
                unit=conversion.result.unit,
                billed_amount=conversion.result.value,
                expected_amount=expected,
                delta=delta,
                formula=(
                    f"{conversion.source.value} {conversion.source.unit} × "
                    f"{conversion.factor.value} {conversion.factor.unit} "
                    f"= {expected} {conversion.result.unit}"
                ),
                inputs={
                    "source": (
                        f"{conversion.source.value} {conversion.source.unit}"
                    ),
                    "factor": (
                        f"{conversion.factor.value} {conversion.factor.unit}"
                    ),
                    "printed_result": (
                        f"{conversion.result.value} {conversion.result.unit}"
                    ),
                    "precision": str(quantum),
                },
                evidence=(
                    conversion.source.evidence,
                    conversion.factor.evidence,
                    conversion.result.evidence,
                ),
                status=(
                    "verified"
                    if conversion.result.value == expected
                    else "discrepancy"
                ),
            )
        )
    return tuple(lines)


def _subtotal_line(
    section: ServiceSection,
    currency: str,
    charge_lines: tuple[UtilityAuditLine, ...],
) -> UtilityAuditLine:
    expected = sum(
        (charge.amount.value for charge in section.charges), Decimal("0")
    )
    delta, status = _money_result(section.subtotal.value, expected)
    root_cause_id = None
    if status == "discrepancy":
        root_cause_id = next(
            (line.id for line in charge_lines if line.status == "discrepancy"),
            None,
        )
    return UtilityAuditLine(
        id=f"subtotal::{section.id}",
        section_id=section.id,
        label=f"{section.provider.value} section subtotal",
        scope="statement_reconciliation",
        unit=currency,
        billed_amount=section.subtotal.value,
        expected_amount=expected,
        delta=delta,
        formula=" + ".join(
            f"{charge.amount.value} {currency}" for charge in section.charges
        )
        + f" = {expected} {currency}",
        inputs={
            f"charge::{charge.id}": f"{charge.amount.value} {currency}"
            for charge in section.charges
        },
        evidence=(
            *(charge.amount.evidence for charge in section.charges),
            section.subtotal.evidence,
        ),
        status=status,
        root_cause_id=root_cause_id,
    )


def _current_charges_line(
    document: UtilityDocument,
    subtotal_lines: tuple[UtilityAuditLine, ...],
) -> UtilityAuditLine:
    expected = sum(
        (section.subtotal.value for section in document.sections), Decimal("0")
    )
    delta, status = _money_result(document.current_charges.value, expected)
    root_cause_id = None
    if status == "discrepancy":
        upstream = next(
            (line for line in subtotal_lines if line.status == "discrepancy"),
            None,
        )
        if upstream is not None:
            root_cause_id = upstream.root_cause_id or upstream.id
    return UtilityAuditLine(
        id="statement::current_charges",
        section_id=None,
        label="Current charges",
        scope="statement_reconciliation",
        unit=document.currency,
        billed_amount=document.current_charges.value,
        expected_amount=expected,
        delta=delta,
        formula=" + ".join(
            f"{section.subtotal.value} {document.currency}"
            for section in document.sections
        )
        + f" = {expected} {document.currency}",
        inputs={
            f"subtotal::{section.id}": (
                f"{section.subtotal.value} {document.currency}"
            )
            for section in document.sections
        },
        evidence=(
            *(section.subtotal.evidence for section in document.sections),
            document.current_charges.evidence,
        ),
        status=status,
        root_cause_id=root_cause_id,
    )


def _amount_due_line(
    document: UtilityDocument,
    current_charges_line: UtilityAuditLine,
) -> UtilityAuditLine:
    expected_unrounded = document.current_charges.value
    operands: list[EvidenceRef] = [document.current_charges.evidence]
    inputs = {
        "current_charges": f"{document.current_charges.value} {document.currency}"
    }
    formula = f"{document.current_charges.value} {document.currency}"
    if document.outstanding_balance is not None:
        expected_unrounded += document.outstanding_balance.value
        operands.append(document.outstanding_balance.evidence)
        inputs["outstanding_balance"] = (
            f"{document.outstanding_balance.value} {document.currency}"
        )
        formula += (
            f" + {document.outstanding_balance.value} {document.currency}"
        )
    expected = expected_unrounded
    delta, status = _money_result(document.amount_due.value, expected)
    root_cause_id = None
    if status == "discrepancy" and current_charges_line.status == "discrepancy":
        root_cause_id = (
            current_charges_line.root_cause_id or current_charges_line.id
        )
    return UtilityAuditLine(
        id="statement::amount_due",
        section_id=None,
        label="Amount due",
        scope="statement_reconciliation",
        unit=document.currency,
        billed_amount=document.amount_due.value,
        expected_amount=expected,
        delta=delta,
        formula=formula + f" = {expected} {document.currency}",
        inputs=inputs,
        evidence=(*operands, document.amount_due.evidence),
        status=status,
        root_cause_id=root_cause_id,
    )


def _display_amount(value: Decimal, unit: str, currency: str) -> str:
    if unit == currency and currency == "USD":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):.2f}"
    return f"{value} {unit}"


def _review_request(
    provider: str,
    section_ids: set[str],
    lines: tuple[UtilityAuditLine, ...],
    currency: str,
    include_statement_roots: bool,
) -> ProviderReviewRequest:
    grounded = tuple(
        line
        for line in lines
        if (
            line.section_id in section_ids
            or (include_statement_roots and line.section_id is None)
        )
        and line.root_cause_id is None
        and line.status in {"discrepancy", "needs_review"}
    )
    discrepancies = tuple(
        line for line in grounded if line.status == "discrepancy"
    )
    needs_review = tuple(line for line in grounded if line.status == "needs_review")
    if discrepancies:
        details = "\n".join(
            (
                f"- {line.label}: printed "
                f"{_display_amount(line.billed_amount, line.unit, currency)}, "
                f"recomputed {_display_amount(line.expected_amount, line.unit, currency)}, "
                f"difference {_display_amount(abs(line.delta), line.unit, currency)}."
            )
            for line in discrepancies
            if line.billed_amount is not None
            and line.expected_amount is not None
            and line.delta is not None
        )
        review_details = ""
        if needs_review:
            review_details = "\n" + "\n".join(
                f"- {line.label}: the declared printed operands need review."
                for line in needs_review
            )
        body = (
            "Hello,\n\nPlease review these printed statement relationships:\n"
            f"{details}{review_details}\n\nPlease confirm the printed operands and "
            "calculation detail. I will verify my account details before sending. "
            "Thank you."
        )
        subject = "Request to review printed utility statement calculations"
    elif needs_review:
        details = "\n".join(
            f"- {line.label}: the declared printed operands need review."
            for line in needs_review
        )
        body = (
            "Hello,\n\nPlease clarify these printed statement relationships:\n"
            f"{details}\n\nPlease provide the printed operands and calculation detail. "
            "I will verify my account details before sending. Thank you."
        )
        subject = "Request for printed utility calculation detail"
    else:
        body = (
            "Hello,\n\nThe printed math reconciled internally, while published rates "
            "remain independently unverified. Please provide the applicable rate "
            "schedule and calculation detail for review.\n\nI will verify my account "
            "details before sending. Thank you."
        )
        subject = "Request for utility charge calculation detail"
    return ProviderReviewRequest(
        provider=provider,
        subject=subject,
        body=body,
        grounded_audit_line_ids=tuple(line.id for line in grounded),
        requires_user_review=True,
    )


def reconcile_document(document: UtilityDocument) -> UtilityAuditResult:
    charges_by_id = {
        charge.id: charge
        for section in document.sections
        for charge in section.charges
    }
    lines: list[UtilityAuditLine] = []
    subtotal_lines: list[UtilityAuditLine] = []
    for section in document.sections:
        charge_lines = tuple(
            _charge_line(charge, section, document.currency, charges_by_id)
            for charge in section.charges
        )
        lines.extend(charge_lines)
        meter_line = _meter_line(section)
        if meter_line is not None:
            lines.append(meter_line)
        lines.extend(_conversion_lines(section))
        subtotal_line = _subtotal_line(section, document.currency, charge_lines)
        subtotal_lines.append(subtotal_line)
        lines.append(subtotal_line)
    current_charges_line = _current_charges_line(document, tuple(subtotal_lines))
    lines.append(current_charges_line)
    lines.append(_amount_due_line(document, current_charges_line))

    has_discrepancy = any(line.status == "discrepancy" for line in lines)
    has_needs_review = any(line.status == "needs_review" for line in lines)
    if has_discrepancy:
        verdict = "possible_discrepancy"
        headline = "Possible discrepancy found in printed statement math"
    elif has_needs_review:
        verdict = "needs_review"
        headline = "Printed statement math needs review"
    else:
        verdict = "reconciled"
        headline = "Printed statement math reconciles internally"

    verification_level = (
        "internally_reconciled"
        if any(line.expected_amount is not None for line in lines)
        else "evidence_extracted"
    )
    line_tuple = tuple(lines)
    discrepancy_total = sum(
        (
            abs(line.delta)
            for line in line_tuple
            if line.status == "discrepancy"
            and line.root_cause_id is None
            and line.delta is not None
            and line.unit == document.currency
            and not line.id.startswith(("meter::", "conversion::"))
        ),
        Decimal("0"),
    )
    provider_sections: dict[str, set[str]] = {}
    for section in document.sections:
        provider_sections.setdefault(section.provider.value, set()).add(section.id)
    return UtilityAuditResult(
        schema_version="2.0",
        fixture_kind=document.fixture_kind,
        verdict=verdict,
        verification_level=verification_level,
        headline=headline,
        discrepancy_total=discrepancy_total,
        currency=document.currency,
        lines=line_tuple,
        tariff=None,
        comparison=None,
        review_requests=tuple(
            _review_request(
                provider,
                section_ids,
                line_tuple,
                document.currency,
                include_statement_roots=len(provider_sections) == 1,
            )
            for provider, section_ids in provider_sections.items()
        ),
    )
