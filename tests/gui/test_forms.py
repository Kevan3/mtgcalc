"""Unit tests: plain-language GUI logic (headless; no Tk required)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from mtgcalc import Deck, Query, Scenario, probability
from mtgcalc.errors import MtgCalcError, ParseError, ValidationError
from mtgcalc.model.results import Probability
from mtgcalc_gui import forms
from mtgcalc_gui.forms import (
    ANY_CARD,
    CardType,
    DeckSetup,
    Goal,
    HowMany,
    MulliganSetup,
    PlaySetup,
    Requirement,
    Settings,
    Vary,
)

DECK = DeckSetup(60, (CardType("land", 24), CardType("removal", 6)))
GOAL = Goal((Requirement("at least", 3, "land", 3), Requirement("at least", 1, "removal", 3)))


def scenario(**mull: object) -> Scenario:
    return forms.build_scenario(DECK, PlaySetup(), MulliganSetup(**mull))  # type: ignore[arg-type]


# --- wording helpers --------------------------------------------------------------------
def test_pct_and_in_words() -> None:
    assert forms.pct(Fraction(1, 4)) == "25.0%"
    assert forms.pct(Fraction(1, 3), Settings(fractions=True)) == "33.3% (= 1/3)"
    assert forms.pct(Fraction(1, 2000)) == "0.050%"
    assert forms.pct(Fraction(1, 10**7)) == "less than 0.001%"
    assert forms.pct(1) == "100.0%"
    assert forms.in_words(0.999) == "almost every game"
    assert forms.in_words(0.001) == "almost never"
    assert forms.in_words(0.54) == "about 5 games in 10"
    assert forms.in_words(0.04) == "about 1 game in 25"
    assert forms.turn_words(0) == "in your opening hand"
    assert forms.turn_words(3) == "by turn 3"


# --- steps 1 and 2 ----------------------------------------------------------------------
def test_build_deck_from_types_with_overlaps() -> None:
    deck = forms.build_deck(
        DeckSetup(99, (CardType("Land", 35), CardType("mdfc", 2, ("land", "removal"))))
    )
    assert deck.size == 99
    assert deck.tag_counts()["land"] == 37 and deck.tag_counts()["removal"] == 2


@pytest.mark.parametrize(
    "deck",
    [
        DeckSetup(0, ()),
        DeckSetup(10, (CardType("land", 11),)),
        DeckSetup(60, (CardType("land", 1), CardType("LAND", 2))),
        DeckSetup(60, (CardType("  ", 1),)),
        DeckSetup(60, (CardType("land", -1),)),
        DeckSetup(mode="decklist", decklist="  "),
    ],
)
def test_build_deck_errors_are_friendly(deck: DeckSetup) -> None:
    with pytest.raises(ValidationError):
        forms.build_deck(deck)


def test_type_names() -> None:
    names = forms.type_names(
        DeckSetup(60, (CardType("Land", 24), CardType("mdfc", 2, ("land", "ramp"))))
    )
    assert names == ["land", "mdfc", "ramp", ANY_CARD]
    listed = forms.type_names(DeckSetup(mode="decklist", decklist="4 Bolt #removal\n56 Mountain"))
    assert listed == ["removal", ANY_CARD]
    assert forms.type_names(DeckSetup(mode="decklist", decklist="nonsense")) == [ANY_CARD]


def test_build_scenario_play_and_mulligans() -> None:
    sc = forms.build_scenario(DECK, PlaySetup(False, 1, ((3, 2), (3, 1))), MulliganSetup())
    assert sc.game.draws_through(3) == 3 + 3 and sc.mulligan is None
    sc = scenario(enabled=True, keep_type="", protect=(("land", 3),), free_first=True)
    assert sc.mulligan is not None and sc.mulligan.free_mulligans == 1
    assert "Mulligans allowed" in forms.describe_scenario(sc)
    assert "30 other cards" in forms.describe_scenario(sc)


@pytest.mark.parametrize(
    "mull",
    [
        {"enabled": True, "protect": ()},
        {"enabled": True, "keep_min": 5, "keep_max": 2},
        {"enabled": True, "protect": (("land", 3), ("land", 1))},
    ],
)
def test_mulligan_setup_errors(mull: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        scenario(**mull)


def test_extra_draws_must_be_after_turn_0() -> None:
    with pytest.raises(ValidationError):
        forms.build_scenario(DECK, PlaySetup(extra_draws=((0, 1),)), MulliganSetup())


# --- goals ------------------------------------------------------------------------------
def test_goal_translation_matches_the_rule_language() -> None:
    assert forms.goal_as_text(GOAL) == "land >= 3 @T3 AND removal >= 1 @T3"
    any_goal = Goal(
        (
            Requirement("none", 0, "land", 0),
            Requirement("exactly", 2, ANY_CARD, 1),
            Requirement("at most", 4, "land", 2),
        ),
        combine="any",
    )
    assert forms.goal_as_text(any_goal) == "land == 0 @T0 OR everything == 2 @T1 OR land <= 4 @T2"
    assert forms.goal_as_text(GOAL, with_turns=False) == "land >= 3 AND removal >= 1"
    assert forms.describe_goal(GOAL) == (
        "at least 3 land by turn 3 and at least 1 removal by turn 3"
    )
    assert forms.describe_goal(any_goal).startswith(
        "no land in your opening hand or exactly 2 cards by turn 1"
    )


def test_custom_rule_overrides_lines() -> None:
    goal = Goal(GOAL.requirements, custom="land >= 2 @T0")
    assert forms.goal_as_text(goal) == "land >= 2 @T0"
    assert forms.describe_goal(goal) == "your rule (land >= 2 @T0)"
    with pytest.raises(ParseError):
        forms.goal_condition(Goal(custom="land >="))
    with pytest.raises(ValidationError):
        forms.goal_condition(Goal(()))
    with pytest.raises(ValidationError):
        forms.goal_condition(Goal((Requirement(amount=-1),)))


def test_check_rule() -> None:
    assert forms.check_rule("LAND>=3") == "land >= 3"
    assert forms.check_rule("true") == "true"


# --- questions --------------------------------------------------------------------------
def test_chances_matches_the_engine() -> None:
    view = forms.chances(scenario(), GOAL)
    p = probability(
        forms.build_scenario(DECK, PlaySetup(), MulliganSetup()), Query(forms.goal_condition(GOAL))
    )
    assert isinstance(p, Probability)
    assert forms.pct(p.exact or 0) in view.headline
    assert "about 5 games in 10" in view.headline


def test_chances_conditional_and_impossible() -> None:
    only = Goal((Requirement("at least", 2, "land", 0),))
    assert (
        "In the games where you have at least 2 land"
        in forms.chances(scenario(), GOAL, only).headline
    )
    never = Goal((Requirement("at least", 7, "removal", 0),))
    assert forms.chances(scenario(), GOAL, never).headline.startswith("That never happens")


def test_chances_with_mulligans_and_simulation() -> None:
    view = forms.chances(scenario(enabled=True), GOAL)
    assert "mulligan" in view.details[0]
    sim = forms.chances(scenario(), GOAL, settings=Settings("montecarlo", 2000, 1))
    assert "simulated" in sim.headline


def test_draws_table() -> None:
    view = forms.draws(scenario(), "land", 2)
    assert len(view.rows) == 3 and view.rows[0].values[0].startswith("Opening hand")
    assert view.rows[2].children[3].values[0] == "3 land"
    assert view.headers[1] == "Exactly this many"
    assert "cards" in forms.draws(scenario(), ANY_CARD, 0).headline
    with pytest.raises(ValidationError):
        forms.draws(scenario(), "land", -1)


def test_turn_by_turn() -> None:
    view = forms.turn_by_turn(scenario(), GOAL, 4)
    assert [r.values[0] for r in view.rows] == [
        "Opening hand",
        "Turn 1",
        "Turn 2",
        "Turn 3",
        "Turn 4",
    ]
    assert view.rows[3].values[1] == "9"
    with pytest.raises(ValidationError):
        forms.turn_by_turn(scenario(), GOAL, -1)


def test_mulligan_advice() -> None:
    with pytest.raises(ValidationError):
        forms.mulligan_advice(scenario(), GOAL)
    view = forms.mulligan_advice(
        scenario(enabled=True, protect=(("land", 3), ("removal", 1))), GOAL
    )
    assert "Never mulliganing" in view.headline and "best possible plan" in view.headline
    yours, best = view.rows
    assert yours.values[0] == "Your plan" and len(yours.children) == 3
    assert best.values[0] == "Best possible plan"
    assert best.children[0].values[0].startswith("First 7 cards: keep if its chance")
    assert best.children[-1].values[0].endswith("keep any hand")
    assert all(h.values[0].endswith(("keep", "mulligan")) for h in best.children[0].children)


def test_how_many_need_split_fewest() -> None:
    sc = scenario()
    need = forms.how_many(DECK, sc, HowMany())
    assert need.headline.startswith("Play 33 land") and "With 32 land" in need.details[0]
    assert "guaranteed" in need.details[-1]
    split = forms.how_many(
        DECK,
        sc,
        HowMany("split", (Vary("land", 14, 24), Vary("removal", 0, 8)), slots=30, goal=GOAL),
    )
    assert split.headline.startswith("Best use of 30 cards: 22 land, 8 removal")
    fewest = forms.how_many(
        DECK,
        sc,
        HowMany(
            "fewest", (Vary("land", 14, 30), Vary("removal", 0, 12)), target_percent=50, goal=GOAL
        ),
    )
    assert fewest.headline.startswith("The fewest cards that reach 50.0%")


@pytest.mark.parametrize(
    "q",
    [
        HowMany(vary=()),
        HowMany(vary=(Vary("land", 1, 2), Vary("removal", 1, 2))),
        HowMany(vary=(Vary("ramp", 1, 2),)),
        HowMany(vary=(Vary("land", 5, 2),)),
        HowMany(target_percent=150),
        HowMany(vary=(Vary("land", 14, 20),)),  # target out of reach
    ],
)
def test_how_many_errors_are_friendly(q: HowMany) -> None:
    with pytest.raises(ValidationError):
        forms.how_many(DECK, scenario(), q)


def test_how_many_needs_card_types() -> None:
    listed = DeckSetup(mode="decklist", decklist="24 Forest #land\n36 Bear")
    sc = forms.build_scenario(listed, PlaySetup(), MulliganSetup())
    with pytest.raises(ValidationError):
        forms.how_many(listed, sc, HowMany())


def test_keep_rule_words() -> None:
    assert forms.keep_rule_words(MulliganSetup(keep_type="")) == "always keep your first hand"
    assert forms.keep_rule_words(MulliganSetup()) == "keep a hand with 2 to 5 land"
    assert forms.keep_rule_words(MulliganSetup(keep_type=ANY_CARD)).endswith("cards")


def test_every_error_is_a_library_error() -> None:
    assert issubclass(ValidationError, MtgCalcError)


# --- importing a deck link --------------------------------------------------------------
def _edge_deck() -> Deck:
    import json
    from pathlib import Path

    from mtgcalc_online.archidekt import to_deck

    path = Path(__file__).parents[1] / "online" / "fixtures" / "archidekt_edge.json"
    return to_deck(json.loads(path.read_text()))


def test_import_deck_gives_editable_text_and_a_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forms, "fetch_deck", lambda link: _edge_deck())
    result = forms.import_deck("https://archidekt.com/decks/42/edge-cases")
    assert result.summary.startswith("Imported 'Edge cases' from Archidekt: 38 cards in the deck")
    assert "commander Atraxa, Praetors' Voice" in result.summary
    assert "1 Sol Ring #mana-rock #ramp" in result.text
    deck = forms.build_deck(DeckSetup(mode="decklist", decklist=result.text))
    assert deck.size == 38 and "mana-rock" in forms.type_names(
        DeckSetup(mode="decklist", decklist=result.text)
    )


def test_import_deck_rejects_unsupported_links_without_fetching() -> None:
    from mtgcalc_online import DeckFetchError

    with pytest.raises(DeckFetchError, match="not a deck link"):
        forms.import_deck("my deck")
    with pytest.raises(DeckFetchError, match="Copy as plain text"):
        forms.import_deck("https://moxfield.com/decks/abc")
