"""Game configuration and draw schedule (LLD §3.4, FR-20..FR-23, ADR-0004).

Checkpoint semantics: turn 0 is the kept opening hand; turn T >= 1 means *after the draw
step of turn T*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mtgcalc.errors import ValidationError

TurnMap = tuple[tuple[int, int], ...]
#: Accepted on construction; always normalized to a sorted ``TurnMap``.
TurnMapInput = TurnMap | Mapping[int, int]


def _normalize(name: str, value: TurnMapInput) -> TurnMap:
    items = value.items() if isinstance(value, Mapping) else value
    out: dict[int, int] = {}
    for turn, n in items:
        if turn < 1:
            raise ValidationError(f"game.{name}", "turn keys must be >= 1")
        if n < 0:
            raise ValidationError(f"game.{name}[{turn}]", "must be non-negative")
        if turn in out:
            raise ValidationError(f"game.{name}[{turn}]", "duplicate turn")
        out[turn] = n
    return tuple(sorted(out.items()))


def _lookup(value: TurnMapInput) -> Mapping[int, int]:
    """Dict view of an already-normalized turn map."""
    return value if isinstance(value, Mapping) else dict(value)


@dataclass(frozen=True, slots=True)
class GameConfig:
    """How many cards are seen when.

    Attributes:
        hand_size: Opening hand size when no mulligan is modelled.
        on_play: If true, the turn-1 draw is skipped (unless overridden).
        draws_per_turn: Default draws in each draw step.
        draw_overrides: ``{turn: draws}`` replacing the default for that turn.
        extra_draws: ``{turn: n}`` additional cards drawn by turn ``turn``.
    """

    hand_size: int = 7
    on_play: bool = True
    draws_per_turn: int = 1
    draw_overrides: TurnMapInput = ()
    extra_draws: TurnMapInput = ()

    def __post_init__(self) -> None:
        if self.hand_size < 0:
            raise ValidationError("game.hand_size", "must be non-negative")
        if self.draws_per_turn < 0:
            raise ValidationError("game.draws_per_turn", "must be non-negative")
        object.__setattr__(
            self, "draw_overrides", _normalize("draw_overrides", self.draw_overrides)
        )
        object.__setattr__(self, "extra_draws", _normalize("extra_draws", self.extra_draws))

    def draws_on_turn(self, t: int) -> int:
        """Cards drawn during turn ``t`` (0 for the opening hand)."""
        if t < 0:
            raise ValidationError("turn", "must be non-negative")
        if t == 0:
            return 0
        overrides = _lookup(self.draw_overrides)  # normalized in __post_init__
        if t in overrides:
            base = overrides[t]
        elif t == 1 and self.on_play:
            base = 0
        else:
            base = self.draws_per_turn
        return base + _lookup(self.extra_draws).get(t, 0)

    def draws_through(self, t: int) -> int:
        """Total cards drawn after the opening hand, through the draw step of turn ``t``."""
        return sum(self.draws_on_turn(u) for u in range(1, t + 1))
