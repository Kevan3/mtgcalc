"""Unit tests: domain model (LLD §3)."""

from __future__ import annotations

import pytest

from mtgcalc import (
    And,
    At,
    Card,
    Category,
    Compare,
    Const,
    Deck,
    GameConfig,
    MulliganConfig,
    Not,
    Or,
    PriorityGroup,
    Query,
    Scenario,
    Xor,
    all_of,
    any_of,
    card,
    count,
    everything,
    none_of,
    tag,
)
from mtgcalc.errors import ValidationError
from mtgcalc.model.conditions import (
    Assignable,
    AtLeast,
    Between,
    Demand,
    Exactly,
    Implies,
    selectors_in,
    turns_in,
)
from mtgcalc.model.deck import FILLER_NAME
from mtgcalc.model.scenario import preset_mulligan
from mtgcalc.model.selectors import matches

MDFC = Card("Shatterskull Smashing", 1, frozenset({"Land", "removal"}))
BOLT = Card("Lightning Bolt", 4, frozenset({"removal"}))


# --- selectors ------------------------------------------------------------------------
def test_tag_matching_is_case_insensitive() -> None:
    assert matches(tag("LAND"), MDFC)
    assert not matches(tag("land"), BOLT)


def test_card_name_matching_normalizes() -> None:
    assert matches(card("lightning   BOLT"), BOLT)
    assert not matches(card("Bolt"), BOLT)


def test_compound_selectors() -> None:
    assert matches(any_of("land", "ramp"), MDFC)
    assert matches(all_of("land", "removal"), MDFC)
    assert not matches(all_of("land", "removal"), BOLT)
    assert matches(none_of("land"), BOLT)
    assert not matches(none_of("land", "removal"), BOLT)
    assert matches(everything(), BOLT)


@pytest.mark.parametrize("bad", [lambda: tag("  "), lambda: card(""), any_of])
def test_selector_validation(bad) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        bad()


# --- conditions -----------------------------------------------------------------------
def test_dsl_builds_expected_ast() -> None:
    land = tag("land")
    assert (count(land) >= 3) == Compare(land, ">=", 3)
    assert (count(land) > 3) == Compare(land, ">", 3)
    assert (count(land) <= 3) == Compare(land, "<=", 3)
    assert (count(land) < 3) == Compare(land, "<", 3)
    assert count(land).eq(2) == Compare(land, "==", 2)
    assert count(land).ne(2) == Compare(land, "!=", 2)
    assert count("land").between(1, 2) == Between(land, 1, 2)
    a, b, c = (count(land) >= 1), (count(land) >= 2), (count(land) >= 3)
    assert a & b & c == And((a, b, c))  # flattened
    assert a | b | c == Or((a, b, c))
    assert a ^ b == Xor(a, b)
    assert ~a == Not(a)
    assert a.implies(b) == Implies(a, b)
    assert a.at(3) == At(3, a)


@pytest.mark.parametrize(
    "bad",
    [
        lambda: Compare(tag("x"), ">=", -1),
        lambda: Compare(tag("x"), "=>", 1),  # type: ignore[arg-type]
        lambda: Compare("x", ">=", 1),  # type: ignore[arg-type]
        lambda: Between(tag("x"), 3, 2),
        lambda: And((Const(True),)),
        lambda: Or(()),
        lambda: AtLeast(-1, (Const(True),)),
        lambda: Exactly(-1, (Const(True),)),
        lambda: AtLeast(1, ()),
        lambda: Demand(tag("x"), 0),
        lambda: Assignable(()),
        lambda: At(-1, Const(True)),
        lambda: Not(3),  # type: ignore[arg-type]
        lambda: Query(Const(True), turn=-1),
    ],
)
def test_condition_validation(bad) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        bad()


def test_selectors_and_turns_in() -> None:
    land, ramp = tag("land"), tag("ramp")
    cond = (count(land) >= 1).at(2) & Assignable((Demand(ramp, 1),)) & ~(count(land) >= 5)
    assert selectors_in(cond) == (land, ramp, land)
    assert turns_in(cond, 4) == frozenset({2, 4})


# --- deck -----------------------------------------------------------------------------
def test_from_counts_totals_and_filler() -> None:
    deck = Deck.from_counts(60, {"land": 24, "dfc": Category(2, frozenset({"land"}))})
    assert deck.size == 60
    assert deck.tag_counts() == {"(other)": 34, "dfc": 2, "land": 26}
    assert deck.card(FILLER_NAME).quantity == 34


def test_from_counts_zero_category_and_full_deck() -> None:
    deck = Deck.from_counts(4, {"a": 4, "b": 0})
    assert [c.name for c in deck.cards] == ["a"]


def test_from_counts_overflow() -> None:
    with pytest.raises(ValidationError) as e:
        Deck.from_counts(10, {"a": 11})
    assert e.value.field == "categories"


def test_deck_validation() -> None:
    with pytest.raises(ValidationError):
        Deck((Card("A"), Card("a")))
    with pytest.raises(ValidationError):
        Deck((Card("A", zone="commander"),))
    with pytest.raises(ValidationError):
        Card("A", 0)
    with pytest.raises(ValidationError):
        Card("", 1)
    with pytest.raises(ValidationError):
        Card("A", 1, zone="graveyard")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Card("A", 1, frozenset({" "}))
    with pytest.raises(ValidationError):
        Category(-1)


def test_zones_and_library() -> None:
    deck = Deck((Card("Cmdr", zone="commander"), Card("A", 3), Card("Side", zone="sideboard")))
    assert deck.size == 3
    assert [c.name for c in deck.library] == ["A"]


def test_tag_editing() -> None:
    deck = Deck((MDFC, BOLT))
    d2 = deck.with_tags("lightning bolt", add=["burn"], remove=["removal"])
    assert d2.card("Lightning Bolt").tags == frozenset({"burn"})
    assert deck.card("Lightning Bolt").tags == frozenset({"removal"})  # immutable
    d3 = deck.rename_tag("removal", "interaction")
    assert d3.tag_counts() == {"interaction": 5, "land": 1}
    with pytest.raises(ValidationError):
        deck.card("Nope")


# --- game -----------------------------------------------------------------------------
def test_draws_on_the_play_and_draw() -> None:
    play, draw = GameConfig(on_play=True), GameConfig(on_play=False)
    assert [play.draws_on_turn(t) for t in range(4)] == [0, 0, 1, 1]
    assert [draw.draws_on_turn(t) for t in range(4)] == [0, 1, 1, 1]
    assert play.draws_through(3) == 2 and draw.draws_through(3) == 3


def test_overrides_and_extras() -> None:
    g = GameConfig(draw_overrides={1: 1, 3: 0}, extra_draws={3: 2})
    assert [g.draws_on_turn(t) for t in range(1, 5)] == [1, 1, 2, 1]
    assert g.draw_overrides == ((1, 1), (3, 0))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hand_size": -1},
        {"draws_per_turn": -1},
        {"extra_draws": {0: 1}},
        {"extra_draws": {2: -1}},
        {"draw_overrides": ((2, 1), (2, 2))},
    ],
)
def test_game_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GameConfig(**kwargs)  # type: ignore[arg-type]


def test_negative_turn_rejected() -> None:
    with pytest.raises(ValidationError):
        GameConfig().draws_on_turn(-1)


# --- mulligan / scenario ----------------------------------------------------------------
def test_bottom_counts() -> None:
    cfg = MulliganConfig((PriorityGroup(tag("land")),), max_mulligans=3, free_mulligans=1)
    assert [cfg.bottom_count(m) for m in range(4)] == [0, 0, 1, 2]
    assert [cfg.hand_size(m) for m in range(4)] == [7, 7, 6, 5]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"priority": ()},
        {"priority": (PriorityGroup(tag("a")), PriorityGroup(tag("a")))},
        {"max_mulligans": -1},
        {"free_mulligans": 2},
        {"draw_size": 0},
        {"max_mulligans": 9},
        {"keep_rule": (count("a") >= 1).at(2)},
    ],
)
def test_mulligan_validation(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"priority": (PriorityGroup(tag("a")),)}
    base.update(kwargs)
    with pytest.raises(ValidationError):
        MulliganConfig(**base)  # type: ignore[arg-type]


def test_priority_group_validation() -> None:
    with pytest.raises(ValidationError):
        PriorityGroup(tag("a"), quota=-1)
    with pytest.raises(ValidationError):
        PriorityGroup("a")  # type: ignore[arg-type]


def test_presets_and_scenario() -> None:
    cfg = preset_mulligan("commander", (PriorityGroup(tag("land")),))
    assert cfg.free_mulligans == 1
    s = Scenario(Deck.from_counts(99, {"land": 37}))
    assert s.with_mulligan(cfg).mulligan == cfg
    assert s.mulligan is None
