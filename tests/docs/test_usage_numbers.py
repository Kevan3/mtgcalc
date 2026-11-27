"""Every number quoted in docs/USAGE.md is recomputed here (keeps the guide honest)."""

from __future__ import annotations

from pathlib import Path

from mtgcalc_gui import forms
from mtgcalc_gui.forms import (
    CardType,
    DeckSetup,
    Goal,
    HowMany,
    MulliganSetup,
    PlaySetup,
    Requirement,
    Vary,
)
from mtgcalc_gui.help import EXAMPLES

USAGE = (Path(__file__).resolve().parents[2] / "docs" / "USAGE.md").read_text()
DECK = DeckSetup(60, (CardType("land", 24), CardType("removal", 6)))
GOAL = Goal.all_of(Requirement("at least", 3, "land", 3), Requirement("at least", 1, "removal", 3))
SC = forms.build_scenario(DECK, PlaySetup(), MulliganSetup())


def test_tour_example_matches_the_guide() -> None:
    ex = EXAMPLES["60-card deck: lands and removal by turn 3"]
    sc = forms.build_scenario(ex.deck, ex.play, ex.mulligan)
    headline = forms.chances(sc, ex.goal).headline
    assert headline in USAGE  # the exact sentence a newcomer sees


def test_chances_and_only_if() -> None:
    only = Goal.all_of(Requirement("at least", 2, "land", 0))
    view = forms.chances(SC, GOAL, only)
    assert "53.9% of the time" in view.headline and "53.9% of the time" in USAGE
    assert view.details[0] in USAGE


def test_draws_table() -> None:
    kids = forms.draws(SC, "land", 3).rows[3].children
    for k in (2, 3, 4):
        assert (
            f"| {k} land | {kids[k].values[1]} | {kids[k].values[2]} | {kids[k].values[3]} |"
            in USAGE
        )


def test_turn_by_turn_table() -> None:
    rows = forms.turn_by_turn(SC, Goal.all_of(Requirement("at least", 4, "land", 0)), 6).rows
    for i, label in ((0, "Opening hand"), (3, "Turn 3"), (6, "Turn 6")):
        assert f"| {label} | {rows[i].values[1]} | {rows[i].values[2]} |" in USAGE


def test_mulligan_numbers() -> None:
    sc = forms.build_scenario(
        DECK, PlaySetup(), MulliganSetup(enabled=True, protect=(("land", 3), ("removal", 1)))
    )
    view = forms.mulligan_advice(sc, GOAL)
    assert view.headline in USAGE
    rule = view.rows[1].children[0].values[0]
    assert rule in USAGE


def test_how_many_numbers() -> None:
    need = forms.how_many(DECK, SC, HowMany())
    assert need.headline in USAGE and need.details[0] in USAGE
    split = forms.how_many(
        DECK,
        SC,
        HowMany("share", "best", (Vary("land", 14, 24), Vary("removal", 0, 8)), 0, 30, GOAL),
    )
    assert split.headline.split(".")[0] + "." in USAGE
