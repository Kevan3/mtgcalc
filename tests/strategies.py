"""Hypothesis strategies for small random scenarios and conditions (TP §6)."""

from __future__ import annotations

from hypothesis import strategies as st

from mtgcalc.model.conditions import (
    And,
    Assignable,
    At,
    AtLeast,
    Between,
    Compare,
    Condition,
    Const,
    Demand,
    Exactly,
    Implies,
    Not,
    Or,
    Query,
    Xor,
)
from mtgcalc.model.deck import Card, Deck
from mtgcalc.model.game import GameConfig
from mtgcalc.model.mulligan import MulliganConfig, PriorityGroup
from mtgcalc.model.scenario import Scenario
from mtgcalc.model.selectors import AllOf, AnyOf, CardName, Everything, NoneOf, Selector, Tag

TAGS = ("a", "b", "c")
OPS = ("==", "!=", "<", "<=", ">", ">=")


@st.composite
def decks(draw: st.DrawFn, min_size: int = 2, max_size: int = 10) -> Deck:
    """1-4 card types with random overlapping tags."""
    n_types = draw(st.integers(1, 4))
    cards = []
    for i in range(n_types):
        tags = draw(st.frozensets(st.sampled_from(TAGS), max_size=3))
        cards.append(Card(f"card{i}", draw(st.integers(1, 4)), tags))
    deck = Deck(tuple(cards))
    if not min_size <= deck.size <= max_size:
        from hypothesis import reject

        reject()
    return deck


def selectors(deck: Deck) -> st.SearchStrategy[Selector]:
    base = st.sampled_from([Tag(t) for t in TAGS] + [CardName(c.name) for c in deck.library])
    return st.one_of(
        base,
        base,
        st.lists(base, min_size=1, max_size=2).map(lambda xs: AnyOf(tuple(xs))),
        st.lists(base, min_size=1, max_size=2).map(lambda xs: AllOf(tuple(xs))),
        st.lists(base, min_size=1, max_size=2).map(lambda xs: NoneOf(tuple(xs))),
        st.just(Everything()),
    )


def conditions(deck: Deck, max_turn: int, allow_at: bool = True) -> st.SearchStrategy[Condition]:
    sels = selectors(deck)
    leaves = st.one_of(
        st.builds(Compare, sels, st.sampled_from(OPS), st.integers(0, 4)),
        st.builds(
            lambda s, lo, w: Between(s, lo, lo + w), sels, st.integers(0, 3), st.integers(0, 2)
        ),
        st.lists(st.builds(Demand, sels, st.integers(1, 2)), min_size=1, max_size=3).map(
            lambda ds: Assignable(tuple(ds))
        ),
        st.builds(Const, st.booleans()),
    )

    def extend(children: st.SearchStrategy[Condition]) -> st.SearchStrategy[Condition]:
        many = st.lists(children, min_size=2, max_size=3).map(tuple)
        options = [
            many.map(And),
            many.map(Or),
            st.builds(Xor, children, children),
            st.builds(Not, children),
            st.builds(Implies, children, children),
            st.builds(AtLeast, st.integers(0, 3), many),
            st.builds(Exactly, st.integers(0, 3), many),
        ]
        if allow_at:
            options.append(st.builds(At, st.integers(0, max_turn), children))
        return st.one_of(*options)

    return st.recursive(leaves, extend, max_leaves=5)


@st.composite
def games(draw: st.DrawFn, max_hand: int = 4) -> GameConfig:
    extra = draw(st.dictionaries(st.integers(1, 3), st.integers(0, 1), max_size=1))
    return GameConfig(
        hand_size=draw(st.integers(1, max_hand)),
        on_play=draw(st.booleans()),
        draws_per_turn=draw(st.integers(0, 2)),
        extra_draws=extra,
    )


def _total_seen(hand: int, game: GameConfig, query: Query) -> int:
    from tests.oracle.bruteforce import turns_used

    turns = turns_used(query.condition, query.turn)
    if query.given is not None:
        turns |= turns_used(query.given, query.turn)
    return hand + max(game.draws_through(t) for t in turns)


@st.composite
def plain_cases(draw: st.DrawFn, max_seen: int = 7) -> tuple[Scenario, Query]:
    """Scenario without mulligans plus a (possibly conditional) query."""
    deck = draw(decks())
    game = draw(games())
    max_turn = 3
    cond = draw(conditions(deck, max_turn))
    given = draw(st.none() | conditions(deck, max_turn))
    q = Query(cond, given, draw(st.integers(0, max_turn)))
    seen = _total_seen(game.hand_size, game, q)
    from hypothesis import assume

    assume(seen <= min(max_seen, deck.size))
    return Scenario(deck, game), q


@st.composite
def mulligan_cases(draw: st.DrawFn, max_seen: int = 6) -> tuple[Scenario, Query]:
    """Scenario with a London mulligan configuration plus a query."""
    deck = draw(decks(min_size=3, max_size=9))
    game = draw(games())
    draw_size = draw(st.integers(1, 4))
    max_m = draw(st.integers(0, 2))
    free = draw(st.integers(0, 1))
    from hypothesis import assume

    assume(max(0, max_m - free) <= draw_size)
    sels = selectors(deck)
    groups = draw(
        st.lists(
            st.builds(PriorityGroup, sels, st.none() | st.integers(0, 3)),
            min_size=1,
            max_size=3,
            unique_by=lambda g: g.selector,
        )
    )
    keep = draw(conditions(deck, 0, allow_at=False))
    cfg = MulliganConfig(tuple(groups), keep, max_m, free, draw_size)
    cond = draw(conditions(deck, 2))
    given = draw(st.none() | conditions(deck, 2))
    q = Query(cond, given, draw(st.integers(0, 2)))
    assume(_total_seen(draw_size, game, q) <= min(max_seen, deck.size))
    return Scenario(deck, game, cfg), q


@st.composite
def multi_checkpoint_cases(draw: st.DrawFn, max_seen: int = 7) -> tuple[Scenario, Query]:
    """Boolean combinations of leaves bound to *different* turns, with draws between them.

    Targets early resolution and atom retirement: states decided true or false at an
    early checkpoint must be weighted by every later batch denominator (MATH §5.3).
    """
    deck = draw(decks(min_size=4))
    game = GameConfig(
        hand_size=draw(st.integers(1, 3)),
        on_play=draw(st.booleans()),
        draws_per_turn=draw(st.integers(1, 2)),
    )
    sels = selectors(deck)
    leaf = st.builds(Compare, sels, st.sampled_from(OPS), st.integers(0, 3))
    turns = draw(st.lists(st.integers(0, 3), min_size=2, max_size=3, unique=True))
    bound = [At(t, draw(leaf)) for t in turns]
    combine = draw(st.sampled_from(["and", "or", "xor", "implies", "atleast", "not-or"]))
    cond: Condition
    if combine == "and":
        cond = And(tuple(bound))
    elif combine == "or":
        cond = Or(tuple(bound))
    elif combine == "xor":
        cond = Xor(bound[0], bound[1])
    elif combine == "implies":
        cond = Implies(bound[0], bound[1])
    elif combine == "atleast":
        cond = AtLeast(draw(st.integers(1, len(bound))), tuple(bound))
    else:
        cond = Not(Or(tuple(bound)))
    q = Query(cond, None, 0)
    from hypothesis import assume

    assume(_total_seen(game.hand_size, game, q) <= min(max_seen, deck.size))
    return Scenario(deck, game), q
