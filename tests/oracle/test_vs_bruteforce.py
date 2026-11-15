"""Primary correctness gate: exact engine == independent brute-force oracle (TP §6, NFR-01)."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings

from mtgcalc.api import probability
from mtgcalc.model.conditions import Query
from mtgcalc.model.results import ConditionalResult, Probability
from mtgcalc.model.scenario import Scenario
from tests.oracle.bruteforce import oracle_probabilities
from tests.strategies import mulligan_cases, multi_checkpoint_cases, plain_cases


def _engine(scenario: Scenario, q: Query) -> tuple[Fraction, Fraction]:
    res = probability(scenario, q)
    if isinstance(res, ConditionalResult):
        assert res.joint.exact is not None and res.given.exact is not None
        return res.joint.exact, res.given.exact
    assert isinstance(res, Probability) and res.exact is not None
    return res.exact, Fraction(1)


@given(plain_cases())
def test_engine_matches_bruteforce_without_mulligan(case: tuple[Scenario, Query]) -> None:
    scenario, q = case
    assert _engine(scenario, q) == oracle_probabilities(scenario, q)


@settings(max_examples=60)
@given(mulligan_cases())
def test_engine_matches_bruteforce_with_mulligan(case: tuple[Scenario, Query]) -> None:
    scenario, q = case
    assert _engine(scenario, q) == oracle_probabilities(scenario, q)


@given(multi_checkpoint_cases())
def test_engine_matches_bruteforce_across_checkpoints(case: tuple[Scenario, Query]) -> None:
    scenario, q = case
    assert _engine(scenario, q) == oracle_probabilities(scenario, q)
