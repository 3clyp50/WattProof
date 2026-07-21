from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .utility_models import (
    AuditStatusV2,
    EvidenceRef,
    FactBaseV2,
    FactStatus,
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


def _provenance_label(status: FactStatus | None) -> str:
    if status == "printed":
        return "printed"
    if status == "inferred":
        return "inferred extraction"
    if status == "user_corrected":
        return "user-corrected"
    return "reported"


def _provenance_annotation(fact: FactBaseV2) -> str:
    annotation = _provenance_label(fact.status)
    if fact.status == "user_corrected":
        annotation += f"; original extracted value: {fact.original_value}"
    return annotation


def _annotated_value(value: Decimal, unit: str, fact: FactBaseV2) -> str:
    annotation = _provenance_annotation(fact)
    return f"{value} {unit} [{annotation}]"


def _with_billed_provenance(
    line: UtilityAuditLine,
    fact: FactBaseV2,
) -> UtilityAuditLine:
    return line.model_copy(
        update={
            "billed_status": fact.status,
            "billed_original_value": fact.original_value,
        }
    )


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
            formula="Cannot recompute: a reported quantity or rate is unavailable",
            inputs={
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                )
            },
            evidence=(charge.amount.evidence,),
            status="cannot_verify",
            limitation="The declared calculation is missing a reported quantity or rate.",
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
                f"Cannot multiply {_annotated_value(quantity.value, quantity.unit, quantity)} "
                f"by {_annotated_value(rate.value, rate.unit, rate)} as {currency}"
            ),
            inputs={
                "quantity": _annotated_value(quantity.value, quantity.unit, quantity),
                "rate": _annotated_value(rate.value, rate.unit, rate),
                "required_rate_unit": f"{currency}/{quantity.unit}",
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                ),
            },
            evidence=(quantity.evidence, rate.evidence, charge.amount.evidence),
            status="needs_review",
            limitation="The reported quantity and rate units are incompatible.",
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
            f"{_annotated_value(quantity.value, quantity.unit, quantity)} × "
            f"{_annotated_value(rate.value, rate.unit, rate)} "
            f"= {expected} {currency} [recomputed]"
        ),
        inputs={
            "quantity": _annotated_value(quantity.value, quantity.unit, quantity),
            "rate": _annotated_value(rate.value, rate.unit, rate),
            "billed_amount": _annotated_value(
                charge.amount.value, currency, charge.amount
            ),
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
            formula="Cannot recompute: the reported percentage rate is unavailable",
            inputs={
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                )
            },
            evidence=(charge.amount.evidence,),
            status="cannot_verify",
            limitation="The declared percentage calculation is missing its reported rate.",
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
            formula="Cannot recompute: no percentage base is declared",
            inputs={
                "rate": _annotated_value(rate.value, rate.unit, rate),
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                ),
            },
            evidence=(rate.evidence, charge.amount.evidence),
            status="cannot_verify",
            limitation="The percentage calculation has no declared base charges.",
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
                "rate": _annotated_value(rate.value, rate.unit, rate),
                "referenced_charge_ids": ", ".join(calculation.charge_ids),
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                ),
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
            formula="Cannot recompute: a referenced charge is unavailable",
            inputs={
                "rate": _annotated_value(rate.value, rate.unit, rate),
                "referenced_charge_ids": ", ".join(calculation.charge_ids),
                "missing_charge_ids": ", ".join(missing_ids),
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                ),
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
                f"Cannot apply {_annotated_value(rate.value, rate.unit, rate)} "
                "to the declared charges"
            ),
            inputs={
                "rate": _annotated_value(rate.value, rate.unit, rate),
                "required_rate_unit": "fraction",
                **{
                    f"charge::{item.id}": _annotated_value(
                        item.amount.value, currency, item.amount
                    )
                    for item in referenced
                },
                "billed_amount": _annotated_value(
                    charge.amount.value, currency, charge.amount
                ),
            },
            evidence=(
                rate.evidence,
                *(item.amount.evidence for item in referenced),
                charge.amount.evidence,
            ),
            status="needs_review",
            limitation="The reported percentage rate unit must be exactly fraction.",
        )

    reported_base = sum((item.amount.value for item in referenced), Decimal("0"))
    expected = round_money(rate.value * reported_base)
    delta, status = _money_result(charge.amount.value, expected)
    base_terms = " + ".join(
        _annotated_value(item.amount.value, currency, item.amount)
        for item in referenced
    )
    inputs = {
        "rate": _annotated_value(rate.value, rate.unit, rate),
        **{
            f"charge::{item.id}": _annotated_value(
                item.amount.value, currency, item.amount
            )
            for item in referenced
        },
        "billed_amount": _annotated_value(
            charge.amount.value, currency, charge.amount
        ),
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
            f"{_annotated_value(rate.value, rate.unit, rate)} × ({base_terms}) "
            f"= {expected} {currency} [recomputed]"
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
        formula=(
            "Reported fixed amount: "
            f"{_annotated_value(charge.amount.value, currency, charge.amount)}"
        ),
        inputs={
            "billed_amount": _annotated_value(
                charge.amount.value, currency, charge.amount
            )
        },
        evidence=(charge.amount.evidence,),
        status="cannot_verify",
        limitation=(
            "This is a reported fixed amount without independent operands."
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
        line = _fixed_charge_line(charge, section, currency)
    elif calculation.kind == "quantity_times_rate":
        line = _quantity_charge_line(charge, section, currency)
    else:
        line = _percentage_charge_line(charge, section, currency, charges_by_id)
    return _with_billed_provenance(line, charge.amount)


def _printed_quantum(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("reported measurement must be a finite Decimal")
    return Decimal("1").scaleb(exponent)


def _meter_line(section: ServiceSection) -> UtilityAuditLine | None:
    meter = section.meter
    if meter is None:
        return None
    if not (
        meter.previous.unit == meter.current.unit == meter.usage.unit
    ):
        return _with_billed_provenance(
            UtilityAuditLine(
                id=f"meter::{section.id}",
                section_id=section.id,
                label=f"{section.provider.value} meter usage",
                scope="printed_math",
                unit=meter.usage.unit,
                billed_amount=meter.usage.value,
                expected_amount=None,
                delta=None,
                formula="Cannot subtract meter reads with incompatible reported units",
                inputs={
                    "current": _annotated_value(
                        meter.current.value, meter.current.unit, meter.current
                    ),
                    "previous": _annotated_value(
                        meter.previous.value, meter.previous.unit, meter.previous
                    ),
                    "reported_usage": _annotated_value(
                        meter.usage.value, meter.usage.unit, meter.usage
                    ),
                },
                evidence=(
                    meter.current.evidence,
                    meter.previous.evidence,
                    meter.usage.evidence,
                ),
                status="needs_review",
                limitation="Previous, current, and usage meter units must match exactly.",
            ),
            meter.usage,
        )
    quantum = _printed_quantum(meter.usage.value)
    expected = (meter.current.value - meter.previous.value).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    delta = (meter.usage.value - expected).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    return _with_billed_provenance(
        UtilityAuditLine(
            id=f"meter::{section.id}",
            section_id=section.id,
            label=f"{section.provider.value} meter usage",
            scope="printed_math",
            unit=meter.usage.unit,
            billed_amount=meter.usage.value,
            expected_amount=expected,
            delta=delta,
            formula=(
                f"{_annotated_value(meter.current.value, meter.current.unit, meter.current)} "
                f"− {_annotated_value(meter.previous.value, meter.previous.unit, meter.previous)} "
                f"= {expected} {meter.usage.unit} [recomputed]"
            ),
            inputs={
                "current": _annotated_value(
                    meter.current.value, meter.current.unit, meter.current
                ),
                "previous": _annotated_value(
                    meter.previous.value, meter.previous.unit, meter.previous
                ),
                "reported_usage": _annotated_value(
                    meter.usage.value, meter.usage.unit, meter.usage
                ),
                "precision": str(quantum),
            },
            evidence=(
                meter.current.evidence,
                meter.previous.evidence,
                meter.usage.evidence,
            ),
            status="verified" if meter.usage.value == expected else "discrepancy",
        ),
        meter.usage,
    )


def _conversion_lines(section: ServiceSection) -> tuple[UtilityAuditLine, ...]:
    lines: list[UtilityAuditLine] = []
    for conversion in section.conversions:
        required_factor_unit = (
            f"{conversion.result.unit}/{conversion.source.unit}"
        )
        if conversion.factor.unit != required_factor_unit:
            lines.append(
                _with_billed_provenance(
                    UtilityAuditLine(
                        id=f"conversion::{section.id}::{conversion.id}",
                        section_id=section.id,
                        label=conversion.label,
                        scope="printed_math",
                        unit=conversion.result.unit,
                        billed_amount=conversion.result.value,
                        expected_amount=None,
                        delta=None,
                        formula="Cannot convert using incompatible reported units",
                        inputs={
                            "source": _annotated_value(
                                conversion.source.value,
                                conversion.source.unit,
                                conversion.source,
                            ),
                            "factor": _annotated_value(
                                conversion.factor.value,
                                conversion.factor.unit,
                                conversion.factor,
                            ),
                            "required_factor_unit": required_factor_unit,
                            "reported_result": _annotated_value(
                                conversion.result.value,
                                conversion.result.unit,
                                conversion.result,
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
                    ),
                    conversion.result,
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
        source_trace = _annotated_value(
            conversion.source.value,
            conversion.source.unit,
            conversion.source,
        )
        factor_trace = _annotated_value(
            conversion.factor.value,
            conversion.factor.unit,
            conversion.factor,
        )
        lines.append(
            _with_billed_provenance(
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
                        f"{source_trace} × {factor_trace} "
                        f"= {expected} {conversion.result.unit} [recomputed]"
                    ),
                    inputs={
                        "source": _annotated_value(
                            conversion.source.value,
                            conversion.source.unit,
                            conversion.source,
                        ),
                        "factor": _annotated_value(
                            conversion.factor.value,
                            conversion.factor.unit,
                            conversion.factor,
                        ),
                        "reported_result": _annotated_value(
                            conversion.result.value,
                            conversion.result.unit,
                            conversion.result,
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
                ),
                conversion.result,
            )
        )
    return tuple(lines)


def _subtotal_line(
    section: ServiceSection,
    currency: str,
) -> UtilityAuditLine:
    expected = sum(
        (charge.amount.value for charge in section.charges), Decimal("0")
    )
    delta, status = _money_result(section.subtotal.value, expected)
    return _with_billed_provenance(
        UtilityAuditLine(
            id=f"subtotal::{section.id}",
            section_id=section.id,
            label=f"{section.provider.value} section subtotal",
            scope="statement_reconciliation",
            unit=currency,
            billed_amount=section.subtotal.value,
            expected_amount=expected,
            delta=delta,
            formula=" + ".join(
                _annotated_value(charge.amount.value, currency, charge.amount)
                for charge in section.charges
            )
            + f" = {expected} {currency} [recomputed]",
            inputs={
                f"charge::{charge.id}": _annotated_value(
                    charge.amount.value,
                    currency,
                    charge.amount,
                )
                for charge in section.charges
            },
            evidence=(
                *(charge.amount.evidence for charge in section.charges),
                section.subtotal.evidence,
            ),
            status=status,
        ),
        section.subtotal,
    )


def _current_charges_line(
    document: UtilityDocument,
) -> UtilityAuditLine:
    expected = sum(
        (section.subtotal.value for section in document.sections), Decimal("0")
    )
    delta, status = _money_result(document.current_charges.value, expected)
    return _with_billed_provenance(
        UtilityAuditLine(
            id="statement::current_charges",
            section_id=None,
            label="Current charges",
            scope="statement_reconciliation",
            unit=document.currency,
            billed_amount=document.current_charges.value,
            expected_amount=expected,
            delta=delta,
            formula=" + ".join(
                _annotated_value(
                    section.subtotal.value,
                    document.currency,
                    section.subtotal,
                )
                for section in document.sections
            )
            + f" = {expected} {document.currency} [recomputed]",
            inputs={
                f"subtotal::{section.id}": _annotated_value(
                    section.subtotal.value,
                    document.currency,
                    section.subtotal,
                )
                for section in document.sections
            },
            evidence=(
                *(section.subtotal.evidence for section in document.sections),
                document.current_charges.evidence,
            ),
            status=status,
        ),
        document.current_charges,
    )


def _amount_due_line(
    document: UtilityDocument,
) -> UtilityAuditLine:
    expected_unrounded = document.current_charges.value
    operands: list[EvidenceRef] = [document.current_charges.evidence]
    inputs = {
        "current_charges": f"{document.current_charges.value} {document.currency}",
        "current_charges_provenance": _provenance_annotation(
            document.current_charges
        ),
    }
    formula = _annotated_value(
        document.current_charges.value,
        document.currency,
        document.current_charges,
    )
    if document.outstanding_balance is not None:
        expected_unrounded += document.outstanding_balance.value
        operands.append(document.outstanding_balance.evidence)
        inputs["outstanding_balance"] = (
            f"{document.outstanding_balance.value} {document.currency}"
        )
        inputs["outstanding_balance_provenance"] = _provenance_annotation(
            document.outstanding_balance
        )
        formula += " + " + _annotated_value(
            document.outstanding_balance.value,
            document.currency,
            document.outstanding_balance,
        )
    expected = expected_unrounded
    delta, status = _money_result(document.amount_due.value, expected)
    return _with_billed_provenance(
        UtilityAuditLine(
            id="statement::amount_due",
            section_id=None,
            label="Amount due",
            scope="statement_reconciliation",
            unit=document.currency,
            billed_amount=document.amount_due.value,
            expected_amount=expected,
            delta=delta,
            formula=formula + f" = {expected} {document.currency} [recomputed]",
            inputs=inputs,
            evidence=(*operands, document.amount_due.evidence),
            status=status,
        ),
        document.amount_due,
    )


@dataclass(frozen=True)
class _ReconciledValue:
    amount: Decimal
    root_ids: frozenset[str]
    provable: bool


def _money_reconciles(billed: Decimal, expected: Decimal) -> bool:
    return abs(billed - expected) <= MONEY_TOLERANCE


def _corrected_charge_value(
    charge_id: str,
    charges_by_id: dict[str, UtilityCharge],
    charge_lines_by_id: dict[str, UtilityAuditLine],
    memo: dict[str, _ReconciledValue],
    visiting: set[str],
) -> _ReconciledValue:
    cached = memo.get(charge_id)
    if cached is not None:
        return cached

    charge = charges_by_id[charge_id]
    line = charge_lines_by_id[charge_id]
    calculation = charge.calculation
    if calculation is None:
        result = _ReconciledValue(charge.amount.value, frozenset(), True)
    elif line.expected_amount is None:
        result = _ReconciledValue(charge.amount.value, frozenset(), False)
    elif calculation.kind == "quantity_times_rate":
        if line.status == "discrepancy":
            result = _ReconciledValue(
                line.expected_amount,
                frozenset((line.id,)),
                True,
            )
        else:
            result = _ReconciledValue(charge.amount.value, frozenset(), True)
    elif charge_id in visiting:
        result = _ReconciledValue(charge.amount.value, frozenset(), False)
    else:
        rate = charge.rate
        if rate is None or rate.unit != "fraction":
            result = _ReconciledValue(charge.amount.value, frozenset(), False)
        else:
            visiting.add(charge_id)
            referenced_values: list[_ReconciledValue] = []
            try:
                for referenced_id in calculation.charge_ids:
                    if referenced_id not in charges_by_id:
                        result = _ReconciledValue(
                            charge.amount.value,
                            frozenset(),
                            False,
                        )
                        break
                    referenced_values.append(
                        _corrected_charge_value(
                            referenced_id,
                            charges_by_id,
                            charge_lines_by_id,
                            memo,
                            visiting,
                        )
                    )
                else:
                    root_ids = set().union(
                        *(value.root_ids for value in referenced_values)
                    )
                    if line.status == "discrepancy":
                        root_ids.add(line.id)
                    provable = all(value.provable for value in referenced_values)
                    if root_ids:
                        corrected_base = sum(
                            (value.amount for value in referenced_values),
                            Decimal("0"),
                        )
                        amount = round_money(rate.value * corrected_base)
                    else:
                        amount = charge.amount.value
                    result = _ReconciledValue(
                        amount,
                        frozenset(root_ids),
                        provable,
                    )
            finally:
                visiting.remove(charge_id)

    memo[charge_id] = result
    return result


def _reconcile_section_root(
    section: ServiceSection,
    subtotal_line: UtilityAuditLine,
    charges_by_id: dict[str, UtilityCharge],
    charge_lines_by_id: dict[str, UtilityAuditLine],
    memo: dict[str, _ReconciledValue],
) -> tuple[UtilityAuditLine, _ReconciledValue]:
    charge_values = tuple(
        _corrected_charge_value(
            charge.id,
            charges_by_id,
            charge_lines_by_id,
            memo,
            set(),
        )
        for charge in section.charges
    )
    corrected_subtotal = sum(
        (value.amount for value in charge_values), Decimal("0")
    )
    root_ids = set().union(*(value.root_ids for value in charge_values))
    provable = all(value.provable for value in charge_values)
    rooted_line = subtotal_line
    if subtotal_line.status == "discrepancy":
        if (
            provable
            and len(root_ids) == 1
            and _money_reconciles(section.subtotal.value, corrected_subtotal)
        ):
            rooted_line = subtotal_line.model_copy(
                update={"root_cause_id": next(iter(root_ids))}
            )
        else:
            root_ids.add(subtotal_line.id)
    return rooted_line, _ReconciledValue(
        corrected_subtotal,
        frozenset(root_ids),
        provable,
    )


def _reconcile_current_root(
    document: UtilityDocument,
    current_line: UtilityAuditLine,
    section_values: tuple[_ReconciledValue, ...],
) -> tuple[UtilityAuditLine, _ReconciledValue]:
    corrected_current = sum(
        (value.amount for value in section_values), Decimal("0")
    )
    root_ids = set().union(*(value.root_ids for value in section_values))
    provable = all(value.provable for value in section_values)
    rooted_line = current_line
    if current_line.status == "discrepancy":
        if (
            provable
            and len(root_ids) == 1
            and _money_reconciles(
                document.current_charges.value,
                corrected_current,
            )
        ):
            rooted_line = current_line.model_copy(
                update={"root_cause_id": next(iter(root_ids))}
            )
        else:
            root_ids.add(current_line.id)
    return rooted_line, _ReconciledValue(
        corrected_current,
        frozenset(root_ids),
        provable,
    )


def _reconcile_amount_due_root(
    document: UtilityDocument,
    amount_due_line: UtilityAuditLine,
    current_value: _ReconciledValue,
) -> UtilityAuditLine:
    corrected_due = current_value.amount
    if document.outstanding_balance is not None:
        corrected_due += document.outstanding_balance.value
    if (
        amount_due_line.status == "discrepancy"
        and current_value.provable
        and len(current_value.root_ids) == 1
        and _money_reconciles(document.amount_due.value, corrected_due)
    ):
        return amount_due_line.model_copy(
            update={"root_cause_id": next(iter(current_value.root_ids))}
        )
    return amount_due_line


def _display_amount(value: Decimal, unit: str, currency: str) -> str:
    if unit == currency and currency == "USD":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):.2f}"
    return f"{value} {unit}"


def _billed_phrase(line: UtilityAuditLine, currency: str) -> str:
    if line.billed_amount is None:
        return _provenance_label(line.billed_status)
    phrase = (
        f"{_provenance_label(line.billed_status)} "
        f"{_display_amount(line.billed_amount, line.unit, currency)}"
    )
    if line.billed_status == "user_corrected":
        phrase += f" (original extracted value: {line.billed_original_value})"
    return phrase


_NON_OPERAND_INPUT_KEYS = frozenset(
    {
        "billed_amount",
        "reported_usage",
        "reported_result",
        "rounding",
        "precision",
        "required_rate_unit",
        "required_factor_unit",
        "referenced_charge_ids",
        "missing_charge_ids",
    }
)


def _expected_operand_detail(line: UtilityAuditLine) -> str | None:
    operands: list[str] = []
    for key, value in line.inputs.items():
        if key in _NON_OPERAND_INPUT_KEYS or key.endswith("_provenance"):
            continue
        provenance = line.inputs.get(f"{key}_provenance")
        trace = f"{value} [{provenance}]" if provenance is not None else value
        operands.append(f"{key}={trace}")
    if not operands:
        return None
    return "Recomputed from " + "; ".join(operands)


def _discrepancy_detail(line: UtilityAuditLine, currency: str) -> str:
    if (
        line.billed_amount is None
        or line.expected_amount is None
        or line.delta is None
    ):
        return f"- {line.label}: a discrepancy was recorded without complete operands."
    detail = (
        f"- {line.label}: {_billed_phrase(line, currency)}, "
        f"recomputed {_display_amount(line.expected_amount, line.unit, currency)}, "
        f"difference {_display_amount(abs(line.delta), line.unit, currency)}."
    )
    operand_detail = _expected_operand_detail(line)
    if operand_detail is not None:
        detail += f"\n  {operand_detail}."
    return detail


def _review_request(
    provider: str,
    section_ids: set[str],
    lines: tuple[UtilityAuditLine, ...],
    currency: str,
    include_statement_roots: bool,
    has_unattributed_roots: bool,
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
            _discrepancy_detail(line, currency) for line in discrepancies
        )
        review_details = ""
        if needs_review:
            review_details = "\n" + "\n".join(
                f"- {line.label}: {_billed_phrase(line, currency)}; "
                "the declared operands need review."
                for line in needs_review
            )
        body = (
            "Hello,\n\nPlease review these statement relationships:\n"
            f"{details}{review_details}\n\nPlease confirm the reported operands and "
            "calculation detail. I will verify my account details before sending. "
            "Thank you."
        )
        subject = "Request to review utility statement calculations"
    elif needs_review:
        details = "\n".join(
            f"- {line.label}: {_billed_phrase(line, currency)}; "
            "the declared operands need review."
            for line in needs_review
        )
        body = (
            "Hello,\n\nPlease clarify these statement relationships:\n"
            f"{details}\n\nPlease provide the reported operands and calculation detail. "
            "I will verify my account details before sending. Thank you."
        )
        subject = "Request for utility calculation detail"
    elif has_unattributed_roots:
        body = (
            "Hello,\n\nThe provider-specific section math reconciled where "
            "deterministic operands are available. A separate consolidated statement "
            "issue is documented in a neutral review request and is not attributed "
            "to this provider. Published rates remain independently unverified.\n\n"
            "I will verify my account details before sending. Thank you."
        )
        subject = "Request for utility charge calculation detail"
    else:
        body = (
            "Hello,\n\nThe section math reconciled internally, while published rates "
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


def _consolidated_review_request(
    grounded: tuple[UtilityAuditLine, ...],
    currency: str,
) -> ProviderReviewRequest:
    discrepancies = tuple(
        line for line in grounded if line.status == "discrepancy"
    )
    details = "\n".join(
        _discrepancy_detail(line, currency)
        for line in discrepancies
    )
    needs_review = "\n".join(
        f"- {line.label}: {_billed_phrase(line, currency)}; "
        "the declared operands need review."
        for line in grounded
        if line.status == "needs_review"
    )
    issue_details = "\n".join(part for part in (details, needs_review) if part)
    return ProviderReviewRequest(
        provider="Consolidated statement",
        subject="Request to review consolidated statement calculations",
        body=(
            "Hello,\n\nPlease review the following cross-section statement "
            "relationship. It is not attributed to a particular provider, and this "
            "request does not allege provider error:\n"
            f"{issue_details}\n\nPlease confirm the statement roll-forward and "
            "calculation detail. I will verify my account details before sending. "
            "Thank you."
        ),
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
    charge_lines_by_id: dict[str, UtilityAuditLine] = {}
    subtotal_indexes: list[int] = []
    for section in document.sections:
        charge_lines = tuple(
            _charge_line(charge, section, document.currency, charges_by_id)
            for charge in section.charges
        )
        lines.extend(charge_lines)
        charge_lines_by_id.update(
            {
                charge.id: line
                for charge, line in zip(section.charges, charge_lines, strict=True)
            }
        )
        meter_line = _meter_line(section)
        if meter_line is not None:
            lines.append(meter_line)
        lines.extend(_conversion_lines(section))
        subtotal_indexes.append(len(lines))
        lines.append(_subtotal_line(section, document.currency))

    corrected_charge_values: dict[str, _ReconciledValue] = {}
    section_values: list[_ReconciledValue] = []
    for section, subtotal_index in zip(
        document.sections, subtotal_indexes, strict=True
    ):
        rooted_subtotal, section_value = _reconcile_section_root(
            section,
            lines[subtotal_index],
            charges_by_id,
            charge_lines_by_id,
            corrected_charge_values,
        )
        lines[subtotal_index] = rooted_subtotal
        section_values.append(section_value)

    current_charges_line, current_value = _reconcile_current_root(
        document,
        _current_charges_line(document),
        tuple(section_values),
    )
    lines.append(current_charges_line)
    lines.append(
        _reconcile_amount_due_root(
            document,
            _amount_due_line(document),
            current_value,
        )
    )

    has_discrepancy = any(line.status == "discrepancy" for line in lines)
    has_needs_review = any(line.status == "needs_review" for line in lines)
    if has_discrepancy:
        verdict = "possible_discrepancy"
        headline = "Possible discrepancy found in statement math"
    elif has_needs_review:
        verdict = "needs_review"
        headline = "Statement math needs review"
    else:
        verdict = "reconciled"
        headline = "Statement math reconciles internally"

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
        provider_identity = section.normalized_provider or section.provider.value
        provider_sections.setdefault(provider_identity, set()).add(section.id)
    unattributed_roots = tuple(
        line
        for line in line_tuple
        if len(provider_sections) > 1
        and line.section_id is None
        and line.root_cause_id is None
        and line.status in {"discrepancy", "needs_review"}
    )
    provider_requests = tuple(
        _review_request(
            provider,
            section_ids,
            line_tuple,
            document.currency,
            include_statement_roots=len(provider_sections) == 1,
            has_unattributed_roots=bool(unattributed_roots),
        )
        for provider, section_ids in provider_sections.items()
    )
    consolidated_requests = (
        (_consolidated_review_request(unattributed_roots, document.currency),)
        if unattributed_roots
        else ()
    )
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
        review_requests=provider_requests + consolidated_requests,
    )
