"""Smoke tests for the Tk window (skipped when no display is available)."""

from __future__ import annotations

import gc
import time
from collections.abc import Iterator
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.gui


@pytest.fixture
def app() -> Iterator[Any]:
    from mtgcalc_gui.app import App

    try:
        window = App()
    except tk.TclError as e:  # no display
        pytest.skip(f"no display: {e}")
    window.withdraw()
    yield window
    window.destroy()
    gc.collect()  # free this window's Tk objects on the main thread (see App.run)


def wait(app: Any, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while app._busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    assert not app._busy, "calculation did not finish"


@pytest.mark.parametrize("example", range(4))
def test_every_question_answers_every_card_type_example(app: Any, example: int) -> None:
    from mtgcalc_gui.help import EXAMPLES

    app.load_example(list(EXAMPLES.values())[example])
    for page in app.question_pages():
        if type(page).__name__ == "MulliganPage" and not app.play_panel.mull_on.get():
            continue
        if type(page).__name__ == "HowManyPage":
            page.goal.set(page.goal.value())  # keep its own feasible default goal
        page.run()
        wait(app)
        status = app.status.get()
        if type(page).__name__ == "HowManyPage" and status.startswith("Can't answer"):
            assert "cannot be reached" in status  # a friendly, expected outcome
            continue
        assert status.startswith("Done"), (type(page).__name__, status)
        assert page.headline.cget("text")


@pytest.mark.parametrize("mode", ["one", "share"])
@pytest.mark.parametrize("aim", ["best", "target"])
def test_how_many_page_answers_each_mode_and_aim(app: Any, mode: str, aim: str) -> None:
    page = next(p for p in app.question_pages() if type(p).__name__ == "HowManyPage")
    page.mode.set(mode)
    page.aim.set(aim)
    page._mode_changed()
    assert bool(page.target_row.winfo_manager()) == (aim == "target")
    assert bool(page.slots_row.winfo_manager()) == (mode == "share")
    page.slots_box.delete(0, "end")
    page.slots_box.insert(0, "40")
    page.target_box.delete(0, "end")
    page.target_box.insert(0, "50")  # within reach of the default deck, so all four answer
    page.run()
    wait(app)
    status = app.status.get()
    assert status.startswith("Done"), (mode, aim, status)
    assert page.headline.cget("text")


def test_decklist_example_and_type_names(app: Any) -> None:
    from mtgcalc_gui.help import EXAMPLES

    app.load_example(EXAMPLES["Pasted decklist with #tags"])
    assert "ramp" in app.type_names()
    page = app.question_pages()[0]
    page.run()
    wait(app)
    assert app.status.get().startswith("Done")


def test_errors_are_shown_not_raised(app: Any) -> None:
    app.deck_panel.size_box.set("zero")
    app.question_pages()[0].run()
    assert app.status.get().startswith("Please check your deck")
    app.deck_panel.size_box.set("60")
    app.play_panel.mull_on.set(False)
    app.question_pages()[3].run()
    wait(app)
    assert app.status.get().startswith("Can't answer that yet")


def test_kinds_of_hand_to_keep(app: Any) -> None:
    from mtgcalc_gui.forms import KeepRule, keep_rule_words
    from mtgcalc_gui.help import EXAMPLES

    panel = app.play_panel
    app.load_example(EXAMPLES["Commander: ramp on turn 2"])
    _, mull = panel.value()
    assert mull.keep == (
        (KeepRule("land", 3, 5),),
        (KeepRule("land", 2, 2), KeepRule("ramp", 1, 7)),
    )
    keep = panel.keep
    keep.add()  # a third kind: 2 to 5 land by default
    keep.kinds[2][2].add(("draw", "1", "2"))  # "and also" 1 to 2 draw
    _, mull = panel.value()
    assert mull.keep[2] == (KeepRule("land", 2, 5), KeepRule("draw", 1, 2))
    assert [t.cget("text") for _, t, _ in keep.kinds][1:] == [
        "Or keep a hand with all of these:"
    ] * 2
    keep._remove(keep.kinds[0])
    assert keep.kinds[0][1].cget("text") == "Keep a hand with all of these:"
    while keep.kinds:
        keep._remove(keep.kinds[0])
    _, mull = panel.value()
    assert mull.keep == () and keep_rule_words(mull) == "always keep your first hand"
    assert keep.empty.winfo_manager() == "pack"  # "you keep every hand" is shown
    keep.add()
    assert keep.empty.winfo_manager() == ""
    keep.kinds[0][2].set([])  # a kind with no lines is explained, not raised
    panel.mull_on.set(True)
    app.question_pages()[0].run()
    assert "kind of hand 1 has no card types" in app.status.get()


def test_kinds_of_good_game(app: Any) -> None:
    from mtgcalc_gui.forms import Goal, Requirement

    page = app.question_pages()[0]
    land3, removal = Requirement("at least", 3, "land", 3), Requirement("at least", 1, "removal", 3)
    page.goal.set(Goal.all_of(land3, removal))
    groups = page.goal.lines
    groups.add()  # "Or another kind of good game": at least 1 land by turn 3
    groups.kinds[1][2].set([("at least", "4", "land", "turn 4")])
    goal = page.goal.value()
    assert goal.groups == ((land3, removal), (Requirement("at least", 4, "land", 4),))
    assert [t.cget("text") for _, t, _ in groups.kinds] == ["All of these:", "Or all of these:"]
    page.run()
    wait(app)
    assert ", or at least 4 land by turn 4 in" in page.headline.cget("text")
    page.goal.custom_on.set(True)
    page.goal._custom_changed()
    assert page.goal.custom() == "land >= 3 @T3 AND removal >= 1 @T3 OR land >= 4 @T4"


def test_typed_rule_is_prefilled_and_used(app: Any) -> None:
    page = app.question_pages()[0]
    page.goal.custom_on.set(True)
    page.goal._custom_changed()
    assert page.goal.custom().startswith("land >= 3 @T3")
    page.goal.custom_box.delete(0, "end")
    page.goal.custom_box.insert(0, "land >=")
    page.run()
    wait(app)
    assert "typed rule" in app.status.get()


def test_format_buttons_and_settings(app: Any) -> None:
    from mtgcalc_gui.app import SettingsDialog

    app.apply_format("Commander")
    assert app.deck_panel.deck_size() == "99" and not app.play_panel.first.get()
    dialog = SettingsDialog(app)
    dialog.method.set("montecarlo")
    dialog.games_box.set("5000")
    dialog.save()
    assert app.settings.method == "montecarlo" and app.settings.games == 5000
    from mtgcalc_gui.help import EXAMPLES

    app.apply_format("60-card")
    app.load_example(next(iter(EXAMPLES.values())))
    app.question_pages()[0].run()
    wait(app)
    assert "simulated" in app.question_pages()[0].headline.cget("text")


def test_help_windows_open(app: Any) -> None:
    from mtgcalc_gui.app import text_window
    from mtgcalc_gui.help import GETTING_STARTED

    win = text_window(app, "Getting started", GETTING_STARTED)
    win.destroy()


def test_importing_a_link_fills_the_decklist(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from pathlib import Path

    from mtgcalc_gui import forms
    from mtgcalc_online.archidekt import to_deck

    fixture = Path(__file__).parents[1] / "online" / "fixtures" / "archidekt_edge.json"
    monkeypatch.setattr(forms, "fetch_deck", lambda link: to_deck(json.loads(fixture.read_text())))
    app.deck_panel.link_box.insert(0, "https://archidekt.com/decks/42/edge-cases")
    app.deck_panel.import_button.invoke()
    wait(app)
    assert app.status.get().startswith("Imported 'Edge cases' from Archidekt")
    assert app.deck_panel.mode.get() == "decklist"
    assert "35 Forest #land" in app.deck_panel.decklist.get("1.0", "end")
    assert "mana-rock" in app.type_names()
    app.question_pages()[0].run()  # the imported deck answers questions
    wait(app)
    assert app.status.get().startswith("Done")


def test_import_errors_are_shown(app: Any) -> None:
    app.deck_panel.link_box.insert(0, "https://moxfield.com/decks/abc")
    app.deck_panel.import_button.invoke()
    wait(app)
    assert app.status.get().startswith("Could not import the deck: Moxfield does not let")
