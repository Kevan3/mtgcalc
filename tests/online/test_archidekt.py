"""Archidekt JSON -> Deck, on saved (trimmed) API responses. No network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mtgcalc import parse_decklist
from mtgcalc.io.decklist import format_decklist
from mtgcalc_online import DeckFetchError
from mtgcalc_online.archidekt import to_deck

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def test_edge_cases() -> None:
    deck = to_deck(load("archidekt_edge.json"))
    cards = {c.name: c for c in deck.cards}
    assert deck.name == "Edge cases"
    assert cards["Atraxa, Praetors' Voice"].zone == "commander"
    assert cards["Forest"].quantity == 35  # two printings merged
    assert cards["Forest"].tags == frozenset({"land"})
    assert cards["Sol Ring"].tags == frozenset({"mana rock", "ramp"})  # every category is a tag
    assert cards["Llanowar Elves"].tags == frozenset()  # uncategorized -> library
    assert cards["Black Lotus"].zone == "maybeboard"  # category not included in the deck
    assert "Swamp" not in cards  # deleted
    # a category named "Sideboard" that the deck includes keeps its cards in the library
    assert cards["Swords to Plowshares"].zone == "library"
    assert cards["Swords to Plowshares"].tags == frozenset({"sideboard", "removal"})
    assert deck.size == 38


def test_real_commander_deck() -> None:
    data = load("archidekt_commander.json")
    deck = to_deck(data)
    live = [c for c in data["cards"] if not c.get("deletedAt")]
    assert sum(c.quantity for c in deck.cards) == sum(c["quantity"] for c in live)
    assert [c.zone for c in deck.cards].count("commander") == 1
    assert deck.tag_counts()["removal"] == 10  # categories become tags


def test_imported_deck_survives_the_text_round_trip() -> None:
    deck = to_deck(load("archidekt_commander.json"))
    again = parse_decklist(format_decklist(deck))
    assert {(c.name, c.quantity, c.zone) for c in again.cards} == {
        (c.name, c.quantity, c.zone) for c in deck.cards
    }
    assert again.size == deck.size


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"name": "x"},
        {"cards": [{"quantity": 1}]},
        {"cards": [{"quantity": "many", "card": {"oracleCard": {"name": "A"}}}]},
        {"cards": []},
    ],
)
def test_unreadable_data_is_a_friendly_error(data: Any) -> None:
    with pytest.raises(DeckFetchError):
        to_deck(data)
