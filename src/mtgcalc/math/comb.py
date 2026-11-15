"""Exact combinatorial kernel (LLD §2.1, MATH §3-§5).

All functions are pure and operate on Python integers, so results are exact.
"""

from __future__ import annotations

import math
from functools import cache, lru_cache

Vector = tuple[int, ...]
Transition = tuple[Vector, int]


@cache
def binom(n: int, k: int) -> int:
    """Binomial coefficient C(n, k), defined as 0 outside 0 <= k <= n."""
    if n < 0 or k < 0 or k > n:
        return 0
    return math.comb(n, k)


@lru_cache(maxsize=2**16)
def transitions(rem: Vector, pool_rem: int, b: int) -> tuple[Transition, ...]:
    """Enumerate every way to draw ``b`` cards from atoms ``rem`` plus an untracked pool.

    Returns all ``(d, coef)`` with ``0 <= d[i] <= rem[i]`` and ``0 <= b - sum(d) <= pool_rem``,
    where ``coef = prod(C(rem[i], d[i])) * C(pool_rem, b - sum(d))`` is the number of
    ``b``-subsets of the remaining library with that atom composition.

    Postcondition (Chu-Vandermonde, MATH §4): ``sum(coef) == C(sum(rem) + pool_rem, b)``.
    The same function enumerates opening hands: ``transitions(K, pool, hand_size)``.
    """
    if b < 0 or pool_rem < 0 or any(r < 0 for r in rem):
        return ()
    out: list[Transition] = []
    m = len(rem)
    current = [0] * m

    def rec(i: int, left: int, coef: int) -> None:
        if i == m:
            if left <= pool_rem:
                out.append((tuple(current), coef * binom(pool_rem, left)))
            return
        for x in range(min(rem[i], left) + 1):
            current[i] = x
            rec(i + 1, left - x, coef * binom(rem[i], x))
        current[i] = 0

    rec(0, b, 1)
    return tuple(out)
