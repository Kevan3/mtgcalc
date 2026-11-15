"""Selectors: rules that pick cards out of a deck (LLD §3.1, FR-03, FR-36)."""

from __future__ import annotations

from dataclasses import dataclass

from mtgcalc.errors import ValidationError
from mtgcalc.model.deck import Card, normalize_name, normalize_tag


@dataclass(frozen=True, slots=True)
class Tag:
    """Cards carrying a tag (case-insensitive)."""

    name: str

    def __post_init__(self) -> None:
        clean = normalize_tag(self.name)
        if not clean:
            raise ValidationError("tag", "tag name must not be empty")
        object.__setattr__(self, "name", clean)


@dataclass(frozen=True, slots=True)
class CardName:
    """Cards with a given name (case-insensitive)."""

    name: str

    def __post_init__(self) -> None:
        clean = " ".join(self.name.split())
        if not clean:
            raise ValidationError("card", "card name must not be empty")
        object.__setattr__(self, "name", clean)


@dataclass(frozen=True, slots=True)
class AnyOf:
    """Union: cards matched by at least one item."""

    items: tuple[Selector, ...]

    def __post_init__(self) -> None:
        _check_items("any_of", self, self.items)


@dataclass(frozen=True, slots=True)
class AllOf:
    """Intersection: cards matched by every item."""

    items: tuple[Selector, ...]

    def __post_init__(self) -> None:
        _check_items("all_of", self, self.items)


@dataclass(frozen=True, slots=True)
class NoneOf:
    """Complement of the union: cards matched by no item."""

    items: tuple[Selector, ...]

    def __post_init__(self) -> None:
        _check_items("none_of", self, self.items)


@dataclass(frozen=True, slots=True)
class Everything:
    """Every card in the library."""


Selector = Tag | CardName | AnyOf | AllOf | NoneOf | Everything
SELECTOR_TYPES = (Tag, CardName, AnyOf, AllOf, NoneOf, Everything)


def _check_items(kind: str, obj: object, items: tuple[Selector, ...]) -> None:
    items = tuple(items)
    if not items:
        raise ValidationError(kind, "needs at least one selector")
    for it in items:
        if not isinstance(it, SELECTOR_TYPES):
            raise ValidationError(kind, f"{it!r} is not a selector")
    object.__setattr__(obj, "items", items)


def matches(sel: Selector, card: Card) -> bool:
    """Whether ``sel`` selects ``card``."""
    match sel:
        case Tag(name):
            return name in card.tags
        case CardName(name):
            return normalize_name(name) == normalize_name(card.name)
        case AnyOf(items):
            return any(matches(s, card) for s in items)
        case AllOf(items):
            return all(matches(s, card) for s in items)
        case NoneOf(items):
            return not any(matches(s, card) for s in items)
        case Everything():
            return True
    raise TypeError(f"not a selector: {sel!r}")  # pragma: no cover


def card_names_in(sel: Selector) -> tuple[str, ...]:
    """All CardName names referenced anywhere inside ``sel``."""
    match sel:
        case CardName(name):
            return (name,)
        case AnyOf(items) | AllOf(items) | NoneOf(items):
            return tuple(n for s in items for n in card_names_in(s))
        case _:
            return ()


def tag(name: str) -> Tag:
    """Builder: select by tag."""
    return Tag(name)


def card(name: str) -> CardName:
    """Builder: select by card name."""
    return CardName(name)


def any_of(*items: Selector | str) -> AnyOf:
    """Builder: union (strings are tags)."""
    return AnyOf(tuple(_coerce(i) for i in items))


def all_of(*items: Selector | str) -> AllOf:
    """Builder: intersection (strings are tags)."""
    return AllOf(tuple(_coerce(i) for i in items))


def none_of(*items: Selector | str) -> NoneOf:
    """Builder: complement of union (strings are tags)."""
    return NoneOf(tuple(_coerce(i) for i in items))


def everything() -> Everything:
    """Builder: all cards."""
    return Everything()


def _coerce(s: Selector | str) -> Selector:
    return Tag(s) if isinstance(s, str) else s
