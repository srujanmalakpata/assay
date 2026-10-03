"""Pure pricing rules (no I/O), kept separate so they can be unit tested directly.

All money is integer cents to avoid floating-point rounding errors.
"""

from __future__ import annotations

from dataclasses import dataclass

DISCOUNT_THRESHOLD_CENTS = 10_000  # orders of $100.00 or more ...
DISCOUNT_PERCENT = 10  # ... get 10% off


@dataclass(frozen=True)
class LineItem:
    unit_price_cents: int
    quantity: int

    def __post_init__(self) -> None:
        if self.unit_price_cents < 0:
            raise ValueError("unit price must not be negative")
        if self.quantity < 1:
            raise ValueError("quantity must be at least 1")

    @property
    def total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


@dataclass(frozen=True)
class Quote:
    subtotal_cents: int
    discount_cents: int

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents - self.discount_cents


def discount_for(subtotal_cents: int) -> int:
    """Return the discount in cents, rounding half a cent up."""
    if subtotal_cents < DISCOUNT_THRESHOLD_CENTS:
        return 0
    # Integer "round half up" of subtotal * percent / 100.
    return (subtotal_cents * DISCOUNT_PERCENT + 50) // 100


def quote(lines: list[LineItem]) -> Quote:
    subtotal = sum(line.total_cents for line in lines)
    return Quote(subtotal_cents=subtotal, discount_cents=discount_for(subtotal))


def format_cents(cents: int) -> str:
    """Format integer cents as a dollar string, e.g. 1299 -> '$12.99'."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{remainder:02d}"
