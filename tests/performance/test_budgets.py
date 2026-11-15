"""Performance budgets PF1-PF3 for NFR-03..NFR-05 (TP §10). Run with ``-m perf``."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

import pytest

from mtgcalc import (
    Card,
    Deck,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    Scenario,
    count,
    mulligan_report,
    probability,
    tag,
)
from mtgcalc.compile import policy
from mtgcalc.math.comb import transitions

pytestmark = pytest.mark.perf

DECK60 = Deck(
    (
        Card("Land", 22, frozenset({"land"})),
        Card("MDFC", 2, frozenset({"land", "spell", "removal"})),
        Card("Ramp", 4, frozenset({"ramp", "spell"})),
        Card("Removal", 6, frozenset({"removal", "spell"})),
        Card("Threat", 8, frozenset({"threat", "spell"})),
        Card("Other", 18, frozenset({"spell"})),
    )
)
DECK99 = Deck(
    (
        Card("Land", 35, frozenset({"land"})),
        Card("MDFC", 2, frozenset({"land", "removal"})),
        Card("Rock", 10, frozenset({"ramp"})),
        Card("Draw", 10, frozenset({"draw"})),
        Card("Removal", 8, frozenset({"removal"})),
        Card("Other", 34),
    )
)


def median_seconds(fn: Callable[[], object], runs: int = 5) -> float:
    times = []
    for _ in range(runs):
        transitions.cache_clear()
        policy.bottom.cache_clear()
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def test_pf1_single_checkpoint_four_groups() -> None:
    q = "land >= 3 @T3 AND ramp >= 1 @T3 AND removal >= 1 @T3 AND threat >= 2 @T3"
    assert median_seconds(lambda: probability(Scenario(DECK60), q)) < 0.1


def test_pf2_ten_checkpoints_hundred_cards() -> None:
    q = " AND ".join(f"land >= {min(t + 1, 6)} @T{t}" for t in range(1, 11))
    q += " AND ramp >= 1 @T2 AND draw >= 1 @T5 AND removal >= 1 @T6"
    sc = Scenario(DECK99, GameConfig(on_play=False))
    assert median_seconds(lambda: probability(sc, q)) < 1.0


def test_pf3_mulligan_report() -> None:
    cfg = MulliganConfig(
        (
            PriorityGroup(tag("land"), 3),
            PriorityGroup(tag("ramp"), 1),
            PriorityGroup(tag("threat"), 1),
        ),
        keep_rule=count("land").between(2, 5),
        max_mulligans=3,
        free_mulligans=1,
    )
    sc = Scenario(DECK60, GameConfig(), cfg)
    success = "land >= 3 @T3 AND ramp >= 1 @T2 AND threat >= 1 @T5"
    assert median_seconds(lambda: mulligan_report(sc, success), runs=3) < 3.0
