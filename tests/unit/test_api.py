"""Unit tests: facade and serialization (LLD §3.8, §8)."""

from __future__ import annotations

import ast
import json
from fractions import Fraction
from pathlib import Path

import pytest

import mtgcalc
from mtgcalc import (
    Deck,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    Query,
    Scenario,
    count,
    hypergeom,
    mulligan_report,
    parse_condition,
    probability,
    tag,
)
from mtgcalc.errors import StateSpaceTooLargeError, ValidationError
from mtgcalc.model.results import ConditionalResult, Probability
from mtgcalc.model.serialization import from_dict, register, to_dict

DECK = Deck.from_counts(60, {"land": 24, "key": 4})


def test_hypergeom_fast_path() -> None:
    d = hypergeom(60, 4, 7)
    assert sum(d.pmf) == 1 and len(d.pmf) == 5
    with pytest.raises(ValidationError):
        hypergeom(10, 11, 2)


def test_probability_accepts_all_query_forms() -> None:
    sc = Scenario(DECK)
    text = probability(sc, "land >= 3")
    cond = probability(sc, count("land") >= 3)
    query = probability(sc, Query(count("land") >= 3))
    assert text == cond == query


def test_conditional_probability_and_undefined() -> None:
    sc = Scenario(DECK)
    res = probability(sc, "key >= 1 GIVEN land >= 2")
    assert isinstance(res, ConditionalResult) and res.defined and res.result is not None
    assert res.result.exact == res.joint.exact / res.given.exact  # type: ignore[operator]
    undefined = probability(sc, "key >= 1 GIVEN key >= 5")
    assert isinstance(undefined, ConditionalResult) and not undefined.defined


def test_montecarlo_and_auto_fallback() -> None:
    sc = Scenario(DECK)
    mc = probability(sc, "land >= 3 @T3", engine="montecarlo", trials=2000, seed=3)
    assert isinstance(mc, Probability) and mc.method == "montecarlo" and mc.ci95 is not None
    auto = probability(sc, "land >= 3 @T3", engine="auto", limit=1, trials=2000, seed=3)
    assert isinstance(auto, Probability) and auto.method == "montecarlo" and auto.warnings
    exact = probability(sc, "land >= 3 @T3", engine="auto")
    assert isinstance(exact, Probability) and exact.method == "exact"
    cond = probability(sc, "key >= 1 GIVEN land >= 2", engine="montecarlo", trials=2000, seed=1)
    assert isinstance(cond, ConditionalResult) and cond.result is not None
    assert cond.result.method == "montecarlo"


def test_auto_stays_exact_unless_the_engine_hits_the_limit() -> None:
    sc = Scenario(DECK)
    q = "land >= 3 @T5 AND key >= 1"
    small = probability(sc, q, engine="auto", limit=40)  # needs < 40 live states
    assert isinstance(small, Probability) and small.method == "exact"
    big = probability(sc, q, engine="auto", limit=3, trials=500, seed=1)
    assert isinstance(big, Probability) and big.method == "montecarlo" and big.warnings
    with pytest.raises(StateSpaceTooLargeError):
        probability(sc, q, engine="exact", limit=3)


def test_montecarlo_under_mulligan() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("key")),), count("key") >= 1, 1)
    sc = Scenario(DECK, mulligan=cfg)
    mc = probability(sc, "key >= 1", engine="montecarlo", trials=4000, seed=11)
    ex = probability(sc, "key >= 1")
    assert isinstance(mc, Probability) and isinstance(ex, Probability) and mc.ci95 is not None
    lo, hi = mc.ci95
    assert lo - 0.02 <= ex.value <= hi + 0.02


def test_probability_value_property() -> None:
    assert Probability(Fraction(1, 4)).value == 0.25
    assert Probability(None, 0.3).value == 0.3
    with pytest.raises(ValidationError):
        Probability(None)


def test_string_success_conditions() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("key")),), count("key") >= 1, 1)
    rep = mulligan_report(Scenario(DECK, mulligan=cfg), "key >= 1")
    assert rep.p_success > 0


@pytest.mark.parametrize(
    "obj",
    [
        DECK,
        GameConfig(on_play=False, extra_draws={3: 2}),
        MulliganConfig((PriorityGroup(tag("land"), 2, "lands"),), count("land") >= 2, 3, 1),
        Query(parse_condition("assign(land>=2, key>=1) @T2 OR NOT key in 0..1")),
        Scenario(DECK, GameConfig(), MulliganConfig((PriorityGroup(tag("land")),))),
        Probability(Fraction(3, 7)),
    ],
)
def test_serialization_round_trip(obj: object) -> None:
    data = json.loads(json.dumps(to_dict(obj)))
    assert from_dict(data) == obj


def test_serialization_results_round_trip() -> None:
    rep = mulligan_report(
        Scenario(DECK, mulligan=MulliganConfig((PriorityGroup(tag("key")),), max_mulligans=1)),
        "key >= 1",
    )
    assert from_dict(json.loads(json.dumps(to_dict(rep)))) == rep


def test_serialization_errors() -> None:
    with pytest.raises(ValidationError):
        to_dict(object())
    with pytest.raises(ValidationError):
        from_dict({"type": "Nope"})
    assert register(int) is int


def test_public_api_exports() -> None:
    for name in mtgcalc.__all__:
        assert hasattr(mtgcalc, name)


def test_no_eval_or_exec_in_source() -> None:
    """NFR-14: parsers must never evaluate input as code."""
    src = Path(mtgcalc.__file__).parent
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile"}, path
