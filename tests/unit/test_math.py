"""Unit tests: math kernel (LLD §2)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mtgcalc.errors import ValidationError
from mtgcalc.math.comb import binom, transitions
from mtgcalc.math.intervals import wilson


@pytest.mark.parametrize(
    ("n", "k", "expected"),
    [(5, 2, 10), (5, 0, 1), (5, 5, 1), (5, 6, 0), (5, -1, 0), (-1, 0, 0), (0, 0, 1)],
)
def test_binom_edges(n: int, k: int, expected: int) -> None:
    assert binom(n, k) == expected


def test_binom_large_is_exact() -> None:
    assert binom(100, 50) == math.comb(100, 50)
    assert binom(100, 50).bit_length() == 97  # MATH §3


def test_transitions_small_example() -> None:
    # 2 atoms with 2 and 1 cards, pool of 1, draw 2
    got = dict(transitions((2, 1), 1, 2))
    assert got == {(0, 1): 1, (1, 0): 2, (1, 1): 2, (2, 0): 1}


@given(
    st.lists(st.integers(0, 5), min_size=0, max_size=4).map(tuple),
    st.integers(0, 5),
    st.integers(0, 8),
)
def test_transitions_vandermonde(rem: tuple[int, ...], pool: int, b: int) -> None:
    """Chu-Vandermonde: coefficients sum to C(total, b) (MATH §4)."""
    total = sum(rem) + pool
    assert sum(c for _, c in transitions(rem, pool, b)) == binom(total, b)
    for d, c in transitions(rem, pool, b):
        assert c > 0
        assert all(0 <= x <= r for x, r in zip(d, rem, strict=True))
        assert 0 <= b - sum(d) <= pool


def test_transitions_invalid_inputs_are_empty() -> None:
    assert transitions((1,), 0, -1) == ()
    assert transitions((-1,), 0, 0) == ()
    assert transitions((), -1, 0) == ()


def test_wilson_known_value() -> None:
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-4)
    assert hi == pytest.approx(0.5962, abs=1e-4)


def test_wilson_extremes_stay_in_unit_interval() -> None:
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 0.35
    lo, hi = wilson(10, 10)
    assert hi == pytest.approx(1.0) and 0.65 < lo < 1


def test_wilson_symmetry() -> None:
    lo, hi = wilson(3, 20)
    lo2, hi2 = wilson(17, 20)
    assert lo == pytest.approx(1 - hi2) and hi == pytest.approx(1 - lo2)


@pytest.mark.parametrize(("s", "n"), [(1, 0), (-1, 5), (6, 5)])
def test_wilson_validation(s: int, n: int) -> None:
    with pytest.raises(ValidationError):
        wilson(s, n)
