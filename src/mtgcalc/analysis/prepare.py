"""Compile a scenario plus named outputs into engine-ready form (LLD §6)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from mtgcalc.compile.compiler import CompiledQuery, compile_query
from mtgcalc.compile.logic import conjoin_bit
from mtgcalc.compile.policy import KEEP_BIT, MulliganPlan, build_plan
from mtgcalc.model.conditions import Condition, selectors_in
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Selector

KEEP_SUFFIX = "&keep"


@dataclass(frozen=True, slots=True)
class Prepared:
    """A compiled query, plus the mulligan plan when the scenario models mulligans.

    With a mulligan, bit ``KEEP_BIT`` is reserved for "this hand was kept" and every
    output ``o`` has a companion ``o + KEEP_SUFFIX`` = ``o AND keep``.
    """

    cq: CompiledQuery
    plan: MulliganPlan | None
    names: tuple[str, ...]


def prepare(
    scenario: Scenario,
    outputs: Mapping[str, Condition],
    *,
    turn: int = 0,
    observe: Sequence[tuple[int, Selector]] = (),
) -> Prepared:
    """Atomize, schedule and compile ``outputs`` for ``scenario``."""
    cfg = scenario.mulligan
    if cfg is None:
        cq = compile_query(
            scenario.deck,
            scenario.game,
            outputs,
            hand_size=scenario.game.hand_size,
            turn=turn,
            observe=observe,
        )
        return Prepared(cq, None, tuple(outputs))

    extra = [*selectors_in(cfg.keep_rule), *(g.selector for g in cfg.priority)]
    # The whole drawn hand (including cards later bottomed) leaves the top of the library,
    # so validating hand=draw_size enforces FR-42 (draws never reach the bottomed cards).
    cq = compile_query(
        scenario.deck,
        scenario.game,
        outputs,
        hand_size=cfg.draw_size,
        turn=turn,
        observe=observe,
        extra_selectors=extra,
        reserved_bits=1,
    )
    with_keep = tuple(
        (name + KEEP_SUFFIX, conjoin_bit(prog, KEEP_BIT)) for name, prog in cq.outputs
    )
    cq = replace(cq, outputs=cq.outputs + with_keep)
    plan = build_plan(cfg, list(outputs.values()), cq.atoms)
    return Prepared(cq, plan, tuple(outputs))
