"""Reference values A1-A9 (MATH §12) asserted exactly (TP §5).

Each expected value is written independently with ``math.comb`` closed forms.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb

import pytest

from mtgcalc import (
    Category,
    Deck,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    Query,
    Scenario,
    count,
    distribution,
    mulligan_report,
    parse_condition,
    probability,
    tag,
)
from mtgcalc.model.results import ConditionalResult, Probability


def hyp(N: int, K: int, n: int, k: int) -> Fraction:
    return Fraction(comb(K, k) * comb(N - K, n - k), comb(N, n))


def exact(p: object) -> Fraction:
    assert isinstance(p, Probability) and p.exact is not None
    return p.exact


DECK_4OF = Deck.from_counts(60, {"x": 4})
DECK_LANDS = Deck.from_counts(60, {"land": 24})
P_A1 = 1 - hyp(60, 4, 7, 0)


def test_a1_one_of_four_in_opening_hand() -> None:
    p = exact(probability(Scenario(DECK_4OF), "x >= 1"))
    assert p == P_A1
    assert float(p) == pytest.approx(0.3994996257, abs=1e-10)


def test_a2_land_pmf() -> None:
    d = distribution(Scenario(DECK_LANDS), tag("land"))
    assert d.pmf == tuple(hyp(60, 24, 7, k) for k in range(8))
    published = [0.021615, 0.121041, 0.269415, 0.308704, 0.196448, 0.069335, 0.012546, 0.000896]
    assert [round(float(p), 6) for p in d.pmf] == published


def test_a3_london_mulligan_geometric() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("x")),), count("x") >= 1, max_mulligans=1)
    report = mulligan_report(Scenario(DECK_4OF, mulligan=cfg), "x >= 1")
    assert report.p_success == 1 - (1 - P_A1) ** 2
    assert float(report.p_success) == pytest.approx(0.6393993005, abs=1e-10)


def test_a4_on_the_draw_by_turn_3() -> None:
    p = exact(probability(Scenario(DECK_4OF, GameConfig(on_play=False)), "x >= 1 @T3"))
    assert p == 1 - hyp(60, 4, 10, 0)


def test_a5_land_drops_collapse_to_last_marginal() -> None:
    p = exact(probability(Scenario(DECK_LANDS), "land>=1 @T0 AND land>=2 @T2 AND land>=3 @T3"))
    assert p == sum(hyp(60, 24, 9, k) for k in range(3, 10))
    assert float(p) == pytest.approx(0.7886544700, abs=1e-10)


def test_a6_two_disjoint_four_ofs() -> None:
    deck = Deck.from_counts(60, {"a": 4, "b": 4})
    p = exact(probability(Scenario(deck), "a >= 1 AND b >= 1"))
    expected = Fraction(
        sum(
            comb(4, x) * comb(4, y) * comb(52, 7 - x - y)
            for x in range(1, 5)
            for y in range(1, 5)
            if x + y <= 7
        ),
        comb(60, 7),
    )
    assert p == expected


def test_a7_genuinely_path_dependent() -> None:
    p = exact(probability(Scenario(DECK_LANDS), "land >= 2 @T0 AND land >= 4 @T4"))
    expected = sum(
        hyp(60, 24, 7, a) * hyp(53, 24 - a, 3, b)
        for a in range(2, 8)
        for b in range(4)
        if a + b >= 4
    )
    assert p == expected == Fraction(209193119, 335980515)


def test_a8_conditional_colored_sources() -> None:
    deck = Deck.from_counts(60, {"red": Category(14, frozenset({"land"})), "land": 10})
    q = Query(parse_condition("red >= 1"), parse_condition("land >= 3"), turn=2)
    res = probability(Scenario(deck, GameConfig(on_play=False)), q)
    assert isinstance(res, ConditionalResult) and res.result is not None
    joint = sum(
        Fraction(comb(14, r) * comb(10, o) * comb(36, 9 - r - o), comb(60, 9))
        for r in range(1, 10)
        for o in range(10)
        if r + o >= 3 and r + o <= 9
    )
    given = sum(hyp(60, 24, 9, k) for k in range(3, 10))
    assert res.result.exact == joint / given
    assert float(joint / given) == pytest.approx(0.9717531574, abs=1e-10)


def test_a9_mean_and_variance() -> None:
    d = distribution(Scenario(DECK_LANDS), tag("land"))
    assert d.mean == Fraction(14, 5)
    assert d.variance == Fraction(2226, 1475)


def test_a7_disjunction_inclusion_exclusion() -> None:
    """Regression: states decided *true* early must be scaled by later batch denominators."""
    p_or = exact(probability(Scenario(DECK_LANDS), "land >= 2 @T0 OR land >= 4 @T4"))
    p_a = sum(hyp(60, 24, 7, k) for k in range(2, 8))
    p_b = sum(hyp(60, 24, 10, k) for k in range(4, 11))
    assert p_or == p_a + p_b - Fraction(209193119, 335980515)
