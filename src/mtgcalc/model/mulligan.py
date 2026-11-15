"""Mulligan configuration (LLD §3.5, FR-40..FR-43, ADR-0005)."""

from __future__ import annotations

from dataclasses import dataclass

from mtgcalc.errors import ValidationError
from mtgcalc.model.conditions import At, Condition, Const, walk
from mtgcalc.model.selectors import SELECTOR_TYPES, Selector


@dataclass(frozen=True, slots=True)
class PriorityGroup:
    """A user-given bottoming priority group.

    Up to ``quota`` cards of this group are protected from being put on the bottom.
    ``None`` derives the quota from the conditions (LLD §4.5).
    """

    selector: Selector
    quota: int | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.selector, SELECTOR_TYPES):
            raise ValidationError("priority.selector", f"{self.selector!r} is not a selector")
        if self.quota is not None and self.quota < 0:
            raise ValidationError("priority.quota", "must be non-negative")


#: Default keep rule: keep any hand.
KEEP_ANY: Condition = Const(True)


@dataclass(frozen=True, slots=True)
class MulliganConfig:
    """London mulligan with ``free_mulligans`` free mulligans (MATH §9.1).

    Attributes:
        priority: Bottoming priority groups, highest priority first.
        keep_rule: Condition on the kept hand (after bottoming) deciding keep vs. mulligan.
        max_mulligans: M; the hand at depth M is always kept.
        free_mulligans: F in {0, 1}; mulligan m bottoms ``max(0, m - F)`` cards.
        draw_size: Cards drawn for each hand (7 in all current formats).
    """

    priority: tuple[PriorityGroup, ...]
    keep_rule: Condition = KEEP_ANY
    max_mulligans: int = 2
    free_mulligans: int = 0
    draw_size: int = 7

    def __post_init__(self) -> None:
        prio = tuple(self.priority)
        object.__setattr__(self, "priority", prio)
        if not prio:
            raise ValidationError("mulligan.priority", "at least one priority group is required")
        sels = [g.selector for g in prio]
        if len(set(sels)) != len(sels):
            raise ValidationError("mulligan.priority", "priority group selectors must be distinct")
        if self.max_mulligans < 0:
            raise ValidationError("mulligan.max_mulligans", "must be non-negative")
        if self.free_mulligans not in (0, 1):
            raise ValidationError("mulligan.free_mulligans", "must be 0 or 1")
        if self.draw_size < 1:
            raise ValidationError("mulligan.draw_size", "must be positive")
        if self.bottom_count(self.max_mulligans) > self.draw_size:
            raise ValidationError(
                "mulligan.max_mulligans", "would require bottoming more cards than drawn"
            )
        for node in walk(self.keep_rule):
            if isinstance(node, At) and node.turn != 0:
                raise ValidationError("mulligan.keep_rule", "keep rule may only use turn 0")

    def bottom_count(self, m: int) -> int:
        """Cards put on the bottom after the ``m``-th mulligan."""
        return max(0, m - self.free_mulligans)

    def hand_size(self, m: int) -> int:
        """Kept hand size at mulligan depth ``m``."""
        return self.draw_size - self.bottom_count(m)
