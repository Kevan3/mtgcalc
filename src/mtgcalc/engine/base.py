"""Engine interfaces (LLD §5.1, NFR-09)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from mtgcalc.compile.compiler import CompiledQuery
from mtgcalc.compile.policy import MulliganPlan

#: (seen counts, bottomed counts, predicate bits)
State = tuple[tuple[int, ...], tuple[int, ...], int]
#: (checkpoint index, atom mask) -> (numerators per count k, denominator at that checkpoint)
Snapshots = Mapping[tuple[int, tuple[int, ...]], tuple[tuple[int, ...], int]]

DEFAULT_LIMIT = 2_000_000


@dataclass(frozen=True, slots=True)
class InitialStates:
    """Weighted starting states (probability = weight / denominator).

    ``removed`` is the number of cards already taken from the top of the library
    (the whole drawn hand, including cards later put on the bottom).
    """

    states: Mapping[State, int]
    denominator: int
    removed: int


@dataclass(frozen=True, slots=True)
class RunResult:
    """Integer numerators per output over a common denominator."""

    outputs: Mapping[str, int]
    denominator: int
    snapshots: Snapshots = field(default_factory=dict)
    peak_states: int = 0


@dataclass(frozen=True, slots=True)
class DepthResult:
    """Integer results for one mulligan depth (MATH §9.3).

    P(keep) = ``keep_weight / hands_total``; every output (including its ``&keep``
    companion) is ``outputs[name] / denominator``.
    """

    keep_weight: int
    hands_total: int
    outputs: Mapping[str, int]
    denominator: int


@dataclass(frozen=True, slots=True)
class HandValue:
    """One 7-card draw composition at one depth (MATH §9.5).

    P(drawing it) = ``weight / C(N, draw)``; P(success | keep it) = ``success / denominator``.
    """

    hand: tuple[int, ...]
    weight: int
    success: int
    denominator: int


class Runner(Protocol):
    """Anything that can run the state DP (the minimal engine)."""

    def run(
        self, cq: CompiledQuery, init: InitialStates | None = None, *, limit: int = DEFAULT_LIMIT
    ) -> RunResult:
        """Evaluate all outputs (and observers) of ``cq`` from ``init``."""
        ...


class Engine(Runner, Protocol):
    """Exact evaluation of a compiled query. Native ports implement this protocol."""

    def mulligan(
        self, cq: CompiledQuery, plan: MulliganPlan, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[DepthResult, ...]:
        """Every mulligan depth: keep weight and all outputs from that depth's hands."""
        ...

    def hand_values(
        self, cq: CompiledQuery, plan: MulliganPlan, output: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[tuple[HandValue, ...], ...]:
        """Per depth, every drawn-hand composition with P(``output`` | keep it)."""
        ...
