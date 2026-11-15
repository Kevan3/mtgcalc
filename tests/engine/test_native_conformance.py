"""Native (Rust) engine conformance: identical integers to the Python engine (NFR-09).

Skipped when the optional ``mtgcalc_native`` extension is not installed. The full
oracle/property suites additionally run against whichever engine is the default, and CI
runs them once more with ``MTGCALC_ENGINE=python``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings

from mtgcalc.analysis.prepare import prepare
from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.policy import KEEP_BIT
from mtgcalc.engine.base import InitialStates, State
from mtgcalc.engine.exact import ExactEngine
from mtgcalc.engine.mulligan import hands
from mtgcalc.engine.select import native_module
from mtgcalc.math.comb import binom
from mtgcalc.model.conditions import Query
from mtgcalc.model.scenario import Scenario

if TYPE_CHECKING:
    from mtgcalc.engine.native import NativeEngine
from tests.strategies import mulligan_cases, multi_checkpoint_cases, plain_cases

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")


def _both(cq: CompiledQuery, init: InitialStates | None = None) -> None:
    from mtgcalc.engine.native import NativeEngine

    for early in (True, False):
        for retire in (True, False):
            py = ExactEngine(early_resolution=early, retirement=retire).run(cq, init)
            rs = NativeEngine(early_resolution=early, retirement=retire).run(cq, init)
            assert dict(rs.outputs) == dict(py.outputs)
            assert rs.denominator == py.denominator
            assert dict(rs.snapshots) == dict(py.snapshots)


@given(plain_cases())
def test_plain_queries(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    outputs = {"q": q.condition} if q.given is None else {"q": q.condition, "g": q.given}
    _both(prepare(sc, outputs, turn=q.turn).cq)


@given(multi_checkpoint_cases())
def test_multi_checkpoint_queries(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    _both(prepare(sc, {"q": q.condition}, turn=q.turn).cq)


@given(plain_cases())
def test_observer_snapshots(case: tuple[Scenario, Query]) -> None:
    from mtgcalc.model.selectors import Tag
    from tests.oracle.bruteforce import turns_used

    sc, q = case
    observe = [(t, Tag("a")) for t in sorted(turns_used(q.condition, q.turn))]  # turns that fit
    _both(prepare(sc, {"q": q.condition}, turn=q.turn, observe=observe).cq)


@settings(max_examples=60)
@given(mulligan_cases())
def test_mulligan_initial_states(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    prep = prepare(sc, {"q": q.condition}, turn=q.turn)
    plan = prep.plan
    assert plan is not None
    for depth in range(plan.max_mulligans + 1):
        init: dict[State, int] = defaultdict(int)
        for hand, bott, c in hands(prep.cq, plan, depth):
            kept = tuple(h - b for h, b in zip(hand, bott, strict=True))
            init[(kept, bott, (1 << KEEP_BIT) if plan.keeps(kept) else 0)] += c
        total = binom(prep.cq.atoms.deck_size, plan.draw)
        _both(prep.cq, InitialStates(init, total, plan.draw))


def test_bigint_fallback_matches() -> None:
    """Long horizons on big decks overflow u128; the BigUint path must stay exact."""
    from mtgcalc import Deck, GameConfig
    from mtgcalc.model.conditions import And, At, Compare
    from mtgcalc.model.selectors import Tag

    deck = Deck.from_counts(250, {"land": 100, "ramp": 30})
    cond = And(tuple(At(t, Compare(Tag("land"), ">=", t // 2)) for t in range(0, 41, 4)))
    prep = prepare(Scenario(deck, GameConfig(draws_per_turn=2)), {"q": cond})
    _both(prep.cq)


def _engines() -> Iterator[tuple[ExactEngine, NativeEngine]]:
    from mtgcalc.engine.native import NativeEngine

    for early in (True, False):
        for retire in (True, False):
            yield (
                ExactEngine(early_resolution=early, retirement=retire),
                NativeEngine(early_resolution=early, retirement=retire),
            )


@settings(max_examples=60)
@given(mulligan_cases())
def test_mulligan_depths_match(case: tuple[Scenario, Query]) -> None:
    """Rust enumeration of drawn hands, bottoming and keep rule == the Python reference."""
    sc, q = case
    prep = prepare(sc, {"q": q.condition}, turn=q.turn)
    assert prep.plan is not None
    for py, rs in _engines():
        assert rs.mulligan(prep.cq, prep.plan) == py.mulligan(prep.cq, prep.plan)


@settings(max_examples=40)
@given(mulligan_cases())
def test_hand_values_match(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    prep = prepare(sc, {"q": q.condition}, turn=q.turn)
    assert prep.plan is not None
    for py, rs in _engines():
        assert rs.hand_values(prep.cq, prep.plan, "q") == py.hand_values(prep.cq, prep.plan, "q")


def test_state_limit_and_invalid_input_errors() -> None:
    import mtgcalc_native

    from mtgcalc import Deck, GameConfig
    from mtgcalc.engine.native import NativeEngine, _flatten
    from mtgcalc.errors import StateSpaceTooLargeError
    from mtgcalc.model.conditions import At, Compare
    from mtgcalc.model.selectors import Tag

    deck = Deck.from_counts(60, {"land": 24, "ramp": 8})
    cond = At(5, Compare(Tag("land"), ">=", 3))
    cq = prepare(Scenario(deck, GameConfig()), {"q": cond}).cq
    with pytest.raises(StateSpaceTooLargeError):
        NativeEngine().run(cq, limit=2)
    broken = list(_flatten(cq))
    broken[2] += 1  # pool no longer adds up to the deck size
    with pytest.raises(ValueError, match="deck size"):
        mtgcalc_native.run(tuple(broken), None, (1000, True, True))
