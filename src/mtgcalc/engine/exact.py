"""Exact sequential state DP (LLD §5.2, MATH §5, ADR-0002/0003).

The engine tracks a distribution over states ``(seen, bottomed, bits)`` with *integer*
weights over one shared integer denominator. Every reduction it performs (state merging,
atom retirement, early resolution) is exact; see MATH §5.3 for the proofs.
"""

from __future__ import annotations

from collections import defaultdict

from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.logic import leaf_bits, run2, run3
from mtgcalc.compile.policy import MulliganPlan
from mtgcalc.engine.base import (
    DEFAULT_LIMIT,
    DepthResult,
    HandValue,
    InitialStates,
    RunResult,
    State,
)
from mtgcalc.engine.mulligan import hand_values, mulligan_depths
from mtgcalc.errors import StateSpaceTooLargeError, ValidationError
from mtgcalc.math.comb import binom, transitions


def default_initial_states(cq: CompiledQuery) -> InitialStates:
    """Opening hand of ``cq.plan.hand_size`` cards, no mulligan (MATH §4)."""
    K, pool, h = cq.atoms.counts, cq.atoms.pool, cq.plan.hand_size
    zero = (0,) * len(K)
    states: dict[State, int] = {(x, zero, 0): c for x, c in transitions(K, pool, h)}
    return InitialStates(states, binom(cq.atoms.deck_size, h), h)


class ExactEngine:
    """Reference implementation of the :class:`~mtgcalc.engine.base.Engine` protocol.

    Args:
        early_resolution: Drop states whose outputs are already decided (exact).
        retirement: Fold atoms no longer referenced into the pool (exact).

    Both switches exist so tests can prove the optimizations change nothing.
    """

    def __init__(self, *, early_resolution: bool = True, retirement: bool = True) -> None:
        self.early_resolution = early_resolution
        self.retirement = retirement

    def run(
        self, cq: CompiledQuery, init: InitialStates | None = None, *, limit: int = DEFAULT_LIMIT
    ) -> RunResult:
        """Evaluate every output and observer of ``cq``."""
        start = init if init is not None else default_initial_states(cq)
        N = cq.atoms.deck_size
        K = list(cq.atoms.counts)
        pool = cq.atoms.pool
        removed = start.removed
        D = start.denominator
        batches = cq.plan.batches
        n_cp = len(cq.plan.checkpoints)
        if removed + sum(batches) > N:
            raise ValidationError("game", "draws exceed the library")

        # future_den[j] = product of batch denominators after checkpoint j (MATH §5.3).
        future_den = [1] * n_cp
        rem_before = removed + sum(batches)
        for j in range(n_cp - 1, 0, -1):
            rem_before -= batches[j]
            future_den[j - 1] = future_den[j] * binom(N - rem_before, batches[j])

        dist: dict[State, int] = defaultdict(int)
        for s, w in start.states.items():
            if w:
                dist[s] += w
        resolved = {name: 0 for name, _ in cq.outputs}
        snapshots: dict[tuple[int, tuple[int, ...]], tuple[tuple[int, ...], int]] = {}
        last_observer = max((j for j, _ in cq.observers), default=-1)
        peak = len(dist)
        if peak > limit:
            raise StateSpaceTooLargeError(peak, limit)

        for j in range(n_cp):
            b = batches[j]
            if j > 0 and b > 0:
                nxt: dict[State, int] = defaultdict(int)
                for (seen, bott, bits), w in dist.items():
                    rem = tuple(K[i] - seen[i] - bott[i] for i in range(len(K)))
                    prem = pool - (removed - sum(seen) - sum(bott))
                    for d, c in transitions(rem, prem, b):
                        new_seen = tuple(x + y for x, y in zip(seen, d, strict=True))
                        nxt[(new_seen, bott, bits)] += w * c
                dist = nxt
                D *= binom(N - removed, b)
                removed += b
                peak = max(peak, len(dist))
                if len(dist) > limit:
                    raise StateSpaceTooLargeError(len(dist), limit)

            here = cq.leaves_at(j)
            if here:
                evaluated: dict[State, int] = defaultdict(int)
                for (seen, bott, bits), w in dist.items():
                    evaluated[(seen, bott, bits | leaf_bits(here, seen))] += w
                dist = evaluated

            for idx, mask in cq.observers:
                if idx == j:
                    snapshots[(idx, mask)] = (_marginal(dist, mask), D)

            if self.early_resolution and cq.outputs and last_observer <= j and j < n_cp - 1:
                known = cq.known_through(j)
                kept: dict[State, int] = defaultdict(int)
                for state, w in dist.items():
                    verdicts = [run3(prog, state[2], known) for _, prog in cq.outputs]
                    if any(v is None for v in verdicts):
                        kept[state] += w
                        continue
                    for (name, _), v in zip(cq.outputs, verdicts, strict=True):
                        if v:
                            resolved[name] += w * future_den[j]
                dist = kept

            if self.retirement and cq.retire_after[j] and j < n_cp - 1:
                gone = cq.retire_after[j]
                for i in gone:
                    pool += K[i]
                    K[i] = 0
                folded: dict[State, int] = defaultdict(int)
                for (seen, bott, bits), w in dist.items():
                    s2 = tuple(0 if i in gone else x for i, x in enumerate(seen))
                    b2 = tuple(0 if i in gone else x for i, x in enumerate(bott))
                    folded[(s2, b2, bits)] += w
                dist = folded

        for state, w in dist.items():
            for name, prog in cq.outputs:
                if run2(prog, state[2]):
                    resolved[name] += w
        return RunResult(resolved, D, snapshots, peak)

    def mulligan(
        self, cq: CompiledQuery, plan: MulliganPlan, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[DepthResult, ...]:
        """Every mulligan depth (reference implementation, :mod:`.mulligan`)."""
        return mulligan_depths(self, cq, plan, limit=limit)

    def hand_values(
        self, cq: CompiledQuery, plan: MulliganPlan, output: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[tuple[HandValue, ...], ...]:
        """Per-hand success values (reference implementation, :mod:`.mulligan`)."""
        return hand_values(self, cq, plan, output, limit=limit)


def _marginal(dist: dict[State, int], mask: tuple[int, ...]) -> tuple[int, ...]:
    """Numerators of P(sum of seen[mask] = k) for k = 0..max."""
    acc: dict[int, int] = defaultdict(int)
    for (seen, _, _), w in dist.items():
        acc[sum(seen[i] for i in mask)] += w
    top = max(acc, default=0)
    return tuple(acc.get(k, 0) for k in range(top + 1))
