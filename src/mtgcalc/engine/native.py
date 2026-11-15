"""Adapter for the native (Rust) exact engine (LLD §5.5, ADR-0009).

Translates a :class:`CompiledQuery` (and a :class:`MulliganPlan`) into flat tuples, calls
the ``mtgcalc_native`` extension, and translates the results back. The Rust crate ports
:class:`~mtgcalc.engine.exact.ExactEngine` and :mod:`mtgcalc.engine.mulligan` exactly and
releases the GIL while computing.

Shapes beyond the native limits (more than 64 predicate bits, more than 32 tracked
atoms) transparently use the Python reference instead.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.logic import Leaf
from mtgcalc.compile.policy import MulliganPlan
from mtgcalc.engine import mulligan as reference
from mtgcalc.engine.base import (
    DEFAULT_LIMIT,
    DepthResult,
    HandValue,
    InitialStates,
    RunResult,
)
from mtgcalc.engine.exact import ExactEngine
from mtgcalc.errors import StateSpaceTooLargeError

MAX_BITS = 64
MAX_ATOMS = 32
_KIND = {"cmp": 0, "between": 1, "assign": 2}
_OP = {"==": 0, "!=": 1, "<": 2, "<=": 3, ">": 4, ">=": 5, "": 0}


def _leaf(leaf: Leaf) -> tuple[Any, ...]:
    return (
        leaf.bit,
        leaf.checkpoint,
        _KIND[leaf.kind],
        list(leaf.mask),
        _OP[leaf.op],
        leaf.value,
        leaf.lo,
        leaf.hi,
        [(list(mask), need) for mask, need in leaf.demands],
    )


@lru_cache(maxsize=256)
def _flatten(cq: CompiledQuery) -> tuple[Any, ...]:
    """Primitive form of the query structure (cached: analyses reuse queries)."""
    return (
        cq.atoms.deck_size,
        list(cq.atoms.counts),
        cq.atoms.pool,
        cq.plan.hand_size,
        list(cq.plan.batches),
        [_leaf(leaf) for leaf in cq.leaves],
        [list(prog) for _, prog in cq.outputs],
        [(j, list(mask)) for j, mask in cq.observers],
        [list(r) for r in cq.retire_after],
        cq.reserved_bits,
    )


@lru_cache(maxsize=64)
def _flatten_plan(plan: MulliganPlan) -> tuple[Any, ...]:
    """Primitive form of a mulligan plan."""
    return (
        [(list(mask), quota) for mask, quota in plan.policy.rules],
        [_leaf(leaf) for leaf in plan.keep_leaves],
        list(plan.keep_prog),
        list(plan.bottoms),
        plan.draw,
    )


def supported(cq: CompiledQuery) -> bool:
    """Whether the native engine can evaluate ``cq``."""
    return cq.reserved_bits + len(cq.leaves) <= MAX_BITS and cq.atoms.size <= MAX_ATOMS


def plan_supported(plan: MulliganPlan) -> bool:
    """Whether the native engine can evaluate the keep rule of ``plan``."""
    return len(plan.keep_leaves) <= MAX_BITS


class NativeEngine:
    """Rust implementation of the :class:`~mtgcalc.engine.base.Engine` protocol."""

    def __init__(self, *, early_resolution: bool = True, retirement: bool = True) -> None:
        from mtgcalc.engine.select import native_module

        module = native_module()
        if module is None:  # pragma: no cover - guarded by select.default_engine
            raise ImportError("mtgcalc_native is not installed")
        self._native = module
        self.early_resolution = early_resolution
        self.retirement = retirement
        self._reference = ExactEngine(early_resolution=early_resolution, retirement=retirement)

    def _options(self, limit: int) -> tuple[int, bool, bool]:
        return (limit, self.early_resolution, self.retirement)

    def _call(self, name: str, *args: Any, limit: int) -> Any:
        try:
            return getattr(self._native, name)(*args, self._options(limit))
        except self._native.StateLimitExceeded as e:
            raise StateSpaceTooLargeError(int(e.args[0]), limit) from None

    def run(
        self, cq: CompiledQuery, init: InitialStates | None = None, *, limit: int = DEFAULT_LIMIT
    ) -> RunResult:
        """Evaluate ``cq``; falls back to the Python engine for unsupported shapes."""
        if not supported(cq):
            return self._reference.run(cq, init, limit=limit)
        start = None
        if init is not None:
            start = (
                [(list(s), list(b), bits, w) for (s, b, bits), w in init.states.items() if w],
                init.denominator,
                init.removed,
            )
        outputs, denominator, snapshots, peak = self._call("run", _flatten(cq), start, limit=limit)
        names = [name for name, _ in cq.outputs]
        snaps = {
            (cq.observers[i][0], cq.observers[i][1]): (tuple(nums), den)
            for i, nums, den in snapshots
        }
        return RunResult(dict(zip(names, outputs, strict=True)), denominator, snaps, peak)

    def mulligan(
        self, cq: CompiledQuery, plan: MulliganPlan, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[DepthResult, ...]:
        """Every mulligan depth, enumerated in Rust in one call."""
        if not (supported(cq) and plan_supported(plan)):
            return reference.mulligan_depths(self, cq, plan, limit=limit)
        names = [name for name, _ in cq.outputs]
        depths = self._call("mulligan", _flatten(cq), _flatten_plan(plan), limit=limit)
        return tuple(
            DepthResult(keep, total, dict(zip(names, outputs, strict=True)), den)
            for keep, total, outputs, den in depths
        )

    def hand_values(
        self, cq: CompiledQuery, plan: MulliganPlan, output: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[tuple[HandValue, ...], ...]:
        """Per-hand success values, computed in Rust in one call."""
        if not (supported(cq) and plan_supported(plan)):
            return reference.hand_values(self, cq, plan, output, limit=limit)
        index = [name for name, _ in cq.outputs].index(output)
        depths = self._call("hand_values", _flatten(cq), _flatten_plan(plan), index, limit=limit)
        return tuple(
            tuple(HandValue(tuple(hand), w, s, d) for hand, w, s, d in depth) for depth in depths
        )
