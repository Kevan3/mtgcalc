"""Distributions, threshold tables and turn tables (LLD §6.1, FR-14, FR-24, FR-30, FR-31)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction

from mtgcalc.analysis.evaluation import exact_values
from mtgcalc.analysis.prepare import prepare
from mtgcalc.engine.base import DEFAULT_LIMIT
from mtgcalc.engine.select import default_engine
from mtgcalc.model.conditions import At, Compare, Condition
from mtgcalc.model.results import Distribution, ThresholdRow, ThresholdTable, TurnRow, TurnTable
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Selector


def _cards_seen(scenario: Scenario, turn: int) -> int:
    hand = (
        scenario.mulligan.hand_size(0) if scenario.mulligan is not None else scenario.game.hand_size
    )
    return hand + scenario.game.draws_through(turn)


def distributions(
    scenario: Scenario, selector: Selector, turns: Sequence[int], *, limit: int = DEFAULT_LIMIT
) -> dict[int, Distribution]:
    """Exact distribution of ``count(selector)`` at each turn, from one evaluation."""
    turns = sorted(set(turns))
    if scenario.mulligan is None:
        prep = prepare(scenario, {}, observe=[(t, selector) for t in turns])
        res = default_engine().run(prep.cq, limit=limit)
        out = {}
        for t in turns:
            nums, den = res.snapshots[(prep.cq.plan.index(t), prep.cq.atoms.mask(selector))]
            out[t] = Distribution(t, tuple(Fraction(x, den) for x in nums))
        return out
    # Under a mulligan strategy the distribution mixes depths, so evaluate {count == k}
    # as outputs and combine them at strategy level.
    outputs: dict[str, Condition] = {
        f"{t}:{k}": At(t, Compare(selector, "==", k))
        for t in turns
        for k in range(_cards_seen(scenario, t) + 1)
    }
    values = exact_values(prepare(scenario, outputs), limit=limit)
    result = {}
    for t in turns:
        pmf = [values[f"{t}:{k}"] for k in range(_cards_seen(scenario, t) + 1)]
        while len(pmf) > 1 and pmf[-1] == 0:
            pmf.pop()
        result[t] = Distribution(t, tuple(pmf))
    return result


def distribution(
    scenario: Scenario, selector: Selector, turn: int = 0, *, limit: int = DEFAULT_LIMIT
) -> Distribution:
    """Exact distribution of ``count(selector)`` by ``turn`` (FR-14, FR-30)."""
    return distributions(scenario, selector, [turn], limit=limit)[turn]


def threshold_table(
    scenario: Scenario,
    selector: Selector,
    turns: Sequence[int],
    ks: Iterable[int] | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
) -> ThresholdTable:
    """Rows (turn, k): P(exactly k), P(at least k), P(at most k) (FR-31)."""
    dists = distributions(scenario, selector, turns, limit=limit)
    rows = []
    for t, d in sorted(dists.items()):
        for k in ks if ks is not None else range(len(d.pmf)):
            rows.append(ThresholdRow(t, k, d.exactly(k), d.at_least(k), d.at_most(k)))
    return ThresholdTable(tuple(rows))


def turn_table(
    scenario: Scenario, condition: Condition, turns: Sequence[int], *, limit: int = DEFAULT_LIMIT
) -> TurnTable:
    """P(condition) by each turn, from one evaluation (FR-24)."""
    turns = sorted(set(turns))
    outputs: dict[str, Condition] = {f"t{t}": At(t, condition) for t in turns}
    values = exact_values(prepare(scenario, outputs), limit=limit)
    return TurnTable(tuple(TurnRow(t, _cards_seen(scenario, t), values[f"t{t}"]) for t in turns))
