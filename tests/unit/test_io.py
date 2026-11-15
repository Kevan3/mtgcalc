"""Unit tests: decklist and condition-text parsers (LLD §7)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mtgcalc import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Card,
    Compare,
    Const,
    Deck,
    Demand,
    Exactly,
    Implies,
    Not,
    Or,
    Xor,
    card,
    tag,
)
from mtgcalc.errors import ParseError
from mtgcalc.io.decklist import TextImporter, format_decklist, parse_decklist, tag_token
from mtgcalc.io.expr import (
    MAX_DEPTH,
    format_condition,
    format_selector,
    parse_condition,
    parse_query,
)
from mtgcalc.model.selectors import AllOf, AnyOf, Everything, NoneOf

# --- decklists --------------------------------------------------------------------------
MOXFIELD = """
Commander
1 Atraxa, Praetors' Voice (2X2) 190 #!legend

Deck
1 Sol Ring (CMR) 472 #ramp #!artifact
35 Forest #land
1 Breeding Pool (RNA) 246 *F* #land #fixing
// a comment
1 sol ring #fast

Sideboard
2 Pithing Needle
"""

ARCHIDEKT = """
1x Atraxa, Praetors' Voice [Commander{top}]
1x Arcane Signet [Ramp,Mana Rock{top}] ^Have,#37d67a^
36x Forest [Land]
1x Thing [Maybeboard]
"""


def test_moxfield_format() -> None:
    deck = parse_decklist(MOXFIELD)
    assert deck.size == 38
    sol = deck.card("Sol Ring")
    assert sol.quantity == 2 and sol.tags == frozenset({"ramp", "artifact", "fast"})
    assert deck.card("Breeding Pool").tags == frozenset({"land", "fixing"})
    assert deck.card("Atraxa, Praetors' Voice").zone == "commander"
    assert deck.card("Pithing Needle").zone == "sideboard"


def test_archidekt_format() -> None:
    deck = parse_decklist(ARCHIDEKT)
    assert deck.size == 37
    assert deck.card("Arcane Signet").tags == frozenset({"ramp", "mana rock"})
    assert deck.card("Atraxa, Praetors' Voice").zone == "commander"
    assert deck.card("Thing").zone == "maybeboard"


def test_plain_format_and_importer() -> None:
    deck = TextImporter("plain").parse("4 Lightning Bolt\n4x Counterspell\n52 Island")
    assert deck.size == 60 and deck.card("Counterspell").quantity == 4


@pytest.mark.parametrize(
    ("text", "line"),
    [("4 Bolt\nBolt", 2), ("0 Bolt", 1), ("", 1), ("4 #tag", 1), ("4 [Land]", 1)],
)
def test_decklist_errors_report_lines(text: str, line: int) -> None:
    with pytest.raises(ParseError) as e:
        parse_decklist(text)
    assert e.value.line == line


def test_decklist_size_limit() -> None:
    with pytest.raises(ParseError):
        parse_decklist("1 A\n" * 300_000)


# --- expressions -------------------------------------------------------------------------
LAND, RAMP = tag("land"), tag("ramp")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("land >= 3", Compare(LAND, ">=", 3)),
        ("LAND>=3", Compare(LAND, ">=", 3)),
        ("land in 2..4", Between(LAND, 2, 4)),
        ('card:"Sol Ring" == 1', Compare(card("Sol Ring"), "==", 1)),
        ('tag:"mana rock" != 0', Compare(tag("mana rock"), "!=", 0)),
        ("any(land, ramp) > 0", Compare(AnyOf((LAND, RAMP)), ">", 0)),
        ("all(land, ramp) < 1", Compare(AllOf((LAND, RAMP)), "<", 1)),
        ("none(land) <= 2", Compare(NoneOf((LAND,)), "<=", 2)),
        ("everything >= 7", Compare(Everything(), ">=", 7)),
        ("true", Const(True)),
        ("land >= 1 @T3", At(3, Compare(LAND, ">=", 1))),
        ("land >= 1 @ turn 3", At(3, Compare(LAND, ">=", 1))),
        ("land >= 1 @3", At(3, Compare(LAND, ">=", 1))),
        ("assign(land >= 3, ramp >= 1)", Assignable((Demand(LAND, 3), Demand(RAMP, 1)))),
        (
            "atleast(2, true, false, land >= 1)",
            AtLeast(2, (Const(True), Const(False), Compare(LAND, ">=", 1))),
        ),
        ("exactly(1, true)", Exactly(1, (Const(True),))),
        ("mana-rock >= 1", Compare(tag("mana-rock"), ">=", 1)),
    ],
)
def test_parse_primaries(text: str, expected: object) -> None:
    assert parse_condition(text) == expected


def test_precedence() -> None:
    a, b, c = (Compare(t, ">=", 1) for t in (tag("a"), tag("b"), tag("c")))
    assert parse_condition("a>=1 OR b>=1 AND c>=1") == Or((a, And((b, c))))
    assert parse_condition("NOT a>=1 AND b>=1") == And((Not(a), b))
    assert parse_condition("a>=1 XOR b>=1 OR c>=1") == Or((Xor(a, b), c))
    assert parse_condition("a>=1 -> b>=1 -> c>=1") == Implies(a, Implies(b, c))
    assert parse_condition("a>=1 IMPLIES b>=1") == Implies(a, b)
    assert parse_condition("a>=1 XOR b>=1 XOR c>=1") == Xor(Xor(a, b), c)
    assert parse_condition("(a>=1 AND b>=1) @T2") == At(2, And((a, b)))


def test_query_given() -> None:
    q = parse_query("land >= 1 GIVEN ramp >= 1", turn=2)
    assert q.given == Compare(RAMP, ">=", 1) and q.turn == 2
    with pytest.raises(ParseError):
        parse_condition("land >= 1 GIVEN ramp >= 1")


@pytest.mark.parametrize(
    "text",
    [
        "land >=",
        "land 3",
        ">= 3",
        "land >= 1 AND",
        "(land >= 1",
        "land >= 1)",
        "and >= 1",
        "land in 4..2",
        "land >= 1 @",
        "land >= 1 @X",
        "atleast(1)",
        "assign(land >= 0)",
        'tag:"" >= 1',
        "land >= 1 $",
        "any() >= 1",
    ],
)
def test_parse_errors(text: str) -> None:
    with pytest.raises(ParseError) as e:
        parse_condition(text)
    assert e.value.column >= 1


def test_error_column_points_at_token() -> None:
    with pytest.raises(ParseError) as e:
        parse_condition("land >= x")
    assert e.value.column == 9


def test_limits() -> None:
    with pytest.raises(ParseError):
        parse_condition("(" * (MAX_DEPTH + 5) + "land >= 1" + ")" * (MAX_DEPTH + 5))
    with pytest.raises(ParseError):
        parse_condition("NOT " * 200 + "land >= 1")
    with pytest.raises(ParseError):
        parse_condition("land >= 1 AND " * 1000 + "land >= 1")


def test_format_selector_quotes_when_needed() -> None:
    assert format_selector(tag("land")) == "land"
    assert format_selector(tag("mana rock")) == 'tag:"mana rock"'
    assert format_selector(tag("and")) == 'tag:"and"'
    assert format_selector(tag("t3")) == 'tag:"t3"'
    assert format_selector(card('Say "hi"')) == 'card:"Say \\"hi\\""'


def test_format_examples() -> None:
    a, b = Compare(LAND, ">=", 1), Compare(RAMP, ">=", 1)
    assert format_condition(And((a, Or((a, b))))) == "land >= 1 AND (land >= 1 OR ramp >= 1)"
    assert format_condition(Not(At(2, a))) == "NOT land >= 1 @T2"
    assert format_condition(At(3, At(2, a))) == "(land >= 1 @T2) @T3"
    assert format_condition(Implies(Implies(a, b), a)) == "(land >= 1 -> ramp >= 1) -> land >= 1"


# --- decklist writing -------------------------------------------------------------------


_NAMES = st.from_regex(r"[A-Z][a-z]{1,8}(?:,? [A-Z][a-z']{1,8}){0,2}", fullmatch=True)
_TAGS = st.frozensets(st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True), max_size=3)


@st.composite
def decks(draw: st.DrawFn) -> Deck:
    names = draw(st.lists(_NAMES, min_size=1, max_size=6, unique_by=str.casefold))
    zones = ["library"] + [
        draw(st.sampled_from(["library", "commander", "sideboard", "maybeboard"]))
        for _ in names[1:]
    ]
    return Deck(
        tuple(
            Card(n, draw(st.integers(1, 20)), draw(_TAGS), z)  # type: ignore[arg-type]
            for n, z in zip(names, zones, strict=True)
        )
    )


@given(decks())
def test_format_decklist_round_trips(deck: Deck) -> None:
    def contents(d: Deck) -> list[tuple[str, str, int, frozenset[str]]]:
        return sorted((c.zone, c.name, c.quantity, c.tags) for c in d.cards)

    assert contents(parse_decklist(format_decklist(deck))) == contents(deck)


def test_format_decklist_layout_and_tag_tokens() -> None:
    deck = Deck(
        (
            Card("Forest", 36, frozenset({"land"})),
            Card("Atraxa", 1, zone="commander"),
            Card("Sol Ring", 1, frozenset({"mana rock", "sideboard"})),
        )
    )
    assert format_decklist(deck) == (
        "Commander\n1 Atraxa\n\nDeck\n36 Forest #land\n1 Sol Ring #mana-rock #sideboard\n"
    )
    assert tag_token("Mana  Rock") == "Mana-Rock" and tag_token("#x y") == "x-y"
