"""Errors raised while importing decks from websites."""

from __future__ import annotations

from mtgcalc.errors import MtgCalcError


class DeckFetchError(MtgCalcError):
    """A deck could not be imported. The message is written for players.

    The underlying exception (network, HTTP, JSON) is chained as ``__cause__`` for
    debugging.
    """
