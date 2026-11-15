"""Recognize deck links and import them (the public entry point is :func:`fetch_deck`).

Only links to known deck sites are fetched, and only from those sites' own APIs; any
other text is rejected before a network request is made.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mtgcalc import Deck
from mtgcalc_online import archidekt
from mtgcalc_online.errors import DeckFetchError
from mtgcalc_online.http import get_json

log = logging.getLogger("mtgcalc_online")

Getter = Callable[[str], Any]

MOXFIELD_LINK = re.compile(r"^https?://(?:www\.)?moxfield\.com/decks/([\w-]+)(?:[/?#].*)?$", re.I)
MOXFIELD_HELP = (
    "Moxfield does not let other programs download decks. In Moxfield open the deck, "
    "choose Export > Copy as plain text (tags are included), and paste it here."
)


@dataclass(frozen=True, slots=True)
class Source:
    """A deck website: how to recognize its links and turn its data into a deck.

    ``api_url``/``to_deck`` are ``None`` for sites that cannot be imported
    automatically; ``help`` then tells the player what to do instead.
    """

    name: str
    link: re.Pattern[str]
    api_url: Callable[[str], str] | None = None
    to_deck: Callable[[Any], Deck] | None = None
    help: str = ""


SOURCES: tuple[Source, ...] = (
    Source(archidekt.NAME, archidekt.LINK, archidekt.api_url, archidekt.to_deck),
    Source("Moxfield", MOXFIELD_LINK, help=MOXFIELD_HELP),
)


def recognize(link: str) -> tuple[Source, str]:
    """The source and deck id of a deck link.

    Raises:
        DeckFetchError: the text is not a link to a supported deck site.
    """
    text = link.strip()
    for source in SOURCES:
        match = source.link.match(text)
        if match:
            return source, match.group(1)
    names = " or ".join(s.name for s in SOURCES)
    raise DeckFetchError(f"That is not a deck link. Paste a deck link from {names}.")


def fetch_deck(link: str, *, get: Getter = get_json) -> Deck:
    """Download and convert the deck at ``link``.

    ``get`` performs the HTTP GET (injectable for tests and debugging).

    Raises:
        DeckFetchError: unsupported link, network/HTTP problems, or unreadable data.
    """
    source, deck_id = recognize(link)
    if source.api_url is None or source.to_deck is None:
        raise DeckFetchError(source.help)
    log.debug("importing %s deck %s", source.name, deck_id)
    return source.to_deck(get(source.api_url(deck_id)))
