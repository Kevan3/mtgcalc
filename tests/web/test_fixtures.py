"""The web app's golden cases are up to date with the Python reference (ADR-0013 §7)."""

from __future__ import annotations

import os

from tests.web.make_fixtures import OUT, render


def test_fixtures_are_fresh() -> None:
    assert OUT.read_text(encoding="utf-8") == render(), (
        "web/fixtures/forms.json is out of date: run python -m tests.web.make_fixtures"
    )


def test_generation_does_not_leak_the_engine_choice() -> None:
    before = os.environ.get("MTGCALC_ENGINE")
    render()
    assert os.environ.get("MTGCALC_ENGINE") == before
