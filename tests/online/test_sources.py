"""Link recognition and dispatch, with a fake HTTP getter. No network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mtgcalc_online import DeckFetchError, fetch_deck, recognize

EDGE = json.loads((Path(__file__).parent / "fixtures" / "archidekt_edge.json").read_text())


@pytest.mark.parametrize(
    ("link", "source", "deck_id"),
    [
        ("https://archidekt.com/decks/123456/my-deck", "Archidekt", "123456"),
        ("https://www.archidekt.com/decks/123456", "Archidekt", "123456"),
        ("  http://archidekt.com/decks/42/?tab=stats#top  ", "Archidekt", "42"),
        ("https://archidekt.com/api/decks/7/", "Archidekt", "7"),
        (
            "https://www.moxfield.com/decks/oEWXWHM5eEGMmopExLWRCA",
            "Moxfield",
            "oEWXWHM5eEGMmopExLWRCA",
        ),
        ("https://moxfield.com/decks/abc-DEF_1/primer", "Moxfield", "abc-DEF_1"),
    ],
)
def test_recognize(link: str, source: str, deck_id: str) -> None:
    found, found_id = recognize(link)
    assert (found.name, found_id) == (source, deck_id)


@pytest.mark.parametrize(
    "link",
    [
        "",
        "hello",
        "https://archidekt.com/decks/not-a-number",
        "https://evil.example/archidekt.com/decks/1",
        "https://archidekt.com.evil.example/decks/1",
        "ftp://archidekt.com/decks/1",
        "https://tappedout.net/mtg-decks/x/",
    ],
)
def test_other_text_is_rejected_before_any_request(link: str) -> None:
    def must_not_fetch(url: str) -> Any:
        raise AssertionError(f"fetched {url}")

    with pytest.raises(DeckFetchError, match="not a deck link"):
        fetch_deck(link, get=must_not_fetch)


def test_archidekt_fetch_uses_the_api_url() -> None:
    requested: list[str] = []

    def fake_get(url: str) -> Any:
        requested.append(url)
        return EDGE

    deck = fetch_deck("https://archidekt.com/decks/42/edge-cases", get=fake_get)
    assert requested == ["https://archidekt.com/api/decks/42/"]
    assert deck.name == "Edge cases"


def test_moxfield_explains_the_text_export_without_fetching() -> None:
    def must_not_fetch(url: str) -> Any:
        raise AssertionError(f"fetched {url}")

    with pytest.raises(DeckFetchError, match="Export"):
        fetch_deck("https://www.moxfield.com/decks/abc", get=must_not_fetch)
