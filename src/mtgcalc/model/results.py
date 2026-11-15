"""Immutable result types (LLD §3.7).

Exact values are :class:`~fractions.Fraction`; ``.value`` style accessors give floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from mtgcalc.errors import ValidationError

Counts = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class Probability:
    """A probability: exact (``method="exact"``) or estimated (``method="montecarlo"``)."""

    exact: Fraction | None
    estimate: float | None = None
    ci95: tuple[float, float] | None = None
    method: Literal["exact", "montecarlo"] = "exact"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.exact is None and self.estimate is None:
            raise ValidationError("probability", "needs an exact value or an estimate")

    @property
    def value(self) -> float:
        """Float value (correctly rounded from the exact value when available)."""
        if self.exact is not None:
            return float(self.exact)
        assert self.estimate is not None
        return self.estimate


@dataclass(frozen=True, slots=True)
class ConditionalResult:
    """P(A | B) together with P(A and B) and P(B) (FR-35)."""

    joint: Probability
    given: Probability
    result: Probability | None

    @property
    def defined(self) -> bool:
        """False when P(B) = 0."""
        return self.result is not None


@dataclass(frozen=True, slots=True)
class Distribution:
    """Distribution of one group's count at one checkpoint (FR-14, FR-30)."""

    turn: int
    pmf: tuple[Fraction, ...]

    def exactly(self, k: int) -> Fraction:
        """P(X = k)."""
        return self.pmf[k] if 0 <= k < len(self.pmf) else Fraction(0)

    def at_least(self, k: int) -> Fraction:
        """P(X >= k)."""
        return sum(self.pmf[max(k, 0) :], Fraction(0))

    def at_most(self, k: int) -> Fraction:
        """P(X <= k)."""
        return sum(self.pmf[: max(k + 1, 0)], Fraction(0))

    def none(self) -> Fraction:
        """P(X = 0)."""
        return self.exactly(0)

    def cdf(self) -> tuple[Fraction, ...]:
        """P(X <= k) for each k."""
        return tuple(self.at_most(k) for k in range(len(self.pmf)))

    def sf(self) -> tuple[Fraction, ...]:
        """P(X >= k) for each k."""
        return tuple(self.at_least(k) for k in range(len(self.pmf)))

    @property
    def mean(self) -> Fraction:
        """E[X]."""
        return sum((k * p for k, p in enumerate(self.pmf)), Fraction(0))

    @property
    def variance(self) -> Fraction:
        """Var[X]."""
        m = self.mean
        return sum((k * k * p for k, p in enumerate(self.pmf)), Fraction(0)) - m * m


@dataclass(frozen=True, slots=True)
class ThresholdRow:
    """One (turn, k) row of a threshold table."""

    turn: int
    k: int
    exactly: Fraction
    at_least: Fraction
    at_most: Fraction


@dataclass(frozen=True, slots=True)
class ThresholdTable:
    """Threshold statistics for one group over turns (FR-31)."""

    rows: tuple[ThresholdRow, ...]


@dataclass(frozen=True, slots=True)
class TurnRow:
    """P(condition) by one turn."""

    turn: int
    cards_seen: int
    probability: Fraction


@dataclass(frozen=True, slots=True)
class TurnTable:
    """P(condition) for each requested turn (FR-24)."""

    rows: tuple[TurnRow, ...]


@dataclass(frozen=True, slots=True)
class MulliganRow:
    """Per-depth mulligan statistics (FR-45)."""

    depth: int
    hand_size: int
    p_reach: Fraction
    p_keep_given_reach: Fraction
    p_success_forced: Fraction
    p_success_and_keep_given_reach: Fraction


@dataclass(frozen=True, slots=True)
class MulliganReport:
    """Strategy-level mulligan results (FR-45, FR-46)."""

    rows: tuple[MulliganRow, ...]
    p_success: Fraction
    expected_mulligans: Fraction
    expected_hand_size: Fraction


@dataclass(frozen=True, slots=True)
class KeptHand:
    """One 7-card hand composition at one depth of the optimal-keep analysis."""

    atom_counts: tuple[int, ...]
    probability: Fraction
    success: Fraction
    keep: bool


@dataclass(frozen=True, slots=True)
class OptimalKeepRow:
    """Per-depth optimal-keep results (FR-48)."""

    depth: int
    hand_size: int
    continuation_value: Fraction
    p_keep_given_reach: Fraction
    hands: tuple[KeptHand, ...]


@dataclass(frozen=True, slots=True)
class OptimalKeepReport:
    """Optimal keep strategy by backward induction (FR-48, MATH §9.5)."""

    value: Fraction
    rows: tuple[OptimalKeepRow, ...]
    atoms: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class OptimizeResult:
    """Optimizer outcome (FR-53)."""

    counts: Counts
    probability: Fraction
    proven_optimal: bool
    evaluations: int
    frontier: tuple[tuple[Counts, Fraction], ...]
