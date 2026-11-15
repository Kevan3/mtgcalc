"""Scenario: the fixed context of a query (LLD §3.6, FR-05, FR-15)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from mtgcalc.model.deck import Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig, PriorityGroup

Format = Literal["limited", "constructed", "commander"]

#: Default library sizes per format (Commander: 99 in the library + 1 commander).
LIBRARY_SIZE: dict[Format, int] = {"limited": 40, "constructed": 60, "commander": 99}
#: Free mulligans per format (multiplayer Commander: first mulligan is free).
FREE_MULLIGANS: dict[Format, int] = {"limited": 0, "constructed": 0, "commander": 1}


@dataclass(frozen=True, slots=True)
class Scenario:
    """Deck + game configuration + optional mulligan configuration."""

    deck: Deck
    game: GameConfig = field(default_factory=GameConfig)
    mulligan: MulliganConfig | None = None

    def with_mulligan(self, mulligan: MulliganConfig | None) -> Scenario:
        """Copy with a different mulligan configuration."""
        return replace(self, mulligan=mulligan)


def preset_mulligan(
    fmt: Format, priority: tuple[PriorityGroup, ...], max_mulligans: int = 2
) -> MulliganConfig:
    """A mulligan configuration with the format's free-mulligan default."""
    return MulliganConfig(
        priority=priority, max_mulligans=max_mulligans, free_mulligans=FREE_MULLIGANS[fmt]
    )
