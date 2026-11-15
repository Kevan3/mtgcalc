"""Atomization: overlapping selectors -> disjoint atoms (LLD §4.1, MATH §6).

An *atom* is the set of library cards sharing one membership signature over the
referenced selectors. Atom counts are multivariate hypergeometric (MATH §4); every
selector count is the sum of the counts of the atoms whose signature includes it.
Cards matched by no referenced selector form the untracked *pool*.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mtgcalc.errors import ValidationError
from mtgcalc.model.deck import Deck, normalize_name
from mtgcalc.model.selectors import Selector, card_names_in, matches

Signature = tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class AtomTable:
    """Disjoint atoms of a deck with respect to a list of selectors."""

    deck_size: int
    selectors: tuple[Selector, ...]
    signatures: tuple[Signature, ...]
    counts: tuple[int, ...]
    names: tuple[tuple[str, ...], ...]
    pool: int

    @property
    def size(self) -> int:
        """Number of tracked atoms."""
        return len(self.counts)

    def mask(self, sel: Selector) -> tuple[int, ...]:
        """Indices of atoms whose cards are matched by ``sel``."""
        try:
            j = self.selectors.index(sel)
        except ValueError:
            raise ValidationError("selector", f"{sel!r} was not atomized") from None
        return tuple(i for i, sig in enumerate(self.signatures) if sig[j])


def atomize(deck: Deck, selectors: Iterable[Selector]) -> AtomTable:
    """Partition the library into atoms over ``selectors`` (deterministic order)."""
    sels: list[Selector] = []
    for s in selectors:
        if s not in sels:
            sels.append(s)
    known = {normalize_name(c.name) for c in deck.library}
    for s in sels:
        for name in card_names_in(s):
            if normalize_name(name) not in known:
                raise ValidationError("selector", f"no library card named {name!r}")
    groups: dict[Signature, tuple[int, list[str]]] = {}
    for c in deck.library:
        sig = tuple(matches(s, c) for s in sels)
        cnt, names = groups.get(sig, (0, []))
        groups[sig] = (cnt + c.quantity, [*names, c.name])
    pool = groups.pop(tuple(False for _ in sels), (0, []))[0]
    order = sorted(groups, reverse=True)
    return AtomTable(
        deck_size=deck.size,
        selectors=tuple(sels),
        signatures=tuple(order),
        counts=tuple(groups[s][0] for s in order),
        names=tuple(tuple(groups[s][1]) for s in order),
        pool=pool,
    )
