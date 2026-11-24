"""Rust core conformance: the model, compiler and probability facade the web app runs.

The web app runs the Rust core compiled to WebAssembly (ADR-0013). This suite sends
the JSON of ``mtgcalc.model.serialization.to_dict`` to the same Rust code through
``mtgcalc_native.probability_json`` and requires (FR-90, FR-91):

* the same exact answer as the pure-Python reference (``MTGCALC_ENGINE=python``), so
  neither the Rust compiler nor the Rust engine is trusted on its own;
* the same error, with Python's field path and message, for every invalid input;
* the same state-limit behaviour;
* the same text normalization for every Unicode code point.

Skipped when the optional ``mtgcalc_native`` extension is not installed.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mtgcalc import api
from mtgcalc.engine.base import DEFAULT_LIMIT
from mtgcalc.engine.select import native_module
from mtgcalc.errors import StateSpaceTooLargeError, ValidationError
from mtgcalc.model.conditions import And, At, Compare, Condition, Op, Or, Query
from mtgcalc.model.deck import Card, Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import AnyOf, Tag
from mtgcalc.model.serialization import from_dict, to_dict
from tests.strategies import multi_checkpoint_cases, plain_cases

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")

ROOT = Path(__file__).resolve().parents[2]
Json = dict[str, Any]


@contextmanager
def _python_engine() -> Iterator[None]:
    """Force the pure-Python reference engine for the duration of the block."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MTGCALC_ENGINE", "python")
        yield


def request(sc: Scenario | Json, q: Query | Json, limit: int | None = None) -> Json:
    """A request in the boundary format (objects are serialized, dicts sent as is)."""
    out: Json = {
        "scenario": sc if isinstance(sc, dict) else to_dict(sc),
        "query": q if isinstance(q, dict) else to_dict(q),
    }
    if limit is not None:
        out["limit"] = limit
    return out


def rust(req: Json) -> Json:
    """The Rust core's answer (round-tripped through JSON text, as the browser does)."""
    module = native_module()
    assert module is not None
    reply: Json = json.loads(module.probability_json(json.dumps(req)))
    return reply


def python(req: Json) -> Json:
    """The Python reference's answer in the same format (errors as the boundary's)."""
    try:
        with _python_engine():
            sc = from_dict(req["scenario"])
            q = from_dict(req["query"])
            res = api.probability(sc, q, limit=req.get("limit", DEFAULT_LIMIT))
    except ValidationError as e:
        return {"type": "Error", "kind": "validation", "field": e.field, "message": e.message}
    except StateSpaceTooLargeError:
        return {"type": "Error", "kind": "too_large"}
    out: Json = json.loads(json.dumps(to_dict(res)))
    return out


def assert_same(req: Json) -> Json:
    """Rust and Python agree on ``req``; returns the answer."""
    expected = python(req)
    got = rust(req)
    if expected.get("kind") == "too_large":
        assert got.get("kind") == "too_large", got
    else:
        assert got == expected
    return got


def exact(answer: Json) -> Fraction:
    assert answer["type"] == "Probability", answer
    return Fraction(answer["exact"]["value"])


# --------------------------------------------------------------------------------------
# Reference values (MATH §12), through the boundary
# --------------------------------------------------------------------------------------


def hyp(N: int, K: int, n: int, k: int) -> Fraction:
    return Fraction(comb(K, k) * comb(N - K, n - k), comb(N, n))


def ge(t: str, n: int) -> Compare:
    return Compare(Tag(t), ">=", n)


DRAW = GameConfig(on_play=False)


@pytest.mark.parametrize(
    ("scenario", "query", "expected"),
    [
        pytest.param(
            Scenario(Deck.from_counts(60, {"x": 4})),
            Query(ge("x", 1)),
            1 - hyp(60, 4, 7, 0),
            id="A1",
        ),
        pytest.param(
            Scenario(Deck.from_counts(60, {"x": 4}), DRAW),
            Query(ge("x", 1), turn=3),
            1 - hyp(60, 4, 10, 0),
            id="A4",
        ),
        pytest.param(
            Scenario(Deck.from_counts(60, {"a": 4, "b": 4})),
            Query(And((ge("a", 1), ge("b", 1)))),
            None,
            id="A6",
        ),
        pytest.param(
            Scenario(Deck.from_counts(60, {"land": 24})),
            Query(And((At(0, ge("land", 2)), At(4, ge("land", 4))))),
            Fraction(209193119, 335980515),
            id="A7",
        ),
    ],
)
def test_reference_values(scenario: Scenario, query: Query, expected: Fraction | None) -> None:
    got = exact(assert_same(request(scenario, query)))
    if expected is not None:
        assert got == expected


def test_a5_and_a8_match_the_math_table() -> None:
    lands = Scenario(Deck.from_counts(60, {"land": 24}))
    a5 = Query(And((At(0, ge("land", 1)), At(2, ge("land", 2)), At(3, ge("land", 3)))))
    assert float(exact(assert_same(request(lands, a5)))) == pytest.approx(0.78865447, abs=1e-8)
    red = Deck(
        (
            Card("Mountain", 14, frozenset({"land", "red"})),
            Card("Island", 10, frozenset({"land"})),
            Card("Spell", 36),
        )
    )
    a8 = Query(ge("red", 1), given=ge("land", 3), turn=2)
    answer = assert_same(request(Scenario(red, DRAW), a8))
    assert answer["type"] == "ConditionalResult"
    assert float(Fraction(answer["result"]["exact"]["value"])) == pytest.approx(
        0.9717531574, abs=1e-10
    )


# --------------------------------------------------------------------------------------
# Generated scenarios: identical answers
# --------------------------------------------------------------------------------------


@given(plain_cases())
def test_generated_queries(case: tuple[Scenario, Query]) -> None:
    got = assert_same(request(*case))
    assert got["type"] in ("Probability", "ConditionalResult")


@given(multi_checkpoint_cases())
def test_generated_multi_turn_queries(case: tuple[Scenario, Query]) -> None:
    assert_same(request(*case))


@st.composite
def web_cases(draw: st.DrawFn) -> tuple[Scenario, Query]:
    """Questions the way the web app builds them: card types with "also counts as"
    tags plus filler, a 40/60/99-card deck, and goal lines combined with all/any."""
    size = draw(st.sampled_from([40, 60, 99]))
    names = ["land", "ramp", "draw", "removal"]
    n_types = draw(st.integers(1, 4))
    cards = []
    left = size
    for name in names[:n_types]:
        n = draw(st.integers(0, min(left, 30)))
        left -= n
        if n:
            also = draw(st.frozensets(st.sampled_from(names), max_size=2))
            cards.append(Card(name, n, frozenset({name}) | also))
    if left:
        cards.append(Card("(other)", left, frozenset({"(other)"})))
    if not cards:
        cards.append(Card("(other)", size, frozenset({"(other)"})))
    deck = Deck(tuple(cards))
    game = GameConfig(on_play=draw(st.booleans()), draws_per_turn=draw(st.integers(0, 2)))
    lines: list[Condition] = []
    for _ in range(draw(st.integers(1, 3))):
        sel = draw(st.sampled_from([Tag(n) for n in names[:n_types]]))
        op: Op = draw(st.sampled_from(["==", "<=", ">="]))
        leaf = Compare(sel, op, draw(st.integers(0, 5)))
        lines.append(At(draw(st.integers(0, 6)), leaf))
    cond: Condition = lines[0]
    if len(lines) > 1:
        cond = And(tuple(lines)) if draw(st.booleans()) else Or(tuple(lines))
    return Scenario(deck, game), Query(cond)


@settings(max_examples=40)
@given(web_cases())
def test_web_app_shaped_questions(case: tuple[Scenario, Query]) -> None:
    assert_same(request(*case))


@settings(max_examples=40)
@given(plain_cases(), st.integers(1, 60))
def test_state_limit_triggers_identically(case: tuple[Scenario, Query], limit: int) -> None:
    """Both engines count live states the same way, so a small limit trips both or neither."""
    assert_same(request(*case, limit=limit))


# --------------------------------------------------------------------------------------
# Invalid input: the same error, field and message
# --------------------------------------------------------------------------------------

Mutation = Callable[[Json], None]


def _first_leaf(node: Json) -> Json:
    """The first Compare/Between leaf in pre-order (generated queries always have one)."""
    stack = [node]
    while stack:
        n = stack.pop(0)
        if n.get("type") in ("Compare", "Between"):
            return n
        for key in ("item", "a", "b"):
            if isinstance(n.get(key), dict):
                stack.append(n[key])
        stack.extend(x for x in n.get("items", []) if isinstance(x, dict))
    raise LookupError("no leaf")


def _card(req: Json) -> Json:
    card: Json = req["scenario"]["deck"]["cards"][0]
    return card


def _move_all(req: Json, zone: str) -> None:
    for c in req["scenario"]["deck"]["cards"]:
        c["zone"] = zone


def _game(req: Json) -> Json:
    game: Json = req["scenario"]["game"]
    return game


MUTATIONS: dict[str, Mutation] = {
    "quantity zero": lambda r: _card(r).update(quantity=0),
    "quantity negative": lambda r: _card(r).update(quantity=-3),
    "blank name": lambda r: _card(r).update(name="  \t "),
    "blank tag": lambda r: _card(r).update(tags={"type": "frozenset", "items": ["  "]}),
    "unknown zone": lambda r: _card(r).update(zone="graveyard"),
    "duplicate card": lambda r: r["scenario"]["deck"]["cards"].append(
        {**_card(r), "name": _card(r)["name"].upper() + "  "}
    ),
    "empty library": lambda r: _move_all(r, "sideboard"),
    "negative hand": lambda r: _game(r).update(hand_size=-1),
    "negative draws": lambda r: _game(r).update(draws_per_turn=-1),
    "override turn 0": lambda r: _game(r).update(draw_overrides=[[0, 1]]),
    "negative extra": lambda r: _game(r).update(extra_draws=[[2, -1]]),
    "duplicate turn": lambda r: _game(r).update(draw_overrides=[[2, 1], [2, 3]]),
    "hand too big": lambda r: _game(r).update(hand_size=1000),
    "negative query turn": lambda r: r["query"].update(turn=-1),
    "bad leaf": lambda r: _first_leaf(r["query"]["condition"]).update(
        {"op": "=>", "value": 1}
        if _first_leaf(r["query"]["condition"])["type"] == "Compare"
        else {"lo": 3, "hi": 1}
    ),
    "negative value": lambda r: _first_leaf(r["query"]["condition"]).update(
        {"value": -1} if _first_leaf(r["query"]["condition"])["type"] == "Compare" else {"lo": -1}
    ),
    "blank tag selector": lambda r: _first_leaf(r["query"]["condition"]).update(
        sel={"type": "Tag", "name": " "}
    ),
    "blank card selector": lambda r: _first_leaf(r["query"]["condition"]).update(
        sel={"type": "CardName", "name": ""}
    ),
    "unknown card": lambda r: _first_leaf(r["query"]["condition"]).update(
        sel={"type": "CardName", "name": "No Such Card"}
    ),
    "empty any_of": lambda r: _first_leaf(r["query"]["condition"]).update(
        sel={"type": "AnyOf", "items": []}
    ),
    "one-item and": lambda r: r["query"].update(
        condition={"type": "And", "items": [r["query"]["condition"]]}
    ),
    "negative at_least": lambda r: r["query"].update(
        condition={"type": "AtLeast", "n": -1, "items": [r["query"]["condition"]]}
    ),
    "empty exactly": lambda r: r["query"].update(
        condition={"type": "Exactly", "n": 1, "items": []}
    ),
    "empty assignable": lambda r: r["query"].update(
        condition={"type": "Assignable", "demands": []}
    ),
    "zero demand": lambda r: r["query"].update(
        condition={
            "type": "Assignable",
            "demands": [{"type": "Demand", "sel": {"type": "Everything"}, "need": 0}],
        }
    ),
    "negative at": lambda r: r["query"].update(
        condition={"type": "At", "turn": -2, "item": r["query"]["condition"]}
    ),
}


def _has_leaf(req: Json) -> bool:
    try:
        _first_leaf(req["query"]["condition"])
    except LookupError:
        return False
    return True


#: Mutations that edit the first Compare/Between leaf (skipped when there is none).
NEEDS_LEAF = {
    "bad leaf",
    "negative value",
    "blank tag selector",
    "blank card selector",
    "unknown card",
    "empty any_of",
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
@settings(max_examples=12)
@given(case=plain_cases())
def test_invalid_input_gets_pythons_error(case: tuple[Scenario, Query], name: str) -> None:
    """Each mutation runs as its own test, so every kind of invalid input is exercised
    on every run (sampling the mutation inside one test left some untested)."""
    req = request(*case)
    assume(name not in NEEDS_LEAF or _has_leaf(req))
    MUTATIONS[name](req)
    expected = python(copy.deepcopy(req))
    assert expected["kind"] == "validation", (name, expected)
    assert rust(req) == expected


@pytest.mark.parametrize(
    "fragment",
    [
        {"query": {"type": "Query", "condition": {"type": "Maybe"}}},
        {"query": {"type": "Query", "condition": {"type": "Const", "value": True, "x": 1}}},
        {"scenario": {"type": "Scenario"}},
        {"query": {"type": "Query", "condition": {"type": "Const", "value": "yes"}}},
    ],
)
def test_malformed_requests_are_rejected_without_crashing(fragment: Json) -> None:
    base = request(Scenario(Deck.from_counts(60, {"land": 24})), Query(ge("land", 1)))
    base.update(fragment)
    assert rust(base)["kind"] == "malformed"


def test_overlapping_selectors_with_any_of() -> None:
    deck = Deck(
        (
            Card("Forest", 16, frozenset({"land"})),
            Card("Elf", 8, frozenset({"ramp", "creature"})),
            Card("Arbor", 1, frozenset({"land", "creature"})),
            Card("Spell", 35),
        )
    )
    ramp_or_creature = Compare(AnyOf((Tag("ramp"), Tag("creature"))), ">=", 1)
    cond = Or((At(2, ge("land", 3)), At(1, ramp_or_creature)))
    assert_same(request(Scenario(deck), Query(cond)))


# --------------------------------------------------------------------------------------
# Text normalization: every code point
# --------------------------------------------------------------------------------------


def _py_normalize(s: str) -> str:
    return " ".join(s.split()).casefold()


def test_normalization_matches_python_for_every_code_point() -> None:
    module = native_module()
    assert module is not None
    chars = [chr(c) for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF]
    # One call per block of characters keeps this fast; each block is checked as a whole
    # and, around every character, with whitespace and letters.
    for i in range(0, len(chars), 4096):
        block = chars[i : i + 4096]
        text = "x".join(block)
        assert module.normalize_text(text) == _py_normalize(text)
        assert module.normalize_text(" A ".join(block)) == _py_normalize(" A ".join(block))
    for c in chars:
        if c.isspace() or c.casefold() != c:
            assert module.normalize_text(f" {c}Ab{c} ") == _py_normalize(f" {c}Ab{c} "), hex(ord(c))


@given(st.text())
def test_normalization_matches_python_on_random_text(text: str) -> None:
    module = native_module()
    assert module is not None
    assert module.normalize_text(text) == _py_normalize(text)


def test_unicode_tables_are_fresh() -> None:
    module = native_module()
    assert module is not None
    if unicodedata.unidata_version != module.UNICODE_VERSION:
        pytest.skip("tables come from another Unicode version; code points are checked above")
    tool = ROOT / "native" / "core" / "tools" / "gen_unicode.py"
    command = [sys.executable, str(tool), "--check"]
    done = subprocess.run(command, check=False, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
