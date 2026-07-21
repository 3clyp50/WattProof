from __future__ import annotations

import re
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    ROUND_DOWN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator

MAX_UTILITY_DECIMAL_CHARACTERS = 64
MAX_UTILITY_DECIMAL_DIGITS = 28
MIN_UTILITY_DECIMAL_EXPONENT = -18
MAX_UTILITY_DECIMAL_EXPONENT = 11
MAX_UTILITY_DECIMAL_ADJUSTED_EXPONENT = 11
MAX_UTILITY_INTEGER_ABS = 999_999_999_999
MAX_UTILITY_INTEGER_CHARACTERS = 64
MONEY_QUANTUM = Decimal("0.01")

_DECIMAL_SPELLING = re.compile(
    r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?"
)


def abs_exact(value: Decimal) -> Decimal:
    """Return a Decimal magnitude without applying the ambient context."""

    return value.copy_abs()


def _canonical_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


def _arithmetic_context(precision: int) -> Context:
    """Create arithmetic settings independent from mutable process/thread context."""

    return Context(
        prec=max(precision, 1),
        rounding=ROUND_HALF_UP,
        Emin=MIN_EMIN,
        Emax=MAX_EMAX,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _validate_decimal_spelling(value: object) -> object:
    """Reject oversized or special string forms before Decimal construction."""

    if isinstance(value, bool):
        raise ValueError("utility-bill decimal must not be a boolean")
    if isinstance(value, float):
        raise ValueError(
            "utility-bill decimal cannot accept a binary float; use an exact "
            "Decimal, integer, or numeric spelling"
        )
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


def validate_confidence_decimal(value: Decimal) -> Decimal:
    if value < 0 or value > 1:
        raise ValueError("utility-bill confidence must be between 0 and 1")
    return value


ConfidenceDecimal = Annotated[
    UtilityDecimal,
    AfterValidator(validate_confidence_decimal),
]


def _exact_integer(value: Decimal) -> int:
    if not value.is_finite():
        raise ValueError("utility-bill integer must be finite")
    precision = max(len(value.as_tuple().digits), 1)
    with localcontext(_arithmetic_context(precision)) as context:
        integral = value.to_integral_value(rounding=ROUND_DOWN, context=context)
    if value != integral:
        raise ValueError("utility-bill integer must not contain a fractional value")
    if abs_exact(value) > MAX_UTILITY_INTEGER_ABS:
        raise ValueError(
            "utility-bill integer magnitude must be at most "
            f"{MAX_UTILITY_INTEGER_ABS}"
        )
    return int(value)


def _validate_integer_input(value: object) -> int:
    """Normalize only exact integer forms before Pydantic's integer coercion."""

    if isinstance(value, bool):
        raise ValueError("utility-bill integer must not be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError(
            "utility-bill integer cannot accept a binary float; use an exact "
            "integer, Decimal, or numeric spelling"
        )
    if isinstance(value, Decimal):
        return _exact_integer(value)
    if isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_UTILITY_INTEGER_CHARACTERS:
            raise ValueError(
                "utility-bill integer spelling is limited to "
                f"{MAX_UTILITY_INTEGER_CHARACTERS} characters"
            )
        if isinstance(value, str):
            spelling = value
        else:
            try:
                spelling = bytes(value).decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "utility-bill integer must use an ASCII numeric spelling"
                ) from error
        if _DECIMAL_SPELLING.fullmatch(spelling) is None:
            raise ValueError(
                "utility-bill integer must use a finite numeric spelling"
            )
        return _exact_integer(Decimal(spelling))
    raise ValueError("utility-bill integer must use an integer numeric value")


def validate_utility_integer(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("utility-bill integer must not be a boolean")
    if abs(value) > MAX_UTILITY_INTEGER_ABS:
        raise ValueError(
            "utility-bill integer magnitude must be at most "
            f"{MAX_UTILITY_INTEGER_ABS}"
        )
    return value


UtilityInteger = Annotated[
    int,
    BeforeValidator(_validate_integer_input),
    AfterValidator(validate_utility_integer),
]


def multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    """Multiply bounded operands without the process-wide Decimal precision rounding them."""

    precision = max(
        len(left.as_tuple().digits) + len(right.as_tuple().digits),
        1,
    )
    with localcontext(_arithmetic_context(precision)):
        return _canonical_zero(left * right)


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
    with localcontext(_arithmetic_context(_operation_precision(values))):
        return _canonical_zero(sum(values, Decimal("0")))


def add_exact(left: Decimal, right: Decimal) -> Decimal:
    return sum_exact((left, right))


def subtract_exact(left: Decimal, right: Decimal) -> Decimal:
    values = (left, right)
    with localcontext(_arithmetic_context(_operation_precision(values))):
        return _canonical_zero(left - right)


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
    with localcontext(_arithmetic_context(precision)) as context:
        result = value.quantize(quantum, rounding=ROUND_HALF_UP, context=context)
    return _canonical_zero(result)


def format_decimal_exact(value: Decimal) -> str:
    """Render every stored digit without consulting the ambient Decimal context."""

    if not value.is_finite():
        raise ValueError("utility-bill presentation requires a finite Decimal value")
    return format(_canonical_zero(value), "f")


def format_fixed_exact(value: Decimal, quantum: Decimal) -> str:
    """Round half-up in a fresh context, then render without another rounding step."""

    return format_decimal_exact(quantize_exact(value, quantum))


def format_usd_exact(value: Decimal) -> str:
    """Render a Decimal as signed US currency with deterministic cent rounding."""

    rendered = format_fixed_exact(value, MONEY_QUANTUM)
    if rendered.startswith("-"):
        return f"-${rendered[1:]}"
    return f"${rendered}"
