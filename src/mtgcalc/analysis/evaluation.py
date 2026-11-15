"""Evaluate named output conditions on a scenario with a chosen method (LLD §8, FR-71)."""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Literal

from mtgcalc.analysis.mulligan import run_mulligan
from mtgcalc.analysis.prepare import Prepared, prepare
from mtgcalc.engine.base import DEFAULT_LIMIT, Engine
from mtgcalc.engine.montecarlo import simulate
from mtgcalc.engine.select import default_engine
from mtgcalc.errors import StateSpaceTooLargeError
from mtgcalc.math.intervals import wilson
from mtgcalc.model.conditions import Condition
from mtgcalc.model.results import Probability
from mtgcalc.model.scenario import Scenario

Method = Literal["exact", "montecarlo", "auto"]


def exact_values(
    prep: Prepared, *, engine: Engine | None = None, limit: int = DEFAULT_LIMIT
) -> dict[str, Fraction]:
    """Exact probability of every output (strategy-level when mulligans are modelled)."""
    if prep.plan is not None:
        return dict(run_mulligan(prep, engine=engine, limit=limit).strategy)
    eng = engine if engine is not None else default_engine()
    res = eng.run(prep.cq, limit=limit)
    return {n: Fraction(res.outputs[n], res.denominator) for n in prep.names}


def montecarlo_counts(
    prep: Prepared, *, trials: int, seed: int | None
) -> tuple[dict[str, int], int]:
    """Simulated success counts of every output."""
    hits, n = simulate(prep.cq, trials=trials, seed=seed, mulligan=prep.plan)
    return {name: hits[name] for name in prep.names}, n


def evaluate(
    scenario: Scenario,
    outputs: Mapping[str, Condition],
    *,
    turn: int = 0,
    method: Method = "exact",
    limit: int = DEFAULT_LIMIT,
    trials: int = 200_000,
    seed: int | None = None,
) -> dict[str, Probability]:
    """Probability of each named output with the requested method.

    ``"auto"`` runs the exact engine and falls back to Monte Carlo (with a warning) only
    if the engine exceeds ``limit`` live states; the engine checks that limit as it
    goes, so the attempt costs at most ``limit`` states of work.
    """
    prep = prepare(scenario, outputs, turn=turn)
    warnings: tuple[str, ...] = ()
    if method in ("exact", "auto"):
        try:
            return _exact(prep, limit)
        except StateSpaceTooLargeError:
            if method == "exact":
                raise
        warnings = (f"exact computation needed more than {limit:,} states; used Monte Carlo",)
    hits, n = montecarlo_counts(prep, trials=trials, seed=seed)
    return {
        name: Probability(None, h / n, wilson(h, n), "montecarlo", warnings)
        for name, h in hits.items()
    }


def _exact(prep: Prepared, limit: int) -> dict[str, Probability]:
    return {n: Probability(v) for n, v in exact_values(prep, limit=limit).items()}
