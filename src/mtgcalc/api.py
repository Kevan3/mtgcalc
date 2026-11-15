"""Public facade (LLD §8, NFR-08).

Every function is pure: immutable inputs in, immutable results out. Conditions may be
given as AST objects, :class:`Query` objects, or text (FR-37).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction

from mtgcalc.analysis import mulligan as _mulligan
from mtgcalc.analysis import optimizer as _optimizer
from mtgcalc.analysis import stats as _stats
from mtgcalc.analysis.evaluation import Method, evaluate
from mtgcalc.engine.base import DEFAULT_LIMIT
from mtgcalc.errors import ValidationError
from mtgcalc.io.decklist import format_decklist, parse_decklist
from mtgcalc.io.expr import (
    format_condition,
    format_query,
    format_selector,
    parse_condition,
    parse_query,
    parse_selector,
)
from mtgcalc.math.comb import binom
from mtgcalc.model.conditions import And, Condition, Query
from mtgcalc.model.results import (
    ConditionalResult,
    Distribution,
    MulliganReport,
    OptimalKeepReport,
    OptimizeResult,
    Probability,
    ThresholdTable,
    TurnTable,
)
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Selector

__all__ = [
    "distribution",
    "format_condition",
    "format_decklist",
    "format_query",
    "format_selector",
    "hypergeom",
    "mulligan_report",
    "optimal_keep",
    "optimize",
    "parse_condition",
    "parse_decklist",
    "parse_query",
    "parse_selector",
    "probability",
    "threshold_table",
    "turn_table",
]


def _query(q: Query | Condition | str) -> Query:
    if isinstance(q, str):
        return parse_query(q)
    if isinstance(q, Query):
        return q
    return Query(q)


def _condition(c: Condition | str) -> Condition:
    return parse_condition(c) if isinstance(c, str) else c


def hypergeom(N: int, K: int, n: int) -> Distribution:
    """Distribution of successes in ``n`` draws from ``N`` cards with ``K`` successes (FR-10)."""
    if not (N > 0 and 0 <= K <= N and 0 <= n <= N):
        raise ValidationError("hypergeom", "requires N > 0, 0 <= K <= N and 0 <= n <= N")
    total = binom(N, n)
    top = min(K, n)
    return Distribution(
        0, tuple(Fraction(binom(K, k) * binom(N - K, n - k), total) for k in range(top + 1))
    )


def probability(
    scenario: Scenario,
    query: Query | Condition | str,
    *,
    engine: Method = "exact",
    limit: int = DEFAULT_LIMIT,
    trials: int = 200_000,
    seed: int | None = None,
) -> Probability | ConditionalResult:
    """P(condition), or P(condition | given) when the query has ``given`` (FR-11..FR-35).

    Under a mulligan configuration the probability is strategy-level (FR-46).
    """
    q = _query(query)
    outputs: dict[str, Condition] = (
        {"p": q.condition}
        if q.given is None
        else {"joint": And((q.condition, q.given)), "given": q.given}
    )
    res = evaluate(
        scenario, outputs, turn=q.turn, method=engine, limit=limit, trials=trials, seed=seed
    )
    if q.given is None:
        return res["p"]
    joint, given = res["joint"], res["given"]
    if given.value == 0:
        return ConditionalResult(joint, given, None)
    if joint.exact is not None and given.exact is not None:
        return ConditionalResult(joint, given, Probability(joint.exact / given.exact))
    estimate = joint.value / given.value
    return ConditionalResult(
        joint, given, Probability(None, estimate, None, "montecarlo", joint.warnings)
    )


def distribution(
    scenario: Scenario, selector: Selector, turn: int = 0, *, limit: int = DEFAULT_LIMIT
) -> Distribution:
    """Exact distribution of the number of seen cards matching ``selector`` (FR-30)."""
    return _stats.distribution(scenario, selector, turn, limit=limit)


def threshold_table(
    scenario: Scenario,
    selector: Selector,
    turns: Sequence[int],
    ks: Iterable[int] | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
) -> ThresholdTable:
    """Exactly / at least / at most table for several turns (FR-31)."""
    return _stats.threshold_table(scenario, selector, turns, ks, limit=limit)


def turn_table(
    scenario: Scenario,
    condition: Condition | str,
    turns: Sequence[int],
    *,
    limit: int = DEFAULT_LIMIT,
) -> TurnTable:
    """P(condition) by each turn (FR-24)."""
    return _stats.turn_table(scenario, _condition(condition), turns, limit=limit)


def mulligan_report(
    scenario: Scenario, success: Condition | str, *, turn: int = 0, limit: int = DEFAULT_LIMIT
) -> MulliganReport:
    """Per-depth and strategy-level mulligan statistics (FR-45, FR-46)."""
    return _mulligan.mulligan_report(scenario, _condition(success), turn=turn, limit=limit)


def optimal_keep(
    scenario: Scenario, success: Condition | str, *, turn: int = 0, limit: int = DEFAULT_LIMIT
) -> OptimalKeepReport:
    """Optimal keep strategy for the configured bottom policy (FR-48)."""
    return _mulligan.optimal_keep(scenario, _condition(success), turn=turn, limit=limit)


def optimize(problem: _optimizer.OptimizeProblem, *, limit: int = DEFAULT_LIMIT) -> OptimizeResult:
    """Card-count optimization (FR-50..FR-53)."""
    return _optimizer.optimize(problem, limit=limit)
