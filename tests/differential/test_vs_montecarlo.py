"""Exact engine vs. Monte Carlo on realistic scenarios (TP §1, §13).

Seeds are fixed, so these tests are deterministic. Each check uses a 99.9% Wilson
interval, so a failure indicates a real discrepancy (or a deliberate seed/code change).
"""

from __future__ import annotations

import pytest

from mtgcalc import (
    Card,
    Category,
    Deck,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    Scenario,
    count,
    tag,
)
from mtgcalc.api import probability
from mtgcalc.math.intervals import wilson
from mtgcalc.model.results import Probability

Z999 = 3.2905267314919255
TRIALS = 20_000

COMMANDER = Deck(
    (
        Card("Basic Land", 33, frozenset({"land"})),
        Card("MDFC", 3, frozenset({"land", "removal"})),
        Card("Mana Rock", 8, frozenset({"ramp"})),
        Card("Ramp Creature", 4, frozenset({"ramp", "creature"})),
        Card("Card Draw", 10, frozenset({"draw"})),
        Card("Sol Ring", 1, frozenset({"ramp", "fast"})),
        Card("Other", 40),
    )
)
CONSTRUCTED = Deck.from_counts(
    60, {"land": 23, "dual": Category(4, frozenset({"land"})), "one-drop": 8}
)

CASES = [
    (
        "constructed-curve",
        Scenario(CONSTRUCTED),
        "land >= 2 @T0 AND land >= 4 @T4 AND one-drop >= 1 @T1",
    ),
    (
        "constructed-or",
        Scenario(CONSTRUCTED, GameConfig(on_play=False)),
        "dual >= 1 @T2 OR land >= 5 @T5",
    ),
    (
        "commander-assign",
        Scenario(COMMANDER, GameConfig(on_play=False)),
        "assign(land >= 3, ramp >= 1, removal >= 1) @T3",
    ),
    (
        "commander-mulligan",
        Scenario(
            COMMANDER,
            GameConfig(on_play=False),
            MulliganConfig(
                (
                    PriorityGroup(tag("land"), 3),
                    PriorityGroup(tag("ramp"), 1),
                    PriorityGroup(tag("draw"), 1),
                ),
                keep_rule=count("land").between(2, 5),
                max_mulligans=2,
                free_mulligans=1,
            ),
        ),
        "land >= 3 @T3 AND ramp >= 1 @T2",
    ),
    (
        "constructed-mulligan-conditional",
        Scenario(
            CONSTRUCTED,
            GameConfig(),
            MulliganConfig(
                (PriorityGroup(tag("land")), PriorityGroup(tag("one-drop"), 1)),
                keep_rule=count("land").between(2, 4),
                max_mulligans=2,
            ),
        ),
        "one-drop >= 1 @T1 AND land >= 3 @T3",
    ),
]


@pytest.mark.mc
@pytest.mark.parametrize(("name", "scenario", "query"), CASES, ids=[c[0] for c in CASES])
def test_exact_inside_monte_carlo_interval(name: str, scenario: Scenario, query: str) -> None:
    exact = probability(scenario, query)
    mc = probability(scenario, query, engine="montecarlo", trials=TRIALS, seed=20261114)
    assert isinstance(exact, Probability) and isinstance(mc, Probability)
    assert mc.estimate is not None
    lo, hi = wilson(round(mc.estimate * TRIALS), TRIALS, z=Z999)
    assert lo <= exact.value <= hi, (name, exact.value, (lo, hi))
