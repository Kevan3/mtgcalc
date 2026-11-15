"""Archidekt deck JSON -> :class:`mtgcalc.Deck` (pure; no network).

Shape of ``GET https://archidekt.com/api/decks/<id>/`` (only the fields used)::

    {"name": str,
     "categories": [{"name": str, "isPremier": bool, "includedInDeck": bool}],
     "cards": [{"quantity": int, "categories": [str], "deletedAt": str | null,
                "card": {"oracleCard": {"name": str}}}]}

Placement follows Archidekt: a card's *first* category decides where it goes. A premier
category (the commander) puts it in the command zone; a category not included in the
deck (e.g. Maybeboard) puts it in the maybeboard; anything else is in the library. Every
category becomes a tag. Deleted cards are skipped; repeated cards (several printings)
are merged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from mtgcalc import Card, Deck
from mtgcalc.model.deck import Zone
from mtgcalc_online.errors import DeckFetchError

NAME = "Archidekt"
LINK = re.compile(r"^https?://(?:www\.)?archidekt\.com/(?:api/)?decks/(\d+)(?:[/?#].*)?$", re.I)


def api_url(deck_id: str) -> str:
    """JSON endpoint for a deck id."""
    return f"https://archidekt.com/api/decks/{deck_id}/"


def to_deck(data: Any) -> Deck:
    """Convert Archidekt's JSON into a deck (tags = categories)."""
    try:
        name = str(data.get("name") or "Archidekt deck")
        categories = {c["name"]: c for c in data.get("categories") or []}
        entries = data["cards"]
        merged: dict[tuple[Zone, str], tuple[str, int, set[str]]] = {}
        for entry in entries:
            if entry.get("deletedAt"):
                continue
            card_name = str(entry["card"]["oracleCard"]["name"])
            tags = [str(t) for t in entry.get("categories") or []]
            zone = _zone(tags[0] if tags else None, categories)
            key = (zone, card_name.casefold())
            _, qty, seen = merged.get(key, (card_name, 0, set()))
            merged[key] = (card_name, qty + int(entry["quantity"]), seen | set(tags))
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise DeckFetchError("Archidekt sent a deck in a format this version cannot read.") from e
    cards = tuple(Card(n, q, frozenset(t), z) for (z, _), (n, q, t) in merged.items() if q > 0)
    if not any(c.zone == "library" for c in cards):
        raise DeckFetchError("That Archidekt deck has no cards in it.")
    return Deck(cards, name)


def _zone(primary: str | None, categories: Mapping[str, Mapping[str, Any]]) -> Zone:
    info = categories.get(primary or "")
    if info is None:
        return "library"
    if info.get("isPremier"):
        return "commander"
    return "library" if info.get("includedInDeck", True) else "maybeboard"
