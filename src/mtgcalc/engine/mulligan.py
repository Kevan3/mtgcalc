"""Reference mulligan enumeration shared by every engine (LLD §5.6, MATH §9).

For each mulligan depth the 7-card draw is enumerated by atom composition, the bottom
policy and keep rule are applied, and the DP is seeded with ``(kept, bottomed, keep-bit)``
states. The native engine implements the same two operations in Rust; these functions
are the specification (and the fallback) it is tested against.
"""

from __future__ import annotations

from collections import defaultdict

from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.policy import KEEP_BIT, MulliganPlan, bottom
from mtgcalc.engine.base import (
    DEFAULT_LIMIT,
    DepthResult,
    HandValue,
    InitialStates,
    Runner,
    State,
)
from mtgcalc.math.comb import binom, transitions

Vector = tuple[int, ...]


def hands(cq: CompiledQuery, plan: MulliganPlan, depth: int) -> list[tuple[Vector, Vector, int]]:
    """``(drawn hand, bottomed, weight)`` for every drawn-hand composition at ``depth``."""
    atoms = cq.atoms
    out = []
    for hand, c in transitions(atoms.counts, atoms.pool, plan.draw):
        bott = bottom(plan.policy, hand, plan.draw - sum(hand), plan.bottoms[depth])
        out.append((hand, bott, c))
    return out


def _kept(hand: Vector, bott: Vector) -> Vector:
    return tuple(h - b for h, b in zip(hand, bott, strict=True))


def mulligan_depths(
    engine: Runner, cq: CompiledQuery, plan: MulliganPlan, *, limit: int = DEFAULT_LIMIT
) -> tuple[DepthResult, ...]:
    """Keep weight and every output, per depth. The hand at the last depth is always kept."""
    total = binom(cq.atoms.deck_size, plan.draw)
    names = [name for name, _ in cq.outputs]
    results = []
    for m in range(plan.max_mulligans + 1):
        init: dict[State, int] = defaultdict(int)
        keep_weight = 0
        for hand, bott, c in hands(cq, plan, m):
            kept = _kept(hand, bott)
            keep = m == plan.max_mulligans or plan.keeps(kept)
            init[(kept, bott, (1 << KEEP_BIT) if keep else 0)] += c
            keep_weight += c if keep else 0
        res = engine.run(cq, InitialStates(init, total, plan.draw), limit=limit)
        results.append(
            DepthResult(keep_weight, total, {n: res.outputs[n] for n in names}, res.denominator)
        )
    return tuple(results)


def hand_values(
    engine: Runner,
    cq: CompiledQuery,
    plan: MulliganPlan,
    output: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> tuple[tuple[HandValue, ...], ...]:
    """Per depth, each drawn-hand composition with P(``output`` | keep it).

    Results are memoized by ``(kept, bottomed)``: the same kept hand reached at several
    depths (e.g. with a free mulligan) is evaluated once.
    """
    cache: dict[tuple[Vector, Vector], tuple[int, int]] = {}
    per_depth = []
    for m in range(plan.max_mulligans + 1):
        values = []
        for hand, bott, c in hands(cq, plan, m):
            key = (_kept(hand, bott), bott)
            if key not in cache:
                start = InitialStates({(key[0], bott, 1 << KEEP_BIT): 1}, 1, plan.draw)
                res = engine.run(cq, start, limit=limit)
                cache[key] = (res.outputs[output], res.denominator)
            success, denominator = cache[key]
            values.append(HandValue(hand, c, success, denominator))
        per_depth.append(tuple(values))
    return tuple(per_depth)
