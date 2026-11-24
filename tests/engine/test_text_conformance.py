"""Rust core conformance, port stage 2 (ADR-0013 §2): the rule language and decklists.

For any text, the Rust parsers must give what Python's ``mtgcalc.io`` gives: the same
query or deck (compared as ``to_dict`` JSON), or the same error (a ``ParseError`` with the
same message, line and column, or a ``ValidationError`` with the same field and message).
The printer must write the same text as ``format_query``.

Text is generated from fragments chosen to hit every branch of both grammars, including
Python-specific Unicode behaviour: non-ASCII digits, Python-only whitespace, line
separators, and the characters ``(?i)`` matches with ASCII letters.

Skipped when the optional ``mtgcalc_native`` extension is not installed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mtgcalc.engine.select import native_module
from mtgcalc.errors import ParseError, StateSpaceTooLargeError, ValidationError
from mtgcalc.io.decklist import parse_decklist
from mtgcalc.io.expr import format_query, parse_query
from mtgcalc.model.conditions import Query
from mtgcalc.model.game import GameConfig
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.serialization import to_dict
from tests.engine.test_core_conformance import python as python_probability
from tests.strategies import conditions, decks

pytestmark = pytest.mark.skipif(native_module() is None, reason="mtgcalc_native not built")

Json = dict[str, Any]
I64_MAX = 2**63 - 1


def _native() -> Any:
    module = native_module()
    assert module is not None
    return module


def _call(name: str, *args: Any) -> Json:
    """A native JSON entry point's reply, decoded."""
    reply: Json = json.loads(getattr(_native(), name)(*args))
    return reply


def _error(e: Exception) -> Json:
    if isinstance(e, ParseError):
        return {"kind": "parse", "message": e.message, "line": e.line, "column": e.column}
    assert isinstance(e, ValidationError)
    return {"kind": "validation", "field": e.field, "message": e.message}


def _rust_error(reply: Json) -> Json:
    keep = (
        ("kind", "message", "line", "column")
        if reply["kind"] == "parse"
        else ("kind", "field", "message")
    )
    return {k: reply[k] for k in keep}


def _fits(data: Any) -> bool:
    """No integer beyond 64 bits (Rust saturates those; Python keeps them exactly)."""
    if isinstance(data, bool):
        return True
    if isinstance(data, int):
        return data <= I64_MAX
    if isinstance(data, dict):
        return all(_fits(v) for v in data.values())
    if isinstance(data, list):
        return all(_fits(v) for v in data)
    return True


def assert_same_rule(text: str, turn: int = 0) -> Json:
    try:
        expected: Json = json.loads(json.dumps(to_dict(parse_query(text, turn))))
    except (ParseError, ValidationError) as e:
        got = _call("parse_rule_json", text, turn)
        assert got["type"] == "Error", (text, got)
        assert _rust_error(got) == _error(e), text
        return got
    if not _fits(expected):
        return expected
    got = _call("parse_rule_json", text, turn)
    assert got == expected, text
    return got


def assert_same_deck(text: str) -> Json:
    try:
        expected: Json = json.loads(json.dumps(to_dict(parse_decklist(text))))
    except (ParseError, ValidationError) as e:
        got = _call("parse_deck_json", text)
        assert got["type"] == "Error", (text, got)
        assert _rust_error(got) == _error(e), text
        return got
    if not _fits(expected):
        return expected
    got = _call("parse_deck_json", text)
    if got.get("kind") == "unsupported":
        # The documented limit of the Rust engine (16-bit counts, ADR-0013 §3).
        library = sum(c["quantity"] for c in expected["cards"] if c["zone"] == "library")
        assert library > 65_535, (text, got)
        return got
    assert got == expected, text
    return got


# --------------------------------------------------------------------------------------
# The rule language
# --------------------------------------------------------------------------------------

RULES = [
    "land >= 3",
    "land >= 3 @T3 AND removal >= 1 @T3",
    "(land >= 3 AND ramp >= 1) @T2",
    "land >= 3 @t3 or ramp>=1 @ turn 2",
    "NOT NOT a == 1",
    "a < 1 XOR b > 2 XOR c != 0",
    "a >= 1 -> b >= 1 -> c >= 1",
    "a >= 1 implies b >= 1",
    "land in 2..4",
    'card:"Sol Ring" >= 1',
    'tag:"mana rock" >= 1 AND tag:"a\\"b\\\\c" == 0',
    "any(ramp, draw) >= 2",
    "all(land, ramp) >= 1",
    "none(land, any(a, b)) >= 4",
    "everything >= 9",
    "atleast(2, a >= 1, b >= 1, c >= 1)",
    "exactly(0, a >= 1)",
    "assign(land >= 3, ramp >= 1)",
    "true AND false OR TRUE",
    "a >= 1 GIVEN b >= 2",
    "land >= ٣",
    "land　>=\u001c3",
    "mana-rock >= 1 AND urza's >= 1",
]

BAD_RULES = [
    "",
    "land >=",
    "land ! 3",
    "and >= 1",
    "land in 4..2",
    "land >= 1 @x",
    "land >= 1 @",
    "atleast(1)",
    'tag:"  " >= 1',
    'card:"" >= 1',
    '"open',
    '"esc\\\n" >= 1',
    "a >= 1 GIVEN b >= 1 GIVEN c >= 1",
    "assign(a >= 0)",
    "assign(a > 1)",
    "(a >= 1",
    "a >= 1)",
    "any() >= 1",
    "a -",
    "a >= 1 ;",
    "\x00",
    "é >= 1",
    "(" * 70 + "a >= 1" + ")" * 70,
    "NOT " * 70 + "a >= 1",
    "x" * 10_001,
]


@pytest.mark.parametrize("text", RULES + BAD_RULES)
def test_rules_parse_like_python(text: str) -> None:
    assert_same_rule(text)


@pytest.mark.parametrize("turn", [0, 3, -1])
def test_the_default_turn_is_passed_through(turn: int) -> None:
    assert_same_rule("land >= 3 OR ramp >= 1 @T1", turn)


FRAGMENTS = [
    "land",
    "Ramp",
    "a",
    "b_c",
    "x-y",
    "z'",
    "t3",
    "T12",
    "turn",
    "and",
    "OR",
    "xor",
    "not",
    "implies",
    "given",
    "true",
    "false",
    "in",
    "atleast",
    "exactly",
    "assign",
    "any",
    "all",
    "none",
    "everything",
    "tag",
    "card",
    ">=",
    "<=",
    "==",
    "!=",
    "<",
    ">",
    "->",
    "..",
    "(",
    ")",
    ",",
    "@",
    ":",
    '"',
    '"Sol Ring"',
    '"a\\"b"',
    "0",
    "1",
    "3",
    "12",
    "٣",
    " ",
    "  ",
    "\t",
    "　",
    "\u001c",
    "\n",
    "-",
    ".",
    "!",
    "é",
    "#",
]


@settings(max_examples=600)
@given(st.lists(st.sampled_from(FRAGMENTS), max_size=14))
def test_any_text_parses_like_python(parts: list[str]) -> None:
    assert_same_rule("".join(parts))


@settings(max_examples=300)
@given(st.text(max_size=40))
def test_arbitrary_unicode_parses_like_python(text: str) -> None:
    assert_same_rule(text)


@settings(max_examples=400)
@given(decks().flatmap(lambda d: st.tuples(conditions(d, 6), st.none() | conditions(d, 6))))
def test_printed_rules_match_python_and_read_back(case: tuple[Any, Any]) -> None:
    cond, given_ = case
    q = Query(cond, given_)
    text = format_query(q)
    got = _call("format_rule_json", json.dumps(to_dict(q)))
    assert got == {"type": "Rule", "text": text}
    assert assert_same_rule(text) == json.loads(json.dumps(to_dict(q)))


# --------------------------------------------------------------------------------------
# Decklists
# --------------------------------------------------------------------------------------

DECKS = [
    "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n4x Lightning Bolt (M11) 149 *F*\n"
    "1 Sol Ring #ramp #!artifact\n1x Arcane Signet [Ramp,Mana Rock{top}]\n"
    "2 Forest\n2 FOREST #land\n// a comment\nSideboard:\n1 Pyroblast\n1 Duress [Maybeboard]\n",
    "4 x Bolt\n4 xavier\n4 X  Bolt",
    "4 x",
    "٣ Bolt",
    "ſideboard\n1 A\nDECK:\n1 B",
    "maın\n1 A",
    "// Commanders :\n1 A",
    "1 Bolt (2X2) 117a\n1 Shock (SLD) 12★\n1 Spark (X) 1\n1 Jolt (ABCDEFG) 1",
    "1 A#b #c#d #!",
    "1 A ^Tag^ ^open\n1 B [x{y}, ,{z}] [unclosed",
    "1 A\r\n1 B  1 C\x85\n\n",
    "1 Sol Ring #ramp\n1 sol  ring #rock",
    "Bolt",
    "4x",
    "0 Bolt",
    "4 #ramp",
    "",
    "\n\n  \n",
    "Commander\n1 A",
    "1 A\n" * 3,
    "99999999999 Forest",
]


@pytest.mark.parametrize("text", DECKS)
def test_decklists_parse_like_python(text: str) -> None:
    assert_same_deck(text)


LINE_PARTS = [
    "1",
    "4",
    "0",
    "٣",
    "12",
    "x",
    "X",
    " ",
    "  ",
    "\t",
    "　",
    "\u001c",
    "Lightning",
    "Bolt",
    "sol ring",
    "Atraxa,",
    "Voice",
    "(M11)",
    "(SLD)",
    "(X)",
    "149",
    "12★",
    "117a",
    "*F*",
    "*f*",
    "#ramp",
    "#!artifact",
    "#",
    "#!",
    "[Ramp]",
    "[Ramp,Mana Rock{top}]",
    "[Sideboard]",
    "[Commander]",
    "[deck]",
    "[",
    "]",
    "{",
    "}",
    "^Tag^",
    "^",
    "//",
    ":",
]
HEADERS = [
    "Commander",
    "Commanders",
    "Deck",
    "MAIN",
    "mainboard",
    "Sideboard:",
    "// Maybeboard",
    "companion",
    "ſideboard",
    "deck2",
    "  deck  :  ",
]


@st.composite
def decklists(draw: st.DrawFn) -> str:
    lines = []
    for _ in range(draw(st.integers(1, 6))):
        if draw(st.integers(0, 5)) == 0:
            lines.append(draw(st.sampled_from(HEADERS)))
        else:
            lines.append(
                "".join(draw(st.lists(st.sampled_from(LINE_PARTS), min_size=1, max_size=7)))
            )
    sep = draw(st.sampled_from(["\n", "\r\n", " ", "\n\n"]))
    return sep.join(lines)


@settings(max_examples=800)
@given(decklists())
def test_generated_decklists_parse_like_python(text: str) -> None:
    assert_same_deck(text)


@settings(max_examples=300)
@given(st.text(max_size=60))
def test_arbitrary_text_decklists_parse_like_python(text: str) -> None:
    assert_same_deck(text)


def test_size_limits_match_python() -> None:
    assert_same_deck("1 A\n" * 300_000)


# --------------------------------------------------------------------------------------
# Questions given as text, end to end
# --------------------------------------------------------------------------------------

DECKLIST = (
    "36 Forest #land\n2 Mosswort Bridge #land #ramp\n10 Llanowar Elves #ramp\n"
    "1 Sol Ring #ramp\n50 Bear\n"
)


@pytest.mark.parametrize(
    ("rule", "turn"),
    [
        ("land >= 3", 3),
        ('land >= 3 @T3 AND card:"sol ring" >= 1 @T2', 0),
        ("assign(land >= 2, ramp >= 1) GIVEN land >= 2 @T0", 2),
        ("ramp >= 1 @T2 OR land in 4..5 @T4", 0),
        ("land >=", 0),
        ('card:"Black Lotus" >= 1', 0),
    ],
)
def test_text_questions_answer_like_python(rule: str, turn: int) -> None:
    game = GameConfig(on_play=False)
    request = {"decklist": DECKLIST, "game": to_dict(game), "rule": rule, "turn": turn}
    try:
        expected_req = {
            "scenario": to_dict(Scenario(parse_decklist(DECKLIST), game)),
            "query": to_dict(parse_query(rule, turn)),
        }
    except ParseError as e:
        got = _call("probability_json", json.dumps(request))
        assert _rust_error(got) == _error(e)
        return
    expected = python_probability(expected_req)
    got = _call("probability_json", json.dumps(request))
    if expected.get("kind") == "too_large":  # pragma: no cover - not expected for these
        assert got["kind"] == "too_large"
    else:
        assert got == expected


@pytest.mark.parametrize(
    "request_",
    [
        {"decklist": "1 A", "scenario": {}, "rule": "a >= 1"},
        {"decklist": "1 A"},
        {
            "decklist": "1 A",
            "rule": "a >= 1",
            "query": {"type": "Query", "condition": {"type": "Const", "value": True}},
        },
        {
            "scenario": {"type": "Scenario", "deck": {"type": "Deck", "cards": []}},
            "game": {},
            "rule": "x",
        },
        {
            "decklist": "1 A",
            "query": {"type": "Query", "condition": {"type": "Const", "value": True}},
            "turn": 2,
        },
    ],
)
def test_ambiguous_requests_are_malformed(request_: Json) -> None:
    got = _call("probability_json", json.dumps(request_))
    assert got["kind"] == "malformed"


def test_state_limit_errors_are_not_swallowed_for_text_requests() -> None:
    request = {"decklist": DECKLIST, "rule": "land >= 1 @T9 AND ramp >= 1 @T9", "limit": 1}
    got = _call("probability_json", json.dumps(request))
    assert got["kind"] == "too_large"
    _ = StateSpaceTooLargeError  # the Python counterpart, for the reader
