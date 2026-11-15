"""Opt-in checks against the real websites: ``pytest -m network``.

Not part of the default run (no internet needed for the suite). Useful when a site
changes its data format: if this fails while the fixture tests pass, update the parser
and refresh the fixtures.
"""

from __future__ import annotations

import pytest

from mtgcalc_online import fetch_deck

pytestmark = pytest.mark.network


def test_archidekt_public_deck() -> None:
    deck = fetch_deck("https://archidekt.com/decks/1/fun-with-fungus")
    assert deck.size > 0
    assert any(c.zone == "commander" for c in deck.cards)
