"""Text decklist parsing (LLD §7.1, FR-60..FR-63, NFR-14).

Supported line shapes (combinable)::

    4 Lightning Bolt
    4x Lightning Bolt (M11) 149 *F*
    1 Sol Ring #ramp #!artifact            (Moxfield-style tags)
    1x Arcane Signet [Ramp,Mana Rock{top}]  (Archidekt-style categories)

Section headers (``Commander``, ``Deck``, ``Sideboard``, ...) switch the zone.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from mtgcalc.errors import ParseError
from mtgcalc.model.deck import Card, Deck, Zone, normalize_name, normalize_tag

Format = Literal["auto", "plain", "moxfield", "archidekt"]
MAX_INPUT = 1_000_000

_SECTION = re.compile(
    r"^\s*(?://\s*)?(commander|commanders|deck|main|mainboard|sideboard|maybeboard|companion)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)
_SECTION_ZONE: dict[str, Zone] = {
    "commander": "commander",
    "commanders": "commander",
    "deck": "library",
    "main": "library",
    "mainboard": "library",
    "sideboard": "sideboard",
    "companion": "sideboard",
    "maybeboard": "maybeboard",
}
_QTY = re.compile(r"^\s*(\d+)\s*x?\s+(.*)$", re.IGNORECASE)
_BRACKETS = re.compile(r"\[([^\]]*)\]")
_HASHTAG = re.compile(r"(?:^|\s)#!?([^\s#]+)")
_CARET = re.compile(r"\^[^^]*\^")
_SET_SUFFIX = re.compile(r"\s+\([A-Za-z0-9]{2,6}\)(?:\s+[A-Za-z0-9-]+[a-z★]?)?\s*$")
_FOIL = re.compile(r"\s+\*[A-Z]\*")


class DeckImporter(Protocol):
    """Anything that turns text into a :class:`Deck` (FR-63)."""

    def parse(self, text: str) -> Deck:
        """Parse a decklist."""
        ...


def _strip_archidekt(rest: str, tags: set[str]) -> tuple[str, Zone | None]:
    zone: Zone | None = None
    for group in _BRACKETS.findall(rest):
        for raw in group.split(","):
            cat = re.sub(r"\{[^}]*\}", "", raw).strip()
            if not cat:
                continue
            lower = cat.casefold()
            if lower in _SECTION_ZONE and lower not in ("deck", "main", "mainboard"):
                zone = _SECTION_ZONE[lower]
            else:
                tags.add(normalize_tag(cat))
    return _BRACKETS.sub(" ", rest), zone


def _strip_moxfield(rest: str, tags: set[str]) -> str:
    tags.update(normalize_tag(t) for t in _HASHTAG.findall(rest))
    return _HASHTAG.sub(" ", rest)


def parse_decklist(text: str, fmt: Format = "auto") -> Deck:
    """Parse a text decklist into a :class:`Deck` (duplicates merged per zone)."""
    if len(text) > MAX_INPUT:
        raise ParseError(f"decklist longer than {MAX_INPUT} characters")
    use_arch = fmt in ("auto", "archidekt")
    use_mox = fmt in ("auto", "moxfield")
    zone: Zone = "library"
    merged: dict[tuple[Zone, str], tuple[str, int, set[str]]] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        section = _SECTION.match(line)
        if section:
            zone = _SECTION_ZONE[section.group(1).casefold()]
            continue
        if line.startswith("//"):
            continue
        m = _QTY.match(line)
        if m is None:
            raise ParseError("expected '<quantity> <card name>'", lineno, 1)
        qty, rest = int(m.group(1)), m.group(2)
        if qty < 1:
            raise ParseError("quantity must be at least 1", lineno, 1)
        tags: set[str] = set()
        card_zone: Zone | None = None
        rest = _CARET.sub(" ", rest)
        if use_arch:
            rest, card_zone = _strip_archidekt(rest, tags)
        if use_mox:
            rest = _strip_moxfield(rest, tags)
        rest = _FOIL.sub(" ", rest)
        rest = _SET_SUFFIX.sub("", rest)
        name = " ".join(rest.split())
        if not name:
            raise ParseError("missing card name", lineno, m.start(2) + 1)
        z = card_zone or zone
        key = (z, normalize_name(name))
        prev_name, prev_qty, prev_tags = merged.get(key, (name, 0, set()))
        merged[key] = (prev_name, prev_qty + qty, prev_tags | tags)
    if not merged:
        raise ParseError("decklist is empty")
    cards = tuple(Card(n, q, frozenset(t), z) for (z, _), (n, q, t) in merged.items())
    return Deck(cards)


_ZONE_HEADERS: tuple[tuple[Zone, str], ...] = (
    ("commander", "Commander"),
    ("library", "Deck"),
    ("sideboard", "Sideboard"),
    ("maybeboard", "Maybeboard"),
)


def tag_token(tag: str) -> str:
    """A tag as a single ``#word``: spaces become hyphens, ``#`` is dropped."""
    return "-".join(tag.replace("#", " ").split())


def format_decklist(deck: Deck) -> str:
    """Write ``deck`` as text that :func:`parse_decklist` reads back.

    Tags are written Moxfield-style (``#ramp``) so that tag names such as "sideboard"
    are never mistaken for sections. Tags containing spaces are hyphenated, so
    ``parse_decklist(format_decklist(deck))`` returns the same deck up to that spelling.
    """
    lines: list[str] = []
    for zone, header in _ZONE_HEADERS:
        cards = [c for c in deck.cards if c.zone == zone]
        if not cards:
            continue
        if lines:
            lines.append("")
        lines.append(header)
        for c in cards:
            tags = "".join(f" #{tag_token(t)}" for t in sorted(c.tags) if tag_token(t))
            lines.append(f"{c.quantity} {c.name}{tags}")
    return "\n".join(lines) + "\n"


class TextImporter:
    """:class:`DeckImporter` for a fixed text format."""

    def __init__(self, fmt: Format = "auto") -> None:
        self.fmt: Format = fmt

    def parse(self, text: str) -> Deck:
        """Parse ``text`` in this importer's format."""
        return parse_decklist(text, self.fmt)
