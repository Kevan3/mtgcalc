"""Monte Carlo simulator (LLD §5.4, FR-70, MATH §11).

Shares the compiled leaves, programs and bottom policy with the exact path but none of
the DP machinery, so agreement between the two is meaningful evidence (ADR-0007).
"""

from __future__ import annotations

import random

from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.logic import leaf_bits, run2
from mtgcalc.compile.policy import MulliganPlan, bottom
from mtgcalc.errors import ValidationError


def simulate(
    cq: CompiledQuery,
    *,
    trials: int,
    seed: int | None = None,
    mulligan: MulliganPlan | None = None,
) -> tuple[dict[str, int], int]:
    """Play ``trials`` games; return successes per output and the number of trials.

    With ``mulligan`` the strategy is played out (fresh shuffle per mulligan, bottoming,
    keep rule, forced keep at depth M) and ``cq.reserved_bits`` must be 0.
    """
    if trials <= 0:
        raise ValidationError("trials", "must be positive")
    rng = random.Random(seed)
    m = cq.atoms.size
    library: list[int] = [i for i, k in enumerate(cq.atoms.counts) for _ in range(k)]
    library += [-1] * cq.atoms.pool
    hits = {name: 0 for name, _ in cq.outputs}
    by_checkpoint = [cq.leaves_at(j) for j in range(len(cq.plan.checkpoints))]

    for _ in range(trials):
        if mulligan is None:
            rng.shuffle(library)
            seen = _counts(library[: cq.plan.hand_size], m)
            cursor = cq.plan.hand_size
        else:
            for depth, nb in enumerate(mulligan.bottoms):
                rng.shuffle(library)
                hand = _counts(library[: mulligan.draw], m)
                pool_in_hand = mulligan.draw - sum(hand)
                bott = bottom(mulligan.policy, hand, pool_in_hand, nb)
                seen = tuple(h - b for h, b in zip(hand, bott, strict=True))
                if depth == mulligan.max_mulligans or mulligan.keeps(seen):
                    break
            cursor = mulligan.draw
        counts = list(seen)
        bits = 0
        for j, leaves in enumerate(by_checkpoint):
            for card in library[cursor : cursor + cq.plan.batches[j]]:
                if card >= 0:
                    counts[card] += 1
            cursor += cq.plan.batches[j]
            bits |= leaf_bits(leaves, tuple(counts))
        for name, prog in cq.outputs:
            if run2(prog, bits):
                hits[name] += 1
    return hits, trials


def _counts(cards: list[int], m: int) -> tuple[int, ...]:
    out = [0] * m
    for c in cards:
        if c >= 0:
            out[c] += 1
    return tuple(out)
