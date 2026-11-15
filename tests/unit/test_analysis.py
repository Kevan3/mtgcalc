"""Unit tests: stats, mulligan analysis, optimizer (LLD §6)."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from math import comb

import pytest

from mtgcalc import (
    Category,
    Deck,
    GameConfig,
    MulliganConfig,
    OptimizeProblem,
    PriorityGroup,
    Query,
    Scenario,
    Variable,
    count,
    distribution,
    mulligan_report,
    optimal_keep,
    optimize,
    parse_condition,
    probability,
    tag,
    threshold_table,
    turn_table,
)
from mtgcalc.analysis.mulligan import run_mulligan
from mtgcalc.analysis.optimizer import is_monotone
from mtgcalc.analysis.prepare import prepare
from mtgcalc.errors import InfeasibleError, ValidationError
from mtgcalc.model.results import Probability

LANDS = Deck.from_counts(60, {"land": 24, "key": 4})


def _p(x: object) -> Fraction:
    assert isinstance(x, Probability) and x.exact is not None
    return x.exact


# --- stats ------------------------------------------------------------------------------
def test_threshold_table_consistency() -> None:
    table = threshold_table(Scenario(LANDS), tag("land"), [0, 3], ks=range(0, 5))
    assert len(table.rows) == 10
    for r in table.rows:
        assert r.at_least + r.at_most - r.exactly == 1


def test_threshold_table_default_ks() -> None:
    table = threshold_table(Scenario(LANDS), tag("key"), [0])
    assert [r.k for r in table.rows] == [0, 1, 2, 3, 4]


def test_distribution_helpers() -> None:
    d = distribution(Scenario(LANDS), tag("key"), 0)
    assert d.none() == Fraction(comb(56, 7), comb(60, 7))
    assert d.at_least(1) == 1 - d.none()
    assert d.cdf()[-1] == 1 and d.sf()[0] == 1
    assert d.exactly(99) == 0 and d.exactly(-1) == 0


def test_turn_table_matches_individual_queries() -> None:
    tt = turn_table(Scenario(LANDS), "land >= 3", [1, 2, 3, 4])
    for row in tt.rows:
        single = _p(
            probability(Scenario(LANDS), Query(parse_condition("land >= 3"), turn=row.turn))
        )
        assert row.probability == single
        assert row.cards_seen == 7 + GameConfig().draws_through(row.turn)


# --- mulligans --------------------------------------------------------------------------
MULL = MulliganConfig(
    (PriorityGroup(tag("land")), PriorityGroup(tag("key"))),
    keep_rule=count("land").between(2, 5),
    max_mulligans=2,
)


def test_mulligan_rows_are_consistent() -> None:
    rep = mulligan_report(Scenario(LANDS, mulligan=MULL), "land >= 3 @T3 AND key >= 1 @T3")
    assert [r.hand_size for r in rep.rows] == [7, 6, 5]
    assert rep.rows[0].p_reach == 1
    assert rep.rows[-1].p_keep_given_reach == 1
    for a, b in zip(rep.rows, rep.rows[1:], strict=False):
        assert b.p_reach == a.p_reach * (1 - a.p_keep_given_reach)
    total = sum(r.p_reach * r.p_success_and_keep_given_reach for r in rep.rows)
    assert rep.p_success == total
    assert 0 <= rep.expected_mulligans <= 2
    assert 5 <= rep.expected_hand_size <= 7


def test_mulligan_depth_zero_equals_no_mulligan() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("land")),), max_mulligans=0)
    cond = parse_condition("land >= 3 @T3 AND key >= 1 @T2")
    with_m = probability(Scenario(LANDS, mulligan=cfg), cond)
    without = probability(Scenario(LANDS), cond)
    assert _p(with_m) == _p(without)


def test_free_mulligan_keeps_seven() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("key")),), count("key") >= 1, 1, free_mulligans=1)
    rep = mulligan_report(Scenario(LANDS, mulligan=cfg), "key >= 1")
    assert [r.hand_size for r in rep.rows] == [7, 7]
    p = 1 - Fraction(comb(56, 7), comb(60, 7))
    assert rep.p_success == 1 - (1 - p) ** 2


def test_forced_success_matches_bottomed_hand() -> None:
    """At depth 1 with keep-anything, forced success equals 6-card-kept probability
    for a single-card condition protected by the policy."""
    cfg = MulliganConfig((PriorityGroup(tag("key")),), max_mulligans=1)
    rep = mulligan_report(Scenario(LANDS, mulligan=cfg), "key >= 1")
    p7 = 1 - Fraction(comb(56, 7), comb(60, 7))
    assert rep.rows[1].p_success_forced == p7


def test_optimal_keep_dominates_keep_rule() -> None:
    sc = Scenario(LANDS, mulligan=MULL)
    success = "land >= 3 @T3 AND key >= 1 @T3"
    best = optimal_keep(sc, success)
    rule = mulligan_report(sc, success)
    assert best.value >= rule.p_success
    assert best.rows[-1].p_keep_given_reach == 1
    for row in best.rows:
        assert sum(h.probability for h in row.hands) == 1
        for h in row.hands:
            if row.depth < len(best.rows) - 1:
                assert h.keep == (h.success >= row.continuation_value)


def test_run_mulligan_requires_mulligan() -> None:
    with pytest.raises(ValidationError):
        run_mulligan(prepare(Scenario(LANDS), {"x": count("land") >= 1}))
    with pytest.raises(ValidationError):
        optimal_keep(Scenario(LANDS), "land >= 1")


def test_mulligan_rejects_draws_into_bottom() -> None:
    small = Deck.from_counts(9, {"a": 3})
    cfg = MulliganConfig((PriorityGroup(tag("a")),), max_mulligans=1)
    with pytest.raises(ValidationError):
        probability(Scenario(small, mulligan=cfg), "a >= 1 @T4")


def test_distribution_under_mulligan_sums_to_one() -> None:
    d = distribution(Scenario(LANDS, mulligan=MULL), tag("land"), 2)
    assert sum(d.pmf) == 1
    assert d.at_least(2) > distribution(Scenario(LANDS), tag("land"), 2).at_least(2)


# --- optimizer --------------------------------------------------------------------------
def _problem(**kw: object) -> OptimizeProblem:
    base: dict[str, object] = {
        "deck_size": 60,
        "variables": (Variable("land", 14, 40),),
        "query": Query(parse_condition("land >= 3"), turn=3),
        "objective": "min_count",
        "target": Fraction(9, 10),
    }
    base.update(kw)
    return OptimizeProblem(**base)  # type: ignore[arg-type]


def test_min_count_bisection_is_proven_and_minimal() -> None:
    res = optimize(_problem())
    ((name, c),) = res.counts
    assert name == "land" and res.proven_optimal and res.probability >= Fraction(9, 10)
    below = optimize(_problem(variables=(Variable("land", 14, c - 1),), target=Fraction(0)))
    assert below.counts[0][1] == 14  # sanity: zero target picks the lower bound
    p_prev = _p(probability(Scenario(Deck.from_counts(60, {"land": c - 1})), "land >= 3 @T3"))
    assert p_prev < Fraction(9, 10)


def test_min_count_linear_scan_when_not_monotone() -> None:
    q = Query(parse_condition("land in 3..4"), turn=3)
    p = _problem(query=q, target=Fraction(1, 2))
    assert not is_monotone(p, p.variables[0])
    res = optimize(p)
    assert res.proven_optimal and res.probability >= Fraction(1, 2)


def test_min_count_infeasible() -> None:
    with pytest.raises(InfeasibleError):
        optimize(_problem(target=Fraction(1)))
    q = Query(parse_condition("land in 3..4"), turn=3)
    with pytest.raises(InfeasibleError):
        optimize(_problem(query=q, target=Fraction(99, 100)))


def test_max_probability_exhaustive() -> None:
    p = OptimizeProblem(
        deck_size=40,
        variables=(Variable("land", 15, 18), Variable("ramp", 0, 4)),
        query=Query(parse_condition("land >= 3 AND ramp >= 1"), turn=2),
        budget=20,
    )
    res = optimize(p)
    assert res.proven_optimal
    counts = dict(res.counts)
    assert counts["land"] + counts["ramp"] == 20  # monotone: the best uses the whole cap
    assert res.evaluations == 3  # only the sum == 20 slice: (16,4), (17,3), (18,2)
    assert res.frontier[0][1] == res.probability
    full = optimize(replace(p, assume_monotone=False))  # no pruning: whole grid
    assert full.evaluations == len([1 for a in range(15, 19) for b in range(5) if a + b <= 20])
    assert full.probability == res.probability and full.counts == res.counts


def test_max_probability_local_search_agrees_with_exhaustive() -> None:
    kw = {
        "deck_size": 40,
        "variables": (Variable("land", 14, 18), Variable("ramp", 0, 4)),
        "query": Query(parse_condition("land >= 3 AND ramp >= 1"), turn=2),
        "budget": 20,
    }
    exhaustive = optimize(OptimizeProblem(**kw))  # type: ignore[arg-type]
    heuristic = optimize(OptimizeProblem(**kw, exhaustive_limit=1))  # type: ignore[arg-type]
    assert not heuristic.proven_optimal
    assert heuristic.probability == exhaustive.probability


def test_min_total() -> None:
    p = OptimizeProblem(
        deck_size=40,
        variables=(Variable("land", 10, 20), Variable("ramp", 0, 4)),
        query=Query(parse_condition("land >= 2 AND ramp >= 1"), turn=2),
        objective="min_total",
        target=Fraction(1, 2),
    )
    res = optimize(p)
    assert res.probability >= Fraction(1, 2) and res.proven_optimal
    total = sum(c for _, c in res.counts)
    # nothing with a smaller total meets the target
    smaller = OptimizeProblem(
        deck_size=40,
        variables=p.variables,
        query=p.query,
        budget=total - 1,
    )
    assert optimize(smaller).probability < Fraction(1, 2)


def test_fixed_categories_and_tags() -> None:
    p = OptimizeProblem(
        deck_size=60,
        variables=(Variable("basic", 10, 36, frozenset({"land"})),),
        fixed=(("mdfc", Category(4, frozenset({"land"}))),),
        query=Query(parse_condition("land >= 3"), turn=3),
        objective="min_count",
        target=Fraction(9, 10),
    )
    with_mdfc = dict(optimize(p).counts)["basic"]
    without = dict(optimize(_problem()).counts)["land"]
    assert with_mdfc == without - 4


@pytest.mark.parametrize(
    ("text", "monotone"),
    [
        ("land >= 3", True),
        ("land > 2 AND (land >= 4 OR key >= 1)", True),
        ("NOT (land < 3)", False),  # '<' read under negation: syntactic test is conservative
        ("land <= 5", False),
        ("land == 3", False),
        ("land >= 3 XOR key >= 1", False),
        ("key >= 1 XOR key >= 2", True),
        ("atleast(1, land >= 3, key >= 1)", True),
        ('tag:"(other)" >= 1', False),
        ("assign(land >= 2, key >= 1)", True),
        ("NOT assign(land >= 2)", False),
        ("true AND land >= 1", True),
    ],
)
def test_monotonicity_classifier(text: str, monotone: bool) -> None:
    p = _problem(query=Query(parse_condition(text)))
    assert is_monotone(p, p.variables[0]) is monotone


def test_monotone_override_and_mulligan() -> None:
    p = _problem(assume_monotone=False)
    assert not is_monotone(p, p.variables[0])
    cfg = MulliganConfig((PriorityGroup(tag("land")),))
    assert not is_monotone(_problem(mulligan=cfg), _problem().variables[0])


@pytest.mark.parametrize(
    "kw",
    [
        {"variables": ()},
        {"objective": "min_count", "target": None},
        {"variables": (Variable("a", 0, 1), Variable("b", 0, 1))},
        {"variables": (Variable("a", 0, 1), Variable("a", 0, 1)), "objective": "max_probability"},
        {"query": Query(parse_condition("land >= 1"), parse_condition("land >= 0"))},
    ],
)
def test_problem_validation(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _problem(**kw)
    with pytest.raises(ValidationError):
        Variable("x", 3, 1)


def test_lower_bounds_exceed_space() -> None:
    with pytest.raises(InfeasibleError):
        optimize(_problem(variables=(Variable("land", 61, 70),)))


@pytest.mark.parametrize("percent", [10, 30, 50, 70, 85, 90, 95, 99])
def test_bisection_equals_linear_scan(percent: int) -> None:
    """Binary search must return exactly the smallest count meeting the target (FR-50)."""
    target = Fraction(percent, 100)
    p = _problem(variables=(Variable("land", 0, 40),), target=target)
    bisect = optimize(p)
    scan = optimize(
        _problem(variables=(Variable("land", 0, 40),), target=target, assume_monotone=False)
    )
    assert bisect.counts == scan.counts


def test_points_and_count_points_match_brute_force() -> None:
    from itertools import product

    from mtgcalc.analysis.optimizer import _points, count_points

    vs = (Variable("a", 1, 4), Variable("b", 0, 3), Variable("c", 2, 5))
    for cap in range(0, 14):
        for total in (None, *range(0, 14)):
            brute = [
                pt
                for pt in product(range(1, 5), range(0, 4), range(2, 6))
                if sum(pt) <= cap and (total is None or sum(pt) == total)
            ]
            assert list(_points(vs, cap, total)) == brute
            assert count_points(vs, cap, total) == len(brute)


def test_min_total_binary_search_matches_linear() -> None:
    p = OptimizeProblem(
        deck_size=40,
        variables=(Variable("land", 10, 20), Variable("ramp", 0, 6)),
        query=Query(parse_condition("land >= 2 AND ramp >= 1"), turn=2),
        objective="min_total",
        target=Fraction(1, 2),
    )
    fast, slow = optimize(p), optimize(replace(p, assume_monotone=False))
    assert fast.counts == slow.counts and fast.proven_optimal
    assert fast.evaluations < slow.evaluations


def test_parallel_evaluation_matches_serial() -> None:
    p = OptimizeProblem(
        deck_size=40,
        variables=(Variable("land", 14, 18), Variable("ramp", 0, 4)),
        query=Query(parse_condition("land >= 3 OR ramp >= 2"), turn=2),
        assume_monotone=False,
    )
    assert optimize(replace(p, workers=4)) == optimize(replace(p, workers=1))


def test_monotone_implication() -> None:
    q = Query(parse_condition("key >= 1 -> land >= 3"))  # land only in the consequent
    p = _problem(query=q)
    assert is_monotone(p, p.variables[0])
    q2 = Query(parse_condition("land >= 3 -> key >= 1"))  # land in the antecedent
    assert not is_monotone(_problem(query=q2), p.variables[0])


def test_budget_and_workers_validation() -> None:
    with pytest.raises(ValidationError):
        _problem(budget=-1)
    with pytest.raises(ValidationError):
        _problem(workers=0)
