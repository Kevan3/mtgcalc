"""Mulligan analysis (LLD §6.2, FR-40..FR-48, MATH §9).

The engine enumerates each depth's drawn hands (``Engine.mulligan`` /
``Engine.hand_values``, in Rust when the native engine is installed) and returns exact
integers. This module turns them into probabilities: depths are combined with the law of
total probability (MATH §9.3), and the optimal keep strategy is found by backward
induction (MATH §9.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from mtgcalc.analysis.prepare import KEEP_SUFFIX, Prepared, prepare
from mtgcalc.engine.base import DEFAULT_LIMIT, Engine
from mtgcalc.engine.select import default_engine
from mtgcalc.errors import ValidationError
from mtgcalc.math.comb import binom
from mtgcalc.model.conditions import Condition
from mtgcalc.model.results import (
    KeptHand,
    MulliganReport,
    MulliganRow,
    OptimalKeepReport,
    OptimalKeepRow,
)
from mtgcalc.model.scenario import Scenario

Vector = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DepthOutcome:
    """Exact per-depth results for every output."""

    depth: int
    hand_size: int
    p_keep: Fraction
    forced: Mapping[str, Fraction] = field(default_factory=dict)
    with_keep: Mapping[str, Fraction] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MulliganOutcome:
    """Per-depth outcomes, reach probabilities and strategy-level output probabilities."""

    depths: tuple[DepthOutcome, ...]
    reach: tuple[Fraction, ...]
    strategy: Mapping[str, Fraction]


def run_mulligan(
    prep: Prepared, *, engine: Engine | None = None, limit: int = DEFAULT_LIMIT
) -> MulliganOutcome:
    """Evaluate every output of ``prep`` under the mulligan strategy."""
    plan = prep.plan
    if plan is None:
        raise ValidationError("scenario.mulligan", "scenario has no mulligan configuration")
    eng = engine if engine is not None else default_engine()
    depths = tuple(
        DepthOutcome(
            depth=m,
            hand_size=plan.draw - plan.bottoms[m],
            p_keep=Fraction(d.keep_weight, d.hands_total),
            forced={n: Fraction(d.outputs[n], d.denominator) for n in prep.names},
            with_keep={n: Fraction(d.outputs[n + KEEP_SUFFIX], d.denominator) for n in prep.names},
        )
        for m, d in enumerate(eng.mulligan(prep.cq, plan, limit=limit))
    )
    reach = [Fraction(1)]
    for d in depths[:-1]:
        reach.append(reach[-1] * (1 - d.p_keep))
    strategy = {
        n: sum((r * d.with_keep[n] for r, d in zip(reach, depths, strict=True)), Fraction(0))
        for n in prep.names
    }
    return MulliganOutcome(depths, tuple(reach), strategy)


def mulligan_report(
    scenario: Scenario,
    success: Condition,
    *,
    turn: int = 0,
    engine: Engine | None = None,
    limit: int = DEFAULT_LIMIT,
) -> MulliganReport:
    """Per-depth and strategy-level mulligan statistics (FR-45, FR-46)."""
    prep = prepare(scenario, {"success": success}, turn=turn)
    out = run_mulligan(prep, engine=engine, limit=limit)
    rows = tuple(
        MulliganRow(
            depth=d.depth,
            hand_size=d.hand_size,
            p_reach=r,
            p_keep_given_reach=d.p_keep,
            p_success_forced=d.forced["success"],
            p_success_and_keep_given_reach=d.with_keep["success"],
        )
        for d, r in zip(out.depths, out.reach, strict=True)
    )
    stop = [r * d.p_keep for d, r in zip(out.depths, out.reach, strict=True)]
    return MulliganReport(
        rows=rows,
        p_success=out.strategy["success"],
        expected_mulligans=sum((m * p for m, p in enumerate(stop)), Fraction(0)),
        expected_hand_size=sum(
            (d.hand_size * p for d, p in zip(out.depths, stop, strict=True)), Fraction(0)
        ),
    )


def optimal_keep(
    scenario: Scenario,
    success: Condition,
    *,
    turn: int = 0,
    engine: Engine | None = None,
    limit: int = DEFAULT_LIMIT,
) -> OptimalKeepReport:
    """Keep strategy maximizing P(success) for the configured bottom policy (FR-48).

    The scenario's keep rule is ignored (it is what is being optimized); its priority
    groups and bottom counts are used. Backward induction (MATH §9.5)::

        V_M = E[s_M(H)],  V_m = E[max(s_m(H), V_{m+1})],  keep iff s_m(H) >= V_{m+1}
    """
    prep = prepare(scenario, {"success": success}, turn=turn)
    plan = prep.plan
    if plan is None:
        raise ValidationError("scenario.mulligan", "scenario has no mulligan configuration")
    eng = engine if engine is not None else default_engine()
    total = binom(prep.cq.atoms.deck_size, plan.draw)
    per_depth = [
        [(v.hand, Fraction(v.weight, total), Fraction(v.success, v.denominator)) for v in depth]
        for depth in eng.hand_values(prep.cq, plan, "success", limit=limit)
    ]

    # Backward induction from the last depth (where every hand is kept).
    continuation: Fraction | None = None  # V_{m+1}: value of mulliganing; None at depth M
    out_rows: list[OptimalKeepRow] = []
    for m in range(plan.max_mulligans, -1, -1):
        hands = tuple(
            KeptHand(h, p, s, keep=continuation is None or s >= continuation)
            for h, p, s in per_depth[m]
        )
        value = sum(
            (k.probability * (k.success if k.keep else _known(continuation)) for k in hands),
            Fraction(0),
        )
        out_rows.append(
            OptimalKeepRow(
                depth=m,
                hand_size=plan.draw - plan.bottoms[m],
                continuation_value=continuation if continuation is not None else Fraction(0),
                p_keep_given_reach=sum((k.probability for k in hands if k.keep), Fraction(0)),
                hands=hands,
            )
        )
        continuation = value
    assert continuation is not None
    return OptimalKeepReport(continuation, tuple(reversed(out_rows)), prep.cq.atoms.names)


def _known(value: Fraction | None) -> Fraction:
    """A continuation value that must exist (a hand is only mulliganed if one does)."""
    assert value is not None
    return value
