"""Independent brute-force oracle (TP §6, ADR-0007).

Enumerates every card-by-card draw sequence with probability
``prod(remaining_of_type / remaining_total)`` and interprets the condition AST directly.
It shares **no** code with the engine's DP: no binomials, no atoms in the evaluation, no
batches, no state merging, no retirement or early resolution, no compiled leaves. Exclusive
assignment is decided by max-flow (the engine uses Hall's subset condition).

The only library code used is the public model (``matches``, ``GameConfig``) and, for
mulligans, the bottom-policy decision (as permitted by ADR-0007; the policy itself is
covered by its own unit and property tests).
"""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction

from mtgcalc.analysis.prepare import prepare
from mtgcalc.compile.policy import bottom
from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Const,
    Exactly,
    Implies,
    Not,
    Or,
    Query,
    Xor,
    children,
)
from mtgcalc.model.deck import Card
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import Selector, matches

Seq = tuple[int, ...]  # sequence of card-type indices


def sequences(counts: list[int], length: int) -> Iterator[tuple[Seq, Fraction]]:
    """Every ordered draw of ``length`` cards from types with ``counts``, with probability."""
    total = sum(counts)

    def rec(
        prefix: list[int], remaining: list[int], left: int, p: Fraction
    ) -> Iterator[tuple[Seq, Fraction]]:
        if len(prefix) == length:
            yield tuple(prefix), p
            return
        for t, r in enumerate(remaining):
            if r:
                remaining[t] -= 1
                prefix.append(t)
                yield from rec(prefix, remaining, left - 1, p * Fraction(r, left))
                prefix.pop()
                remaining[t] += 1

    yield from rec([], list(counts), total, Fraction(1))


def max_flow_assignable(seen_cards: list[Card], demands: list[tuple[Selector, int]]) -> bool:
    """Can distinct cards satisfy all demands? Augmenting-path bipartite matching with
    demand multiplicities expanded into unit slots."""
    slots = [sel for sel, need in demands for _ in range(need)]
    match_of_card: dict[int, int] = {}

    def augment(slot: int, visited: set[int]) -> bool:
        for ci, c in enumerate(seen_cards):
            if ci in visited or not matches(slots[slot], c):
                continue
            visited.add(ci)
            if ci not in match_of_card or augment(match_of_card[ci], visited):
                match_of_card[ci] = slot
                return True
        return False

    return all(augment(s, set()) for s in range(len(slots)))


def evaluate(cond: Condition, seen_at: dict[int, list[Card]], turn: int) -> bool:
    """Direct recursive interpretation of a condition."""

    def count(sel: Selector, t: int) -> int:
        return sum(1 for c in seen_at[t] if matches(sel, c))

    match cond:
        case Compare(sel, op, v):
            x = count(sel, turn)
            return {"==": x == v, "!=": x != v, "<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v}[
                op
            ]
        case Between(sel, lo, hi):
            return lo <= count(sel, turn) <= hi
        case Assignable(demands):
            return max_flow_assignable(seen_at[turn], [(d.sel, d.need) for d in demands])
        case At(t, item):
            return evaluate(item, seen_at, t)
        case Const(v):
            return v
        case Not(item):
            return not evaluate(item, seen_at, turn)
        case And(items):
            return all(evaluate(i, seen_at, turn) for i in items)
        case Or(items):
            return any(evaluate(i, seen_at, turn) for i in items)
        case Xor(a, b):
            return evaluate(a, seen_at, turn) != evaluate(b, seen_at, turn)
        case Implies(a, b):
            return (not evaluate(a, seen_at, turn)) or evaluate(b, seen_at, turn)
        case AtLeast(n, items):
            return sum(evaluate(i, seen_at, turn) for i in items) >= n
        case Exactly(n, items):
            return sum(evaluate(i, seen_at, turn) for i in items) == n
    raise TypeError(cond)


def turns_used(cond: Condition, default: int) -> set[int]:
    """Every checkpoint turn the condition reads (plus the default)."""
    out = {default}

    def rec(c: Condition) -> None:
        if isinstance(c, At):
            out.add(c.turn)
        for ch in children(c):
            rec(ch)

    rec(cond)
    return out


def oracle_probabilities(scenario: Scenario, query: Query) -> tuple[Fraction, Fraction]:
    """Return (P(condition and given), P(given)) under the scenario (strategy-level with
    mulligans). ``given`` absent means P(given) = 1."""
    given = query.given if query.given is not None else Const(True)
    lib = scenario.deck.library
    counts = [c.quantity for c in lib]
    turns = turns_used(query.condition, query.turn) | turns_used(given, query.turn)
    draws = {t: scenario.game.draws_through(t) for t in turns}
    total_draws = max(draws.values())

    def outcome(kept: list[Card], later: list[Card]) -> tuple[bool, bool]:
        seen_at = {t: kept + later[: draws[t]] for t in turns}
        a = evaluate(query.condition, seen_at, query.turn)
        b = evaluate(given, seen_at, query.turn)
        return a and b, b

    if scenario.mulligan is None:
        h = scenario.game.hand_size
        joint = marg = Fraction(0)
        for seq, p in sequences(counts, h + total_draws):
            cards = [lib[t] for t in seq]
            a, b = outcome(cards[:h], cards[h:])
            joint += p if a else 0
            marg += p if b else 0
        return joint, marg

    cfg = scenario.mulligan
    outputs = {"q": query.condition, "g": given}
    prep = prepare(scenario, outputs, turn=query.turn)
    atoms, plan = prep.cq.atoms, prep.plan
    assert plan is not None

    def atom_of(card: Card) -> int:
        sig = tuple(matches(s, card) for s in atoms.selectors)
        return atoms.signatures.index(sig) if sig in atoms.signatures else -1

    reach = Fraction(1)
    joint = marg = Fraction(0)
    for m in range(cfg.max_mulligans + 1):
        keep_p = joint_m = marg_m = Fraction(0)
        for seq, p in sequences(counts, cfg.draw_size + total_draws):
            cards = [lib[t] for t in seq]
            hand, later = cards[: cfg.draw_size], cards[cfg.draw_size :]
            comp = [0] * atoms.size
            for c in hand:
                if atom_of(c) >= 0:
                    comp[atom_of(c)] += 1
            n_bottom = cfg.bottom_count(m)
            bott = list(bottom(plan.policy, tuple(comp), cfg.draw_size - sum(comp), n_bottom))
            pool_bottom = n_bottom - sum(bott)
            kept = []
            for c in hand:
                i = atom_of(c)
                if i >= 0 and bott[i] > 0:
                    bott[i] -= 1
                elif i < 0 and pool_bottom > 0:
                    pool_bottom -= 1
                else:
                    kept.append(c)
            keep = m == cfg.max_mulligans or evaluate(cfg.keep_rule, {0: kept}, 0)
            if not keep:
                continue
            keep_p += p
            a, b = outcome(kept, later)
            joint_m += p if a else 0
            marg_m += p if b else 0
        joint += reach * joint_m
        marg += reach * marg_m
        reach *= 1 - keep_p
    return joint, marg
