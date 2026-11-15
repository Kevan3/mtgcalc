"""Differential tests against SciPy (TP §1; dev-only third-party oracle)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mtgcalc import Deck, GameConfig, Query, Scenario, distribution, hypergeom, tag
from mtgcalc.api import probability
from mtgcalc.model.conditions import And, Compare
from mtgcalc.model.results import Probability

scipy_stats = pytest.importorskip("scipy.stats")


@given(st.integers(1, 120), st.data())
def test_univariate_pmf_matches_scipy(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    n = data.draw(st.integers(0, min(N, 20)))
    ours = hypergeom(N, K, n).pmf
    for k, p in enumerate(ours):
        assert float(p) == pytest.approx(scipy_stats.hypergeom.pmf(k, N, K, n), rel=1e-9, abs=1e-15)


@given(st.integers(1, 60), st.data())
def test_engine_distribution_matches_scipy(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    turn = data.draw(st.integers(0, 5))
    n = 7 + GameConfig().draws_through(turn)
    if n > N:
        return
    d = distribution(Scenario(Deck.from_counts(N, {"x": K})), tag("x"), turn)
    for k, p in enumerate(d.pmf):
        assert float(p) == pytest.approx(scipy_stats.hypergeom.pmf(k, N, K, n), rel=1e-9, abs=1e-15)


@given(st.lists(st.integers(0, 12), min_size=2, max_size=4), st.integers(0, 10), st.data())
def test_multivariate_point_probabilities_match_scipy(
    counts: list[int], filler: int, data: st.DataObject
) -> None:
    N = sum(counts) + filler
    if N == 0:
        return  # an empty library is invalid input (covered by unit tests)
    n = data.draw(st.integers(0, min(N, 9)))
    xs = [data.draw(st.integers(0, min(c, n))) for c in counts]
    if sum(xs) > n:
        return
    cats = {f"c{i}": c for i, c in enumerate(counts)}
    deck = Deck.from_counts(N, cats)
    leaves = tuple(Compare(tag(f"c{i}"), "==", x) for i, x in enumerate(xs))
    res = probability(Scenario(deck, GameConfig(hand_size=n)), Query(And(leaves)))
    assert isinstance(res, Probability)
    full = [*counts, filler]
    expected = scipy_stats.multivariate_hypergeom.pmf([*xs, n - sum(xs)], full, n)
    assert res.value == pytest.approx(expected, rel=1e-9, abs=1e-15)
