"""Draw schedule -> batch plan (LLD §4.2, MATH §2)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mtgcalc.model.game import GameConfig


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Checkpoints (sorted turns, always including 0) and draws between them.

    ``batches[j]`` is the number of cards drawn between ``checkpoints[j-1]`` and
    ``checkpoints[j]``; ``batches[0] == 0``.
    """

    checkpoints: tuple[int, ...]
    batches: tuple[int, ...]
    hand_size: int

    @property
    def total_draws(self) -> int:
        """Cards drawn after the opening hand through the last checkpoint."""
        return sum(self.batches)

    def index(self, turn: int) -> int:
        """Checkpoint index of ``turn``."""
        return self.checkpoints.index(turn)

    def cards_seen(self, j: int) -> int:
        """Cards seen (kept hand of ``hand_size`` + draws) at checkpoint index ``j``."""
        return self.hand_size + sum(self.batches[: j + 1])


def plan(game: GameConfig, turns: Iterable[int], hand_size: int) -> BatchPlan:
    """Build the batch plan for the given checkpoint turns."""
    cps = tuple(sorted(set(turns) | {0}))
    batches = (
        0,
        *(game.draws_through(cps[j]) - game.draws_through(cps[j - 1]) for j in range(1, len(cps))),
    )
    return BatchPlan(cps, batches, hand_size)
