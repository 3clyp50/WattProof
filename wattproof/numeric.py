from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator

MAX_UTILITY_DECIMAL_CHARACTERS = 64
MAX_UTILITY_DECIMAL_DIGITS = 28
MIN_UTILITY_DECIMAL_EXPONENT = -18
MAX_UTILITY_DECIMAL_EXPONENT = 11
MAX_UTILITY_DECIMAL_ADJUSTED_EXPONENT = 11

_DECIMAL_SPELLING = re.compile(
    r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?"
)


def _validate_decimal_spelling(value: object) -> object:
    """Reject oversized or special string forms before Decimal construction."""

    if not isinstance(value, (str, bytes, bytearray)):
        return value
    if len(value) > MAX_UTILITY_DECIMAL_CHARACTERS:
        raise ValueError(
            "utility-bill decimal spelling is limited to "
            f"{MAX_UTILITY_DECIMAL_CHARACTERS} characters"
        )
    if isinstance(value, str):
        spelling = value
    else:
        try:
            spelling = bytes(value).decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(
                "utility-bill decimal must use an ASCII numeric spelling"
            ) from error
    if _DECIMAL_SPELLING.fullmatch(spelling) is None:
        raise ValueError(
            "utility-bill decimal must use a finite decimal or scientific numeric spelling"
        )
    return value


def validate_utility_decimal(value: Decimal) -> Decimal:
    """Bound statement numbers before any deterministic reconciliation arithmetic."""

    if not value.is_finite():
        raise ValueError("utility-bill decimal must be finite")

    decimal_tuple = value.as_tuple()
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        raise ValueError("utility-bill decimal must be finite")
    if len(decimal_tuple.digits) > MAX_UTILITY_DECIMAL_DIGITS:
        raise ValueError(
            "utility-bill decimal supports at most "
            f"{MAX_UTILITY_DECIMAL_DIGITS} significant digits"
        )
    if exponent < MIN_UTILITY_DECIMAL_EXPONENT:
        raise ValueError(
            "utility-bill decimal exponent must be at least "
            f"{MIN_UTILITY_DECIMAL_EXPONENT}"
        )
    if exponent > MAX_UTILITY_DECIMAL_EXPONENT:
        raise ValueError(
            "utility-bill decimal exponent must be at most "
            f"{MAX_UTILITY_DECIMAL_EXPONENT}"
        )
    if value != 0 and value.adjusted() > MAX_UTILITY_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError("utility-bill decimal magnitude must be less than 1e12")
    return value


UtilityDecimal = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal_spelling),
    AfterValidator(validate_utility_decimal),
]


def multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    """Multiply bounded operands without the process-wide Decimal precision rounding them."""

    precision = max(
        len(left.as_tuple().digits) + len(right.as_tuple().digits),
        1,
    )
    with localcontext() as context:
        context.prec = precision
        return left * right


def _operation_precision(values: tuple[Decimal, ...]) -> int:
    if any(not value.is_finite() for value in values):
        raise ValueError("reconciliation arithmetic requires finite Decimal values")
    if not values:
        return 1
    exponents: list[int] = []
    for value in values:
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise ValueError("reconciliation arithmetic requires finite Decimal values")
        exponents.append(exponent)
    integer_digits = max(
        max((value.adjusted() + 1 if value else 1) for value in values),
        1,
    )
    fractional_digits = max(-min(exponents), 0)
    carry_digits = len(str(len(values)))
    return max(
        integer_digits + fractional_digits + carry_digits,
        max(len(value.as_tuple().digits) for value in values) + carry_digits,
        1,
    )


def sum_exact(values: tuple[Decimal, ...]) -> Decimal:
    """Sum finite values without silently dropping their least-significant digits."""

    if not values:
        return Decimal("0")
    with localcontext() as context:
        context.prec = _operation_precision(values)
        return sum(values, Decimal("0"))


def add_exact(left: Decimal, right: Decimal) -> Decimal:
    return sum_exact((left, right))


def subtract_exact(left: Decimal, right: Decimal) -> Decimal:
    values = (left, right)
    with localcontext() as context:
        context.prec = _operation_precision(values)
        return left - right


def quantize_exact(value: Decimal, quantum: Decimal) -> Decimal:
    """Quantize a finite derived value with enough local precision for its domain."""

    if not value.is_finite() or not quantum.is_finite() or quantum == 0:
        raise ValueError("reconciliation arithmetic requires finite Decimal values")
    exponent = quantum.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("reconciliation quantum must be a finite Decimal")
    integer_digits = max(value.adjusted() + 1, 1) if value else 1
    fractional_digits = max(-exponent, 0)
    precision = max(
        len(value.as_tuple().digits),
        integer_digits + fractional_digits,
        1,
    )
    with localcontext() as context:
        context.prec = precision
        return value.quantize(quantum, rounding=ROUND_HALF_UP)
