"""Metamorphic relations M1-M8 (TP §8)."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import assume, given
from hypothesis import strategies as st

from mtgcalc import (
    And,
    Card,
    Compare,
    Deck,
    GameConfig,
    MulliganConfig,
    PriorityGroup,
    Query,
    Scenario,
    count,
    distribution,
    hypergeom,
    mulligan_report,
    tag,
)
from mtgcalc.api import probability
from mtgcalc.model.conditions import At, Condition
from mtgcalc.model.results import Probability
from mtgcalc.model.selectors import Selector
from tests.strategies import plain_cases


def p_of(sc: Scenario, cond: Condition, turn: int = 0) -> Fraction:
    res = probability(sc, Query(cond, None, turn))
    assert isinstance(res, Probability) and res.exact is not None
    return res.exact


@given(st.integers(10, 60), st.data())
def test_m1_draw_at_t_equals_play_at_t_plus_1(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    t = data.draw(st.integers(0, 3))
    k = data.draw(st.integers(0, 4))
    deck = Deck.from_counts(N, {"x": K})
    cond = Compare(tag("x"), ">=", k)
    assume(7 + t + 1 <= N)
    on_draw = p_of(Scenario(deck, GameConfig(on_play=False)), cond, t)
    on_play = p_of(Scenario(deck, GameConfig(on_play=True)), cond, t + 1)
    assert on_draw == on_play


@given(plain_cases(), st.randoms(use_true_random=False))
def test_m2_relabel_and_reorder(case: tuple[Scenario, Query], rnd) -> None:  # type: ignore[no-untyped-def]
    sc, q = case
    rename = {"a": "zeta", "b": "alpha", "c": "mid"}
    cards = [Card(c.name, c.quantity, frozenset(rename[t] for t in c.tags)) for c in sc.deck.cards]
    rnd.shuffle(cards)

    def relabel(x: object) -> object:
        from dataclasses import fields, is_dataclass, replace

        from mtgcalc.model.selectors import Tag

        if isinstance(x, Tag):
            return Tag(rename[x.name])
        if isinstance(x, tuple):
            return tuple(relabel(i) for i in x)
        if is_dataclass(x) and not isinstance(x, type):
            return replace(x, **{f.name: relabel(getattr(x, f.name)) for f in fields(x)})
        return x

    q2 = relabel(q)
    assert isinstance(q2, Query)
    sc2 = Scenario(Deck(tuple(cards)), sc.game)
    assert probability(sc2, q2) == probability(sc, q)


@given(plain_cases())
def test_m3_split_card_into_identical_copies(case: tuple[Scenario, Query]) -> None:
    sc, q = case
    big = max(sc.deck.cards, key=lambda c: c.quantity)
    assume(big.quantity >= 2)
    from mtgcalc.model.conditions import walk
    from mtgcalc.model.selectors import CardName, card_names_in

    names = {n for node in walk(q.condition) for s in _sels(node) for n in card_names_in(s)}
    if q.given is not None:
        names |= {n for node in walk(q.given) for s in _sels(node) for n in card_names_in(s)}
    assume(big.name not in names)
    split = [c for c in sc.deck.cards if c is not big] + [
        Card(big.name, 1, big.tags),
        Card(big.name + " (alt)", big.quantity - 1, big.tags),
    ]
    _ = CardName  # names are not referenced, so the split is invisible to the query
    assert probability(Scenario(Deck(tuple(split)), sc.game), q) == probability(sc, q)


def _sels(node: object) -> tuple[Selector, ...]:
    from mtgcalc.model.conditions import Assignable, Between, Compare

    if isinstance(node, Compare | Between):
        return (node.sel,)
    if isinstance(node, Assignable):
        return tuple(d.sel for d in node.demands)
    return ()


@given(st.integers(0, 10), st.integers(1, 10))
def test_m4_unreferenced_cards_aggregate_into_pool(c: int, extra: int) -> None:
    cond = (count("land") >= 2).at(2) & (count("key") >= 1)
    a = Deck.from_counts(40, {"land": 17, "key": 3, "junk": c})
    b = Deck.from_counts(40, {"land": 17, "key": 3})
    assert p_of(Scenario(a), cond) == p_of(Scenario(b), cond)


@given(st.integers(10, 50), st.data())
def test_m5_complement(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    k = data.draw(st.integers(0, 7))
    deck = Deck.from_counts(N, {"x": K})
    from mtgcalc import none_of

    sc = Scenario(deck)
    assert p_of(sc, Compare(tag("x"), ">=", k)) == p_of(sc, Compare(none_of("x"), "<=", 7 - k))


@given(st.integers(1, 40), st.data())
def test_m6_hypergeometric_symmetry(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    n = data.draw(st.integers(0, N))
    a, b = hypergeom(N, K, n).pmf, hypergeom(N, n, K).pmf
    assert a == b


@given(st.integers(15, 60), st.data())
def test_m7_monotone_implication_collapse_on_the_draw(N: int, data: st.DataObject) -> None:
    K = data.draw(st.integers(0, N))
    deck = Deck.from_counts(N, {"land": K})
    turns = data.draw(st.integers(1, 4))
    chain = And(tuple(At(t, Compare(tag("land"), ">=", t + 1)) for t in range(turns + 1)))
    sc = Scenario(deck, GameConfig(hand_size=7, on_play=False))
    last = distribution(sc, tag("land"), turns).at_least(turns + 1)
    assert p_of(sc, chain) == last


@given(st.integers(1, 8), st.integers(0, 3))
def test_m8_free_mulligan_never_hurts_single_card_search(copies: int, max_m: int) -> None:
    deck = Deck.from_counts(60, {"x": copies})
    rule = count("x") >= 1
    base = MulliganConfig((PriorityGroup(tag("x")),), rule, max_m + 1, free_mulligans=0)
    free = MulliganConfig((PriorityGroup(tag("x")),), rule, max_m + 1, free_mulligans=1)
    p0 = mulligan_report(Scenario(deck, mulligan=base), rule).p_success
    p1 = mulligan_report(Scenario(deck, mulligan=free), rule).p_success
    assert p1 >= p0
    p = 1 - hypergeom(60, copies, 7).pmf[0]
    assert p0 == p1 == 1 - (1 - p) ** (max_m + 2)  # MATH §9.3 closed form
