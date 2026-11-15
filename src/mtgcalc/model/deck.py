"""Cards and decks (LLD §3.3, FR-01, FR-05, FR-64)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from mtgcalc.errors import ValidationError

Zone = Literal["library", "commander", "sideboard", "maybeboard"]
ZONES: tuple[Zone, ...] = ("library", "commander", "sideboard", "maybeboard")
FILLER_NAME = "(other)"


def normalize_tag(tag: str) -> str:
    """Canonical tag form: stripped and case-folded."""
    return " ".join(tag.split()).casefold()


def normalize_name(name: str) -> str:
    """Canonical card-name key: whitespace-collapsed and case-folded."""
    return " ".join(name.split()).casefold()


@dataclass(frozen=True, slots=True)
class Card:
    """A card entry: a name, how many copies, its tags and its zone."""

    name: str
    quantity: int = 1
    tags: frozenset[str] = field(default_factory=frozenset)
    zone: Zone = "library"

    def __post_init__(self) -> None:
        clean = " ".join(self.name.split())
        if not clean:
            raise ValidationError("card.name", "must not be empty")
        if self.quantity < 1:
            raise ValidationError(f"card[{clean}].quantity", "must be at least 1")
        if self.zone not in ZONES:
            raise ValidationError(f"card[{clean}].zone", f"must be one of {ZONES}")
        tags = frozenset(normalize_tag(t) for t in self.tags)
        if "" in tags:
            raise ValidationError(f"card[{clean}].tags", "tags must not be empty")
        object.__setattr__(self, "name", clean)
        object.__setattr__(self, "tags", tags)


@dataclass(frozen=True, slots=True)
class Category:
    """An abstract category of interchangeable cards (FR-01a), optionally with extra tags."""

    count: int
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValidationError("category.count", "must be non-negative")
        object.__setattr__(self, "tags", frozenset(normalize_tag(t) for t in self.tags))


@dataclass(frozen=True, slots=True)
class Deck:
    """An immutable decklist. Only ``zone == "library"`` cards are shuffled."""

    cards: tuple[Card, ...]
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cards", tuple(self.cards))
        seen: set[tuple[str, str]] = set()
        for c in self.cards:
            key = (c.zone, normalize_name(c.name))
            if key in seen:
                raise ValidationError(f"deck.cards[{c.name}]", f"duplicate card in zone {c.zone}")
            seen.add(key)
        if self.size == 0:
            raise ValidationError("deck.cards", "library must contain at least one card")

    @property
    def library(self) -> tuple[Card, ...]:
        """Cards that are shuffled into the library."""
        return tuple(c for c in self.cards if c.zone == "library")

    @property
    def size(self) -> int:
        """Library size N."""
        return sum(c.quantity for c in self.cards if c.zone == "library")

    def tag_counts(self) -> dict[str, int]:
        """Number of library cards carrying each tag."""
        counts: dict[str, int] = {}
        for c in self.library:
            for t in c.tags:
                counts[t] = counts.get(t, 0) + c.quantity
        return dict(sorted(counts.items()))

    def card(self, name: str) -> Card:
        """Look up a card by (case-insensitive) name in any zone."""
        key = normalize_name(name)
        for c in self.cards:
            if normalize_name(c.name) == key:
                return c
        raise ValidationError("card", f"no card named {name!r}")

    def with_tags(self, name: str, add: Iterable[str] = (), remove: Iterable[str] = ()) -> Deck:
        """Return a copy with tags added to / removed from one card (FR-64)."""
        target = self.card(name)
        drop = {normalize_tag(t) for t in remove}
        new_tags = (target.tags - drop) | {normalize_tag(t) for t in add}
        cards = tuple(replace(c, tags=new_tags) if c is target else c for c in self.cards)
        return Deck(cards, self.name)

    def rename_tag(self, old: str, new: str) -> Deck:
        """Return a copy with tag ``old`` renamed to ``new`` on every card (FR-64)."""
        o, n = normalize_tag(old), normalize_tag(new)
        cards = tuple(
            replace(c, tags=(c.tags - {o}) | {n}) if o in c.tags else c for c in self.cards
        )
        return Deck(cards, self.name)

    @staticmethod
    def from_counts(deck_size: int, categories: Mapping[str, int | Category]) -> Deck:
        """Build an abstract deck: one card per category plus a filler card (FR-01a).

        Each category card is tagged with its own name plus any extra tags, so categories
        may overlap through shared tags.
        """
        cards: list[Card] = []
        total = 0
        for name, spec in categories.items():
            cat = spec if isinstance(spec, Category) else Category(spec)
            total += cat.count
            if cat.count > 0:
                cards.append(Card(name, cat.count, frozenset({name}) | cat.tags))
        if total > deck_size:
            raise ValidationError("categories", f"total {total} exceeds deck size {deck_size}")
        if deck_size - total > 0:
            cards.append(Card(FILLER_NAME, deck_size - total, frozenset({FILLER_NAME})))
        return Deck(tuple(cards))
