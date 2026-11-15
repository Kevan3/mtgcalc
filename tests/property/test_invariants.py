"""Property-based invariants P1-P15 (TP §7)."""

from __future__ import annotations

import json
from fractions import Fraction

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mtgcalc import (
    And,
    Assignable,
    Compare,
    Deck,
    Not,
    Or,
    PriorityGroup,
    Query,
    Scenario,
    Xor,
    distribution,
    hypergeom,
    mulligan_report,
    optimal_keep,
    tag,
)
from mtgcalc.analysis.optimizer import OptimizeProblem, Variable, is_monotone, optimize
from mtgcalc.analysis.prepare import prepare
from mtgcalc.api import probability
from mtgcalc.compile.compiler import compile_query
from mtgcalc.engine.exact import ExactEngine
from mtgcalc.io.expr import format_query, parse_query
from mtgcalc.model.conditions import Condition
from mtgcalc.model.mulligan import MulliganConfig
from mtgcalc.model.results import ConditionalResult, Probability
from mtgcalc.model.serialization import from_dict, to_dict
from tests.strategies import conditions, decks, games, mulligan_cases, plain_cases


def p_of(scenario: Scenario, cond: Condition, turn: int = 0) -> Fraction:
    res = probability(scenario, Query(cond, None, turn))
    assert isinstance(res, Probability) and res.exact is not None
    return res.exact


@st.composite
def two_conditions(draw: st.DrawFn) -> tuple[Scenario, Condition, Condition, int]:
    scenario, q = draw(plain_cases())
    other = draw(conditions(scenario.deck, 3))
    return scenario, q.condition, other, q.turn


def _feasible(scenario: Scenario, *conds: Condition, turn: int) -> bool:
    try:
        prepare(scenario, {str(i): c for i, c in enumerate(conds)}, turn=turn)
    except Exception:
        return False
    return True


@given(two_conditions())
def test_p1_to_p5_probability_algebra(case: tuple[Scenario, Condition, Condition, int]) -> None:
    sc, a, b, t = case
    assume(_feasible(sc, a, b, turn=t))
    pa, pb = p_of(sc, a, t), p_of(sc, b, t)
    pand, por, pxor = p_of(sc, And((a, b)), t), p_of(sc, Or((a, b)), t), p_of(sc, Xor(a, b), t)
    assert 0 <= pa <= 1 and 0 <= pand <= min(pa, pb)  # P1
    assert pa + p_of(sc, Not(a), t) == 1  # P2
    assert por == pa + pb - pand  # P3
    assert pxor == por - pand  # P4
    cond = probability(sc, Query(a, b, t))  # P5
    assert isinstance(cond, ConditionalResult)
    if pb == 0:
        assert not cond.defined
    else:
        assert cond.result is not None and cond.result.exact is not None
        assert cond.result.exact * pb == pand


@given(plain_cases())
def test_p6_engine_switches_are_equivalent(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    cq = compile_query(
        sc.deck, sc.game, {"x": q.condition}, hand_size=sc.game.hand_size, turn=q.turn
    )
    results = set()
    for early in (True, False):
        for retire in (True, False):
            r = ExactEngine(early_resolution=early, retirement=retire).run(cq)
            results.add(Fraction(r.outputs["x"], r.denominator))
    assert len(results) == 1


@given(st.integers(1, 30), st.data())
def test_p7_fast_path_equals_general_engine(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    n = data.draw(st.integers(0, min(N, 12)))
    deck = Deck.from_counts(N, {"x": K})
    from mtgcalc import GameConfig

    general = distribution(Scenario(deck, GameConfig(hand_size=n)), tag("x"))
    fast = hypergeom(N, K, n)
    padded = fast.pmf + (Fraction(0),) * (len(general.pmf) - len(fast.pmf))
    assert general.pmf == padded[: len(general.pmf)]
    assert sum(general.pmf) == 1  # P1


@given(st.integers(2, 40), st.data())
def test_p8_moments_match_closed_forms(N: int, data: st.DataObject) -> None:
    K1 = data.draw(st.integers(0, N))
    K2 = data.draw(st.integers(0, N - K1))
    n = data.draw(st.integers(0, min(N, 10)))
    from mtgcalc import GameConfig, all_of, any_of

    deck = Deck.from_counts(N, {"a": K1, "b": K2})
    sc = Scenario(deck, GameConfig(hand_size=n))
    da, db = distribution(sc, tag("a")), distribution(sc, tag("b"))
    fpc = Fraction(N - n, N - 1) if N > 1 else Fraction(0)
    assert da.mean == Fraction(n * K1, N)
    assert da.variance == n * Fraction(K1, N) * Fraction(N - K1, N) * fpc
    # Cov(a, b) = (Var(a + b) - Var(a) - Var(b)) / 2 = -n (K1/N)(K2/N)(N-n)/(N-1)
    dab = distribution(sc, any_of("a", "b"))
    cov = (dab.variance - da.variance - db.variance) / 2
    assert cov == -n * Fraction(K1, N) * Fraction(K2, N) * fpc
    assert distribution(sc, all_of("a", "b")).mean == 0


@settings(max_examples=40)
@given(mulligan_cases())
def test_p10_optimal_keep_dominates_any_keep_rule(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    rule = mulligan_report(sc, q.condition, turn=q.turn)
    best = optimal_keep(sc, q.condition, turn=q.turn)
    assert best.value >= rule.p_success


@st.composite
def monotone_problems(draw: st.DrawFn) -> OptimizeProblem:
    """Single-variable problems built only from increasing leaves (MATH §10.2)."""
    var = Variable("v", 0, draw(st.integers(1, 10)))
    leaves = [
        Compare(
            tag(draw(st.sampled_from(["v", "w"]))),
            draw(st.sampled_from([">=", ">"])),
            draw(st.integers(0, 2)),
        )
        for _ in range(draw(st.integers(1, 3)))
    ]
    combos: list[Condition] = [And(tuple(leaves)), Or(tuple(leaves))] if len(leaves) > 1 else []
    cond: Condition = leaves[0] if not combos else draw(st.sampled_from(combos))
    from mtgcalc import Category

    return OptimizeProblem(
        deck_size=draw(st.integers(20, 25)),
        variables=(var,),
        fixed=(("w", Category(draw(st.integers(0, 5)))),),
        query=Query(cond, None, draw(st.integers(0, 2))),
        objective="max_probability",
    )


@settings(max_examples=40)
@given(monotone_problems())
def test_p11_p12_monotone_problems(problem: OptimizeProblem) -> None:
    from dataclasses import replace

    from mtgcalc.analysis.optimizer import build_deck

    (var,) = problem.variables
    assert is_monotone(problem, var)
    ps = [
        p_of(Scenario(build_deck(problem, (c,))), problem.query.condition, problem.query.turn)
        for c in range(var.lo, var.hi + 1)
    ]
    assert ps == sorted(ps)  # P12: non-decreasing in the variable
    target = ps[len(ps) // 2]
    bisect = optimize(replace(problem, objective="min_count", target=target))
    scan = optimize(replace(problem, objective="min_count", target=target, assume_monotone=False))
    assert bisect.counts == scan.counts  # P11
    assert bisect.proven_optimal and scan.proven_optimal


@given(plain_cases())
def test_p13_text_round_trip(case: tuple[Scenario, Query]) -> None:
    _, q = case
    assert parse_query(format_query(q), turn=q.turn) == q


@given(plain_cases(), games())
def test_p14_serialization_round_trip(case: tuple[Scenario, Query], game: object) -> None:
    sc, q = case
    for obj in (sc, q, game):
        assert from_dict(json.loads(json.dumps(to_dict(obj)))) == obj


@settings(max_examples=40)
@given(mulligan_cases())
def test_p14_serialization_mulligan(case: tuple[Scenario, Query]) -> None:
    sc, _ = case
    assert from_dict(json.loads(json.dumps(to_dict(sc)))) == sc


@given(plain_cases())
def test_p15_exclusive_implies_shared(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    from mtgcalc.model.conditions import walk

    for node in walk(q.condition):
        if isinstance(node, Assignable):
            shared = (
                And(tuple(Compare(d.sel, ">=", d.need) for d in node.demands))
                if len(node.demands) > 1
                else Compare(node.demands[0].sel, ">=", node.demands[0].need)
            )
            assume(_feasible(sc, node, shared, turn=q.turn))
            # P(assignable AND NOT shared) == 0
            assert p_of(sc, And((node, Not(shared))), q.turn) == 0


@given(decks(min_size=8, max_size=12), st.integers(0, 2))
def test_p9_zero_mulligans_equals_plain(deck: Deck, turn: int) -> None:
    cond = Compare(tag("a"), ">=", 1)
    cfg = MulliganConfig((PriorityGroup(tag("b")),), max_mulligans=0, draw_size=3)
    from mtgcalc import GameConfig

    game = GameConfig(hand_size=3)
    assume(3 + game.draws_through(turn) <= deck.size)
    with_m = p_of(Scenario(deck, game, cfg), cond, turn)
    assert with_m == p_of(Scenario(deck, game), cond, turn)


@st.composite
def small_two_var_problems(draw: st.DrawFn) -> OptimizeProblem:
    """Two-variable max_probability problems, monotone or not."""
    vs = (Variable("v", 0, draw(st.integers(1, 6))), Variable("w", 0, draw(st.integers(1, 6))))
    leaf = st.builds(
        Compare,
        st.sampled_from([tag("v"), tag("w")]),
        st.sampled_from([">=", ">", "<=", "=="]),
        st.integers(0, 2),
    )
    leaves = draw(st.lists(leaf, min_size=1, max_size=3))
    combos: list[Condition] = [And(tuple(leaves)), Or(tuple(leaves))] if len(leaves) > 1 else []
    cond: Condition = leaves[0] if not combos else draw(st.sampled_from(combos))
    return OptimizeProblem(
        deck_size=draw(st.integers(14, 20)),
        variables=vs,
        query=Query(cond, None, draw(st.integers(0, 2))),
        budget=draw(st.none() | st.integers(0, 12)),
    )


@settings(max_examples=40)
@given(small_two_var_problems())
def test_p16_pruned_search_equals_full_search(problem: OptimizeProblem) -> None:
    """Monotone pruning (full-cap slice) never loses the optimum (MATH §10.2)."""
    from dataclasses import replace

    pruned = optimize(problem)
    full = optimize(replace(problem, assume_monotone=False))
    assert pruned.probability == full.probability
