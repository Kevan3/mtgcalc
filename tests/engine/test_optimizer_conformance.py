"""Rust core conformance, port stage 5 (ADR-0013 §2): the card-count optimizer.

The Rust optimizer must give exactly what Python's ``analysis.optimizer.optimize`` gives
with one worker (``to_dict(OptimizeResult)``, including the number of evaluations and the
frontier), or the same error: ``InfeasibleError`` (same message) or ``ValidationError``.

Skipped when the optional ``mtgcalc_native`` extension is not installed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mtgcalc.analysis.optimizer import Objective, OptimizeProblem, Variable, optimize
from mtgcalc.engine.select import native_module
from mtgcalc.errors import InfeasibleError, ValidationError
from mtgcalc.io.expr import parse_condition
from mtgcalc.model.conditions import Query
from mtgcalc.model.deck import Category
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig, PriorityGroup
from mtgcalc.model.selectors import Tag
from mtgcalc.model.serialization import to_dict
from tests.engine.test_core_conformance import _python_engine

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")

Json = dict[str, Any]


def rust(problem: OptimizeProblem) -> Json:
    module = native_module()
    assert module is not None
    reply: Json = json.loads(module.probability_json(json.dumps({"optimize": to_dict(problem)})))
    return reply


def assert_same(problem: OptimizeProblem) -> Json:
    problem = replace(problem, workers=1)
    try:
        with _python_engine():
            expected: Json = json.loads(json.dumps(to_dict(optimize(problem))))
    except InfeasibleError as e:
        got = rust(problem)
        assert (got["kind"], got["message"]) == ("infeasible", str(e))
        return got
    except ValidationError as e:
        got = rust(problem)
        assert (got["kind"], got["field"], got["message"]) == ("validation", e.field, e.message)
        return got
    got = rust(problem)
    assert got == expected
    return got


RULES = [
    "land >= 3 @T3",
    "land >= 2 AND ramp >= 1 @T2",
    "land >= 4 @T4 OR ramp >= 2 @T3",
    "land in 2..4 @T3",
    "NOT land >= 6 @T5 AND ramp >= 1 @T2",
    "land >= 3 @T3 XOR ramp >= 1",
    "assign(land >= 2, ramp >= 1) @T2",
    "exactly(1, land >= 3 @T3, ramp >= 1 @T3)",
    'tag:"(other)" >= 2',
    # Strict ">" and every operator that passes monotonicity through (or flips it):
    # the bisection is only used when the rule is monotone, which shows in `evaluations`.
    "land > 2 @T3",
    "land > 3 @T4 AND ramp > 0 @T2",
    "NOT NOT land > 2 @T3",
    "NOT land < 3 @T3 OR ramp > 1",
    "land <= 2 @T2 -> ramp >= 1 @T3",
    "NOT ramp >= 1 @T2 -> land > 3 @T4",
    "atleast(1, land > 3 @T4, ramp > 0 @T2)",
]


@st.composite
def problems(draw: st.DrawFn) -> OptimizeProblem:
    names = draw(st.sampled_from([["land"], ["land", "ramp"], ["land", "ramp", "draw"]]))
    variables = []
    for n in names:
        lo = draw(st.integers(0, 12))
        variables.append(
            Variable(
                n, lo, lo + draw(st.integers(0, 6)), frozenset(draw(st.sampled_from([(), ("x",)])))
            )
        )
    fixed = (
        (("draw", Category(draw(st.integers(0, 6)))),)
        if "draw" not in names and draw(st.booleans())
        else ()
    )
    objectives: list[Objective] = ["min_count", "max_probability", "min_total"]
    objective = draw(st.sampled_from(objectives))
    assume(objective != "min_count" or len(variables) == 1)
    mulligan = None
    if draw(st.integers(0, 4)) == 0:
        mulligan = MulliganConfig(priority=(PriorityGroup(Tag("land"), 3),), max_mulligans=1)
    return OptimizeProblem(
        deck_size=draw(st.sampled_from([30, 40])),
        variables=tuple(variables),
        query=Query(parse_condition(draw(st.sampled_from(RULES)))),
        fixed=fixed,
        game=GameConfig(on_play=draw(st.booleans())),
        mulligan=mulligan,
        objective=objective,
        # Mostly reachable targets and roomy budgets, so every objective finds answers;
        # the rest exercise the "infeasible" paths.
        target=None
        if objective == "max_probability"
        else Fraction(draw(st.sampled_from([1, 5, 20, 40, 60, 95])), 100),
        budget=draw(st.sampled_from([None, None, None, 4, 12, 25])),
        exhaustive_limit=draw(st.sampled_from([5000, 3, 0])),
        assume_monotone=draw(st.sampled_from([None, None, True, False])),
    )


@settings(max_examples=250)
@given(problems())
def test_generated_problems_match_python(problem: OptimizeProblem) -> None:
    assert_same(problem)


def test_how_many_lands_for_four_by_turn_four() -> None:
    p = OptimizeProblem(
        deck_size=60,
        variables=(Variable("land", 18, 40),),
        query=Query(parse_condition("land >= 4"), turn=4),
        objective="min_count",
        target=Fraction(9, 10),
    )
    got = assert_same(p)
    assert got["proven_optimal"] is True


def test_sharing_slots_between_three_types_matches_python() -> None:
    p = OptimizeProblem(
        deck_size=60,
        variables=(Variable("land", 20, 26), Variable("ramp", 0, 8), Variable("draw", 0, 8)),
        query=Query(parse_condition("land >= 3 @T3 AND (ramp >= 1 OR draw >= 1) @T3")),
        objective="max_probability",
        budget=30,
    )
    assert_same(p)


def test_local_search_on_a_large_space_matches_python() -> None:
    p = OptimizeProblem(
        deck_size=60,
        variables=(Variable("land", 16, 28), Variable("ramp", 0, 10), Variable("draw", 0, 10)),
        query=Query(parse_condition("land >= 3 @T3 AND ramp >= 1 @T3 AND land <= 6 @T6")),
        objective="max_probability",
        budget=36,
        exhaustive_limit=10,
    )
    got = assert_same(p)
    assert got["proven_optimal"] is False


def _base(**changes: Any) -> OptimizeProblem:
    fields: dict[str, Any] = {
        "deck_size": 60,
        "variables": (Variable("land", 18, 26),),
        "query": Query(parse_condition("land >= 4"), turn=4),
        "objective": "min_count",
        "target": Fraction(9, 10),
    }
    return OptimizeProblem(**{**fields, **changes})


VAR_A = {
    "type": "Variable",
    "name": "a",
    "lo": 0,
    "hi": 1,
    "tags": {"type": "frozenset", "items": []},
}
VAR_B = {**VAR_A, "name": "b"}
CONST = {"type": "Const", "value": True}


@pytest.mark.parametrize(
    ("patch", "build"),
    [
        ({"variables": []}, lambda: _base(variables=())),
        ({"variables": [{**VAR_A, "lo": 3}]}, lambda: Variable("a", 3, 1)),
        (
            {
                "fixed": [
                    [
                        "land",
                        {
                            "type": "Category",
                            "count": 1,
                            "tags": {"type": "frozenset", "items": []},
                        },
                    ]
                ]
            },
            lambda: _base(fixed=(("land", Category(1)),)),
        ),
        (
            {"objective": "min_total", "target": None},
            lambda: _base(objective="min_total", target=None),
        ),
        (
            {"variables": [VAR_A, VAR_B]},
            lambda: _base(variables=(Variable("a", 0, 1), Variable("b", 0, 1))),
        ),
        ({"budget": -1}, lambda: _base(budget=-1)),
        ({"workers": 0}, lambda: _base(workers=0)),
        (
            {"query": {"type": "Query", "condition": CONST, "given": CONST, "turn": 0}},
            lambda: _base(query=Query(parse_condition("true"), parse_condition("true"))),
        ),
    ],
)
def test_invalid_problems_get_pythons_error(patch: Json, build: Any) -> None:
    with pytest.raises(ValidationError) as e:
        build()
    module = native_module()
    assert module is not None
    data = {**to_dict(_base()), **patch}
    got = json.loads(module.probability_json(json.dumps({"optimize": data})))
    assert (got["kind"], got["field"], got["message"]) == (
        "validation",
        e.value.field,
        e.value.message,
    )


def test_an_optimize_request_takes_only_the_problem() -> None:
    module = native_module()
    assert module is not None
    p = to_dict(
        OptimizeProblem(
            deck_size=60,
            variables=(Variable("land", 18, 26),),
            query=Query(parse_condition("land >= 4")),
        )
    )
    got = json.loads(module.probability_json(json.dumps({"optimize": p, "rule": "land >= 1"})))
    assert got["kind"] == "malformed"


@settings(max_examples=60)
@given(problems())
def test_one_fewer_is_the_chance_of_one_card_less(problem: OptimizeProblem) -> None:
    """``one_fewer`` = the desktop app's ``_one_fewer``: P at (answer - 1), or null at ``lo``."""
    assume(len(problem.variables) == 1)
    problem = replace(problem, workers=1)
    try:
        with _python_engine():
            res = optimize(problem)
    except (InfeasibleError, ValidationError):
        return
    module = native_module()
    assert module is not None
    req = {"optimize": to_dict(problem), "one_fewer": True}
    got = json.loads(module.probability_json(json.dumps(req)))
    ((_, c),) = res.counts
    (var,) = problem.variables
    if c == var.lo:
        assert got["one_fewer"] is None
        return
    smaller = replace(
        problem,
        variables=(replace(var, lo=c - 1, hi=c - 1),),
        objective="max_probability",
        target=None,
    )
    with _python_engine():
        expected = optimize(smaller).probability
    assert got["one_fewer"] == to_dict(expected)
    assert {k: v for k, v in got.items() if k != "one_fewer"} == json.loads(
        json.dumps(to_dict(res))
    )


def test_one_fewer_needs_one_variable_and_an_optimize_request() -> None:
    module = native_module()
    assert module is not None
    two = _base(
        variables=(Variable("land", 18, 26), Variable("ramp", 0, 4)), objective="max_probability"
    )
    two = replace(two, target=None)
    got = json.loads(
        module.probability_json(json.dumps({"optimize": to_dict(two), "one_fewer": True}))
    )
    assert got["kind"] == "malformed"
    got = json.loads(module.probability_json(json.dumps({"rule": "land >= 1", "one_fewer": True})))
    assert got["kind"] == "malformed"
