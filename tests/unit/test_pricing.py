"""Unit tests for the pure pricing rules: table-driven boundary cases plus Hypothesis invariants."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sut.pricing import (
    DISCOUNT_THRESHOLD_CENTS,
    LineItem,
    discount_for,
    format_cents,
    quote,
)

pytestmark = pytest.mark.unit


@pytest.mark.smoke
def test_empty_cart_costs_nothing() -> None:
    q = quote([])
    assert (q.subtotal_cents, q.discount_cents, q.total_cents) == (0, 0, 0)


def test_subtotal_sums_line_totals() -> None:
    q = quote([LineItem(1299, 2), LineItem(500, 1)])
    assert q.subtotal_cents == 3098
    assert q.total_cents == 3098


@pytest.mark.parametrize(
    ("subtotal", "expected_discount"),
    [
        (0, 0),
        (9_999, 0),  # one cent below the threshold: no discount
        (10_000, 1_000),  # exactly at the threshold: discount applies
        (10_005, 1_001),  # 1000.5 rounds half up
        (10_004, 1_000),  # 1000.4 rounds down
        (25_990, 2_599),
    ],
)
def test_discount_threshold_and_rounding(subtotal: int, expected_discount: int) -> None:
    assert discount_for(subtotal) == expected_discount


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"unit_price_cents": -1, "quantity": 1}, "unit price"),
        ({"unit_price_cents": 100, "quantity": 0}, "quantity"),
    ],
)
def test_line_item_rejects_invalid_values(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        LineItem(**kwargs)


@pytest.mark.parametrize(
    ("cents", "text"),
    [(0, "$0.00"), (5, "$0.05"), (1299, "$12.99"), (123456, "$1,234.56"), (-250, "-$2.50")],
)
def test_format_cents(cents: int, text: str) -> None:
    assert format_cents(cents) == text


@pytest.mark.property
@given(st.lists(st.tuples(st.integers(0, 100_000), st.integers(1, 99)), max_size=20))
def test_quote_invariants(lines: list[tuple[int, int]]) -> None:
    q = quote([LineItem(price, qty) for price, qty in lines])
    assert q.subtotal_cents == sum(price * qty for price, qty in lines)
    assert 0 <= q.discount_cents <= q.subtotal_cents
    assert q.total_cents == q.subtotal_cents - q.discount_cents
    if q.subtotal_cents < DISCOUNT_THRESHOLD_CENTS:
        assert q.discount_cents == 0
    else:
        # Never more than 10% (plus at most half a cent of rounding).
        assert abs(q.discount_cents * 10 - q.subtotal_cents) <= 5


@pytest.mark.property
@given(st.integers(min_value=-(10**9), max_value=10**9))
def test_format_cents_round_trips(cents: int) -> None:
    text = format_cents(cents)
    assert round(float(text.replace("$", "").replace(",", "")) * 100) == cents
