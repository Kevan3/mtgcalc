"""Import decks from deck websites by link (ADR-0012).

Kept outside the ``mtgcalc`` core because it does network I/O (NFR-07)::

    from mtgcalc_online import fetch_deck
    deck = fetch_deck("https://archidekt.com/decks/123456/my-deck")

Supported: Archidekt (public decks). Moxfield links are recognized and answered with
instructions for its text export, because Moxfield blocks other programs.
"""

from mtgcalc_online.errors import DeckFetchError
from mtgcalc_online.sources import SOURCES, Source, fetch_deck, recognize

__all__ = ["SOURCES", "DeckFetchError", "Source", "fetch_deck", "recognize"]
