"""Rust core conformance, port stage 4 (ADR-0013 §2): the London mulligan.

Under a mulligan configuration, the Rust core must give what the pure-Python reference
gives (as ``to_dict`` JSON): strategy-level probabilities (also conditional), the
mulligan report, the optimal keep strategy, and mulligan-aware distributions and turn
tables; and the same validation errors for invalid configurations.

Skipped when the optional ``mtgcalc_native`` extension is not installed.
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mtgcalc import api
from mtgcalc.analysis.stats import distributions, turn_table
from mtgcalc.engine.select import native_module
from mtgcalc.errors import ValidationError
from mtgcalc.model.conditions import Compare, Query
from mtgcalc.model.deck import Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig, PriorityGroup
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Tag
from mtgcalc.model.serialization import to_dict
from tests.engine.test_core_conformance import _python_engine, assert_same, request
from tests.strategies import mulligan_cases

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")

Json = dict[str, Any]


def rust(req: Json) -> Json:
    module = native_module()
    assert module is not None
    reply: Json = json.loads(module.probability_json(json.dumps(req)))
    return reply


def _plain(obj: object) -> Json:
    out: Json = json.loads(json.dumps(to_dict(obj)))
    return out


@settings(max_examples=250)
@given(mulligan_cases())
def test_strategy_level_probabilities_match_python(case: tuple[Scenario, Query]) -> None:
    assert_same(request(*case))


@settings(max_examples=200)
@given(mulligan_cases())
def test_mulligan_reports_match_python(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    query = Query(q.condition, None, q.turn)
    with _python_engine():
        expected = _plain(api.mulligan_report(sc, q.condition, turn=q.turn))
    got = rust({**request(sc, query), "question": {"type": "MulliganReport"}})
    assert got == expected


@settings(max_examples=200)
@given(mulligan_cases())
def test_optimal_keep_matches_python(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    query = Query(q.condition, None, q.turn)
    with _python_engine():
        expected = _plain(api.optimal_keep(sc, q.condition, turn=q.turn))
    got = rust({**request(sc, query), "question": {"type": "OptimalKeep"}})
    assert got == expected


@settings(max_examples=100)
@given(mulligan_cases(), st.lists(st.integers(0, 2), min_size=1, max_size=3))
def test_mulligan_tables_match_python(case: tuple[Scenario, Query], turns: list[int]) -> None:
    sc, q = case
    sel = Tag("a")
    dist_req = {
        "scenario": to_dict(sc),
        "question": {"type": "Distributions", "selector": to_dict(sel), "turns": turns},
    }
    table_req = {
        "scenario": to_dict(sc),
        "query": {"type": "Query", "condition": to_dict(q.condition)},
        "question": {"type": "TurnTable", "turns": turns},
    }
    for req, compute in (
        (
            dist_req,
            lambda: {
                "type": "Distributions",
                "items": [_plain(d) for d in distributions(sc, sel, turns).values()],
            },
        ),
        (table_req, lambda: _plain(turn_table(sc, q.condition, turns))),
    ):
        try:
            with _python_engine():
                expected = compute()
        except ValidationError as e:
            got = rust(req)
            assert (got["kind"], got["field"], got["message"]) == ("validation", e.field, e.message)
            continue
        assert rust(req) == expected


def _commander() -> Scenario:
    deck = Deck.from_counts(99, {"land": 35, "ramp": 12, "draw": 10})
    mull = MulliganConfig(
        priority=(PriorityGroup(Tag("land"), 3), PriorityGroup(Tag("ramp"), 1)),
        keep_rule=Compare(Tag("land"), ">=", 2),
        max_mulligans=2,
        free_mulligans=1,
    )
    return Scenario(deck, GameConfig(on_play=False), mull)


def test_a_realistic_commander_plan_matches_python() -> None:
    sc = _commander()
    success = Compare(Tag("ramp"), ">=", 1)
    for question, fn in (
        ("MulliganReport", api.mulligan_report),
        ("OptimalKeep", api.optimal_keep),
    ):
        with _python_engine():
            expected = _plain(fn(sc, success, turn=2))
        req = {
            "scenario": to_dict(sc),
            "query": to_dict(Query(success, None, 2)),
            "question": {"type": question},
        }
        assert rust(req) == expected


def test_a3_reference_value_through_the_boundary() -> None:
    sc = Scenario(
        Deck.from_counts(60, {"x": 4}),
        mulligan=MulliganConfig(
            priority=(PriorityGroup(Tag("x")),),
            keep_rule=Compare(Tag("x"), ">=", 1),
            max_mulligans=1,
        ),
    )
    got = rust(request(sc, Query(Compare(Tag("x"), ">=", 1))))
    assert float(Fraction(got["exact"]["value"])) == pytest.approx(0.6393993005, abs=1e-10)


@pytest.mark.parametrize(
    "mulligan",
    [
        {"type": "MulliganConfig", "priority": []},
        {
            "type": "MulliganConfig",
            "priority": [
                {"type": "PriorityGroup", "selector": {"type": "Tag", "name": "a"}, "quota": -1}
            ],
        },
        {
            "type": "MulliganConfig",
            "priority": [
                {"type": "PriorityGroup", "selector": {"type": "Tag", "name": "a"}},
                {"type": "PriorityGroup", "selector": {"type": "Tag", "name": "A"}},
            ],
        },
        {
            "type": "MulliganConfig",
            "priority": [{"type": "PriorityGroup", "selector": {"type": "Everything"}}],
            "max_mulligans": -1,
        },
        {
            "type": "MulliganConfig",
            "priority": [{"type": "PriorityGroup", "selector": {"type": "Everything"}}],
            "free_mulligans": 2,
        },
        {
            "type": "MulliganConfig",
            "priority": [{"type": "PriorityGroup", "selector": {"type": "Everything"}}],
            "draw_size": 0,
        },
        {
            "type": "MulliganConfig",
            "priority": [{"type": "PriorityGroup", "selector": {"type": "Everything"}}],
            "max_mulligans": 9,
        },
        {
            "type": "MulliganConfig",
            "priority": [{"type": "PriorityGroup", "selector": {"type": "Everything"}}],
            "keep_rule": {"type": "At", "turn": 2, "item": {"type": "Const", "value": True}},
        },
    ],
)
def test_invalid_mulligans_get_pythons_error(mulligan: Json) -> None:
    from mtgcalc.model.serialization import from_dict

    with pytest.raises(ValidationError) as e:
        from_dict(mulligan)
    sc = _plain(Scenario(Deck.from_counts(60, {"a": 10})))
    sc["mulligan"] = mulligan
    got = rust(
        {"scenario": sc, "query": {"type": "Query", "condition": {"type": "Const", "value": True}}}
    )
    assert (got["kind"], got["field"], got["message"]) == (
        "validation",
        e.value.field,
        e.value.message,
    )


def test_mulligan_questions_need_a_mulligan() -> None:
    sc = Scenario(Deck.from_counts(60, {"a": 10}))
    got = rust(
        {**request(sc, Query(Compare(Tag("a"), ">=", 1))), "question": {"type": "MulliganReport"}}
    )
    assert (got["kind"], got["field"]) == ("validation", "scenario.mulligan")


@pytest.mark.parametrize(
    ("keep", "success"),
    [
        ("land > 2", "land >= 4 @T3 AND ramp > 0 @T3"),
        ("land >= 2", "land > 4 @T4"),
        ("NOT land < 3", "NOT ramp <= 1 @T2"),
        ("land in 2..5", "assign(land >= 3, ramp >= 2) @T3"),
    ],
)
def test_derived_quotas_bottom_like_python(keep: str, success: str) -> None:
    """Quotas derived from the conditions (no explicit quota) only matter when several
    cards go to the bottom: 7-card draws and up to 3 mulligans make them matter."""
    from mtgcalc.io.expr import parse_condition

    deck = Deck.from_counts(60, {"land": 24, "ramp": 8, "draw": 6})
    mull = MulliganConfig(
        priority=(
            PriorityGroup(Tag("land")),
            PriorityGroup(Tag("ramp")),
            PriorityGroup(Tag("draw")),
        ),
        keep_rule=parse_condition(keep),
        max_mulligans=3,
    )
    sc = Scenario(deck, GameConfig(), mull)
    cond = parse_condition(success)
    for question, fn in (
        ("MulliganReport", api.mulligan_report),
        ("OptimalKeep", api.optimal_keep),
    ):
        with _python_engine():
            expected = _plain(fn(sc, cond))
        req = {
            "scenario": to_dict(sc),
            "query": to_dict(Query(cond)),
            "question": {"type": question},
        }
        assert rust(req) == expected, question


def test_mulligan_advice_is_the_report_and_the_best_plan() -> None:
    sc = _commander()
    q = {"type": "Query", "condition": to_dict(Compare(Tag("ramp"), ">=", 1)), "turn": 2}
    base = {"scenario": to_dict(sc), "query": q}
    advice = rust({**base, "question": {"type": "MulliganAdvice"}})
    assert advice == {
        "type": "MulliganAdvice",
        "report": rust({**base, "question": {"type": "MulliganReport"}}),
        "best": rust({**base, "question": {"type": "OptimalKeep"}}),
    }
