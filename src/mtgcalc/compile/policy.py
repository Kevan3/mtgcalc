"""London-mulligan bottom policy driven by user-given priority groups (LLD §4.5, ADR-0005).

Given a drawn hand's atom composition, decide how many cards of each atom go to the
bottom. The decision depends only on the composition, so it is memoized (MATH §9.4).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from mtgcalc.compile.atomizer import AtomTable
from mtgcalc.compile.compiler import compile_predicate
from mtgcalc.compile.logic import Leaf, Mask, Program, leaf_bits, run2
from mtgcalc.errors import ValidationError
from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Implies,
    Not,
    Or,
)
from mtgcalc.model.mulligan import MulliganConfig
from mtgcalc.model.selectors import Selector

#: Predicate bit reserved for "this opening hand was kept" in mulligan analyses.
KEEP_BIT = 0


@dataclass(frozen=True, slots=True)
class ResolvedPolicy:
    """Priority rules ``(atom mask, quota)``, highest priority first."""

    rules: tuple[tuple[Mask, int], ...]


def lower_bounds(conditions: Sequence[Condition]) -> dict[Selector, int]:
    """Largest lower bound each selector must reach for the conditions to hold.

    Only bounds that are *required* are collected: leaves in positive polarity under
    AND / OR / at-least / implication consequents, and negated upper bounds.
    """
    bounds: dict[Selector, int] = defaultdict(int)

    def note(sel: Selector, v: int) -> None:
        bounds[sel] = max(bounds[sel], v)

    def rec(c: Condition, positive: bool) -> None:
        match c:
            case Compare(sel, op, v):
                if positive and op in (">=", "=="):
                    note(sel, v)
                elif positive and op == ">":
                    note(sel, v + 1)
                elif not positive and op == "<":
                    note(sel, v)
                elif not positive and op == "<=":
                    note(sel, v + 1)
            case Between(sel, lo, _) if positive:
                note(sel, lo)
            case Assignable(demands) if positive:
                for d in demands:
                    note(d.sel, d.need)
            case And(items) | Or(items) | AtLeast(_, items):
                for it in items:
                    rec(it, positive)
            case Not(item):
                rec(item, not positive)
            case At(_, item):
                rec(item, positive)
            case Implies(_, b):
                rec(b, positive)
            case _:
                pass  # XOR / exactly / constants impose no one-sided bound

    for cond in conditions:
        rec(cond, True)
    return dict(bounds)


def resolve_policy(
    cfg: MulliganConfig, success: Sequence[Condition], atoms: AtomTable
) -> ResolvedPolicy:
    """Resolve priority groups to atom masks and quotas (explicit or derived)."""
    keep_bounds = lower_bounds([cfg.keep_rule])
    success_bounds = lower_bounds(success)
    rules: list[tuple[Mask, int]] = []
    for g in cfg.priority:
        if g.quota is not None:
            quota = g.quota
        elif g.selector in keep_bounds or g.selector in success_bounds:
            quota = max(keep_bounds.get(g.selector, 0), success_bounds.get(g.selector, 0))
        else:
            quota = cfg.draw_size
        rules.append((atoms.mask(g.selector), quota))
    return ResolvedPolicy(tuple(rules))


@lru_cache(maxsize=2**16)
def bottom(
    policy: ResolvedPolicy, hand: tuple[int, ...], pool_in_hand: int, n: int
) -> tuple[int, ...]:
    """Atom counts to put on the bottom when ``n`` cards must go.

    Order: (1) cards in no group (the pool first), (2) unprotected cards, lowest priority
    first, (3) protected cards, releasing the lowest-priority protections first. Cards
    up to each rule's quota are protected, multi-role atoms first.

    Returns the tracked-atom part; ``n - sum(result)`` pool cards are bottomed implicitly.
    """
    if not 0 <= n <= sum(hand) + pool_in_hand:
        raise ValidationError("bottom", "cannot bottom more cards than are in hand")
    m = len(hand)
    rule_count = [0] * m
    best_rule = [len(policy.rules)] * m  # len(rules) = "in no group"
    for r, (mask, _) in enumerate(policy.rules):
        for i in mask:
            rule_count[i] += 1
            best_rule[i] = min(best_rule[i], r)

    protected = [0] * m
    log: list[tuple[int, int]] = []  # (atom, qty) in priority order
    for mask, quota in policy.rules:
        need = quota - sum(protected[i] for i in mask)
        for i in sorted(mask, key=lambda a: (-rule_count[a], a)):
            if need <= 0:
                break
            take = min(need, hand[i] - protected[i])
            if take > 0:
                protected[i] += take
                need -= take
                log.append((i, take))

    bott = [0] * m
    left = n - min(n, pool_in_hand)
    for i in sorted(range(m), key=lambda a: (-best_rule[a], a)):
        take = min(left, hand[i] - protected[i])
        bott[i] += take
        left -= take
    for i, qty in reversed(log):
        if left == 0:
            break
        take = min(left, qty)
        bott[i] += take
        left -= take
    assert left == 0, "bottoming invariant violated"
    return tuple(bott)


@dataclass(frozen=True, slots=True)
class MulliganPlan:
    """Compiled London-mulligan procedure: bottom policy, keep rule and bottom counts."""

    policy: ResolvedPolicy
    keep_leaves: tuple[Leaf, ...]
    keep_prog: Program
    bottoms: tuple[int, ...]  # cards bottomed at each depth 0..M
    draw: int

    @property
    def max_mulligans(self) -> int:
        """M (the hand at depth M is always kept)."""
        return len(self.bottoms) - 1

    def keeps(self, kept: tuple[int, ...]) -> bool:
        """Whether the keep rule accepts a kept-hand composition."""
        return run2(self.keep_prog, leaf_bits(self.keep_leaves, kept))


def build_plan(cfg: MulliganConfig, success: Sequence[Condition], atoms: AtomTable) -> MulliganPlan:
    """Compile a mulligan configuration against an atom table.

    ``atoms`` must have been built with the keep rule's and priority groups' selectors.
    """
    keep_leaves, keep_prog = compile_predicate(cfg.keep_rule, atoms)
    return MulliganPlan(
        policy=resolve_policy(cfg, success, atoms),
        keep_leaves=keep_leaves,
        keep_prog=keep_prog,
        bottoms=tuple(cfg.bottom_count(m) for m in range(cfg.max_mulligans + 1)),
        draw=cfg.draw_size,
    )
