"""Rust core conformance, port stage 3 (ADR-0013 §2): distributions and turn tables.

The Rust ``Distributions`` and ``TurnTable`` questions must equal Python's
``analysis.stats.distributions`` and ``turn_table`` on the pure-Python engine (as
``to_dict`` JSON), and fail with the same error kind.

Skipped when the optional ``mtgcalc_native`` extension is not installed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mtgcalc.analysis.stats import distributions, turn_table
from mtgcalc.engine.select import native_module
from mtgcalc.errors import StateSpaceTooLargeError, ValidationError
from mtgcalc.model.conditions import Condition
from mtgcalc.model.deck import Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Selector, Tag
from mtgcalc.model.serialization import to_dict
from tests.engine.test_core_conformance import _python_engine
from tests.strategies import conditions, decks, games, selectors

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")

Json = dict[str, Any]


def rust(request: Json) -> Json:
    module = native_module()
    assert module is not None
    reply: Json = json.loads(module.probability_json(json.dumps(request)))
    return reply


def _seen(game: GameConfig, turns: list[int]) -> int:
    return game.hand_size + max(game.draws_through(t) for t in turns)


@st.composite
def distribution_cases(draw: st.DrawFn) -> tuple[Scenario, Selector, list[int]]:
    deck = draw(decks(min_size=4, max_size=12))
    game = draw(games())
    turns = draw(st.lists(st.integers(0, 4), min_size=1, max_size=4))
    assume(_seen(game, turns) <= deck.size)
    return Scenario(deck, game), draw(selectors(deck)), turns


@settings(max_examples=300)
@given(distribution_cases())
def test_distributions_match_python(case: tuple[Scenario, Selector, list[int]]) -> None:
    sc, sel, turns = case
    with _python_engine():
        expected = [
            json.loads(json.dumps(to_dict(d))) for d in distributions(sc, sel, turns).values()
        ]
    got = rust(
        {
            "scenario": to_dict(sc),
            "question": {"type": "Distributions", "selector": to_dict(sel), "turns": turns},
        }
    )
    assert got == {"type": "Distributions", "items": expected}


@st.composite
def turn_cases(draw: st.DrawFn) -> tuple[Scenario, Condition, list[int]]:
    deck = draw(decks(min_size=4, max_size=12))
    game = draw(games())
    turns = draw(st.lists(st.integers(0, 4), min_size=1, max_size=4))
    cond = draw(conditions(deck, 3))
    assume(_seen(game, [*turns, 3]) <= deck.size)
    return Scenario(deck, game), cond, turns


@settings(max_examples=300)
@given(turn_cases())
def test_turn_tables_match_python(case: tuple[Scenario, Condition, list[int]]) -> None:
    sc, cond, turns = case
    try:
        with _python_engine():
            expected: Json = json.loads(json.dumps(to_dict(turn_table(sc, cond, turns))))
    except ValidationError as e:
        got = rust(
            {
                "scenario": to_dict(sc),
                "query": {"type": "Query", "condition": to_dict(cond)},
                "question": {"type": "TurnTable", "turns": turns},
            }
        )
        assert (got["kind"], got["field"], got["message"]) == ("validation", e.field, e.message)
        return
    got = rust(
        {
            "scenario": to_dict(sc),
            "query": {"type": "Query", "condition": to_dict(cond)},
            "question": {"type": "TurnTable", "turns": turns},
        }
    )
    assert got == expected


def test_realistic_web_questions_match_python() -> None:
    deck = Deck.from_counts(99, {"land": 36, "ramp": 10, "draw": 10})
    sc = Scenario(deck, GameConfig(on_play=False))
    turns = list(range(11))
    with _python_engine():
        dist = [
            json.loads(json.dumps(to_dict(d)))
            for d in distributions(sc, Tag("land"), turns).values()
        ]
        table = json.loads(json.dumps(to_dict(turn_table(sc, Compare_ge("land", 4), turns))))
    got = rust(
        {
            "scenario": to_dict(sc),
            "question": {
                "type": "Distributions",
                "selector": {"type": "Tag", "name": "land"},
                "turns": turns,
            },
        }
    )
    assert got["items"] == dist
    got = rust(
        {
            "scenario": to_dict(sc),
            "rule": "land >= 4",
            "question": {"type": "TurnTable", "turns": turns},
        }
    )
    assert got == table


def Compare_ge(tag: str, n: int) -> Condition:
    from mtgcalc.model.conditions import Compare

    return Compare(Tag(tag), ">=", n)


def test_the_state_limit_applies_like_python() -> None:
    sc = Scenario(Deck.from_counts(60, {"a": 10, "b": 10, "c": 10}))
    sel = {"type": "AnyOf", "items": [{"type": "Tag", "name": "a"}, {"type": "Tag", "name": "b"}]}
    with pytest.raises(StateSpaceTooLargeError), _python_engine():
        from mtgcalc.model.selectors import AnyOf

        distributions(sc, AnyOf((Tag("a"), Tag("b"))), [0, 5], limit=3)
    got = rust(
        {
            "scenario": to_dict(sc),
            "question": {"type": "Distributions", "selector": sel, "turns": [0, 5]},
            "limit": 3,
        }
    )
    assert got["kind"] == "too_large"


@pytest.mark.parametrize(
    "request_",
    [
        {
            "question": {"type": "Distributions", "selector": {"type": "Everything"}, "turns": [0]},
            "rule": "a >= 1",
        },
        {"question": {"type": "TurnTable", "turns": [0]}},
        {"question": {"type": "TurnTable", "turns": [0]}, "rule": "a >= 1", "turn": 2},
        {"question": {"type": "Nope"}},
    ],
)
def test_ill_formed_questions_are_malformed(request_: Json) -> None:
    sc = Scenario(Deck.from_counts(60, {"a": 10}))
    assert rust({"scenario": to_dict(sc), **request_})["kind"] == "malformed"


def test_given_is_refused_in_turn_tables() -> None:
    sc = Scenario(Deck.from_counts(60, {"a": 10}))
    q = {
        "type": "Query",
        "condition": {"type": "Const", "value": True},
        "given": {"type": "Const", "value": True},
    }
    assert (
        rust(
            {"scenario": to_dict(sc), "query": q, "question": {"type": "TurnTable", "turns": [0]}}
        )["kind"]
        == "malformed"
    )
    got = rust(
        {
            "scenario": to_dict(sc),
            "rule": "a >= 1 GIVEN a >= 0",
            "question": {"type": "TurnTable", "turns": [0]},
        }
    )
    assert (got["kind"], got["message"]) == ("parse", "GIVEN is not allowed here")
