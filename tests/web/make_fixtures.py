"""Golden cases for the web app, generated from the Python reference (ADR-0013 §7).

Writes ``web/fixtures/forms.json``. The web test suites check against it that:

* the TypeScript form layer builds the same scenario and query JSON as
  ``mtgcalc_gui.forms`` (``build_scenario`` / ``goal_condition``);
* the WebAssembly build answers each request exactly as Python does;
* the answer sentence and the percentage/"in words" texts match
  ``mtgcalc_gui.forms.chances`` / ``pct`` / ``in_words``.

Usage:  python -m tests.web.make_fixtures      (``--check`` compares instead of writing)

The cases are deterministic (fixed seed), and answers come from the pure-Python
engine, so the file only changes when the Python reference does.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "fixtures" / "forms.json"
SEED = 20261123


def _setup() -> None:
    """Make the imports below work when run as a script."""
    for p in (ROOT / "src", ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


@contextmanager
def _python_engine() -> Iterator[None]:
    """Answers come from the pure-Python reference engine (restored afterwards)."""
    old = os.environ.get("MTGCALC_ENGINE")
    os.environ["MTGCALC_ENGINE"] = "python"
    try:
        yield
    finally:
        if old is None:
            del os.environ["MTGCALC_ENGINE"]
        else:
            os.environ["MTGCALC_ENGINE"] = old


_setup()

from mtgcalc import Query, api  # noqa: E402
from mtgcalc.errors import ValidationError  # noqa: E402
from mtgcalc.model.serialization import to_dict  # noqa: E402
from mtgcalc_gui.forms import (  # noqa: E402
    ANY_CARD,
    KINDS,
    CardType,
    DeckSetup,
    Goal,
    HowMany,
    MulliganSetup,
    PlaySetup,
    Requirement,
    Vary,
    build_scenario,
    chances,
    draws,
    goal_condition,
    how_many,
    in_words,
    mulligan_advice,
    pct,
    turn_by_turn,
)
from mtgcalc_gui.help import EXAMPLES  # noqa: E402

Json = dict[str, Any]


def _form(deck: DeckSetup, play: PlaySetup, goal: Goal) -> Json:
    """The validated web setup (camelCase, as web/src/forms/model.ts defines it)."""
    return {
        "deck": {
            "size": deck.size,
            "types": [{"name": t.name, "count": t.count, "also": list(t.also)} for t in deck.types],
        },
        "play": {"goFirst": play.go_first, "drawsPerTurn": play.draws_per_turn},
        "goal": {
            "combine": goal.combine,
            "requirements": [
                {"kind": r.kind, "amount": r.amount, "cardType": r.card_type, "turn": r.turn}
                for r in goal.requirements
            ],
        },
    }


def _case(name: str, deck: DeckSetup, play: PlaySetup, goal: Goal) -> Json:
    sc = build_scenario(deck, play, MulliganSetup())
    query = Query(goal_condition(goal))
    answer = api.probability(sc, query)
    return {
        "name": name,
        "setup": _form(deck, play, goal),
        "request": {"scenario": to_dict(sc), "query": to_dict(query)},
        "answer": to_dict(answer),
        "headline": chances(sc, goal).headline,
    }


def _random_case(rng: random.Random, i: int) -> Json:
    size = rng.choice([40, 60, 99, 100])
    pool = ["land", "ramp", "removal", "draw", "bomb", "mana rock"]
    names = rng.sample(pool, rng.randint(1, 4))
    left = size
    types = []
    for n in names:
        count = rng.randint(0, min(left, 30))
        left -= count
        also = tuple(rng.sample([x for x in pool if x != n], rng.choice([0, 0, 1, 2])))
        types.append(CardType(n, count, also))
    offered = [*dict.fromkeys(x for t in types for x in (t.name, *t.also)), ANY_CARD]
    reqs = tuple(
        Requirement(rng.choice(KINDS), rng.randint(0, 4), rng.choice(offered), rng.randint(0, 8))
        for _ in range(rng.randint(1, 3))
    )
    goal = Goal(reqs, rng.choice(["all", "any"]))
    play = PlaySetup(go_first=rng.random() < 0.5, draws_per_turn=rng.choice([1, 1, 1, 0, 2]))
    return _case(f"random {i}", DeckSetup(size, tuple(types)), play, goal)


def _form_case(
    name: str, deck: DeckSetup, play: PlaySetup, goal: Goal, lines: tuple[Requirement, ...]
) -> Json:
    """A case given as the web form's raw state (decklist and/or typed rule)."""
    sc = build_scenario(deck, play, MulliganSetup())
    answer = api.probability(sc, Query(goal_condition(goal)))
    return {
        "name": name,
        "form": {
            "deckMode": "list" if deck.mode == "decklist" else "types",
            "deckSize": str(deck.size),
            "types": [
                {"id": f"t{i}", "name": t.name, "count": str(t.count), "also": ", ".join(t.also)}
                for i, t in enumerate(deck.types)
            ],
            "decklist": deck.decklist,
            "goFirst": play.go_first,
            "drawsPerTurn": str(play.draws_per_turn),
            "goal": [
                {
                    "id": f"g{i}",
                    "kind": r.kind,
                    "amount": str(r.amount),
                    "cardType": r.card_type,
                    "turn": str(r.turn),
                }
                for i, r in enumerate(lines)
            ],
            "combine": goal.combine,
            "useRule": bool(goal.custom),
            "rule": goal.custom,
            "question": "chances",
            "drawsType": "",
            "lastTurn": "5",
            **_mulligan_form(MulliganSetup()),
            "hmMode": "one",
            "hmAim": "target",
            "hmVary": [{"id": "v0", "cardType": "land", "low": "14", "high": "40"}],
            "hmTarget": "90",
            "hmSlots": "20",
        },
        "answer": to_dict(answer),
        "headline": chances(sc, goal).headline,
    }


_RULES = (
    "land >= 3 @T3",
    "land >= 2 AND ramp >= 1 @T2",
    "(land >= 3 AND ramp >= 1) @T3 OR draw >= 2 @T4",
    "assign(land >= 2, ramp >= 1) @T2",
    "any(ramp, draw) >= 2 @T4",
    "NOT land >= 5 @T5",
    "land in 2..4",
    "atleast(2, land >= 3 @T3, ramp >= 1 @T3, draw >= 1 @T3)",
    'card:"Sol Ring" >= 1 @T2 -> ramp >= 2 @T2',
    "everything >= 9 @T2 XOR land >= 4 @T2",
)


def _decklist(rng: random.Random) -> tuple[str, int]:
    """A random decklist with #tags (and its library size)."""
    lines = ["Commander", "1 Atraxa, Praetors' Voice", "", "Deck"] if rng.random() < 0.4 else []
    spec = [
        ("Forest", "#land"),
        ("Mosswort Bridge", "#land #ramp"),
        ("Sol Ring", "#ramp"),
        ("Llanowar Elves", "#ramp #creature"),
        ("Divination", "#draw"),
        ("Bear", ""),
    ]
    size = 0
    for card, tags in spec:
        n = rng.randint(1, 30) if card != "Sol Ring" else 1
        size += n
        lines.append(f"{n} {card} {tags}".rstrip())
    return "\n".join(lines) + "\n", size


def _form_cases(rng: random.Random) -> list[Json]:
    out = []
    for i in range(25):
        text, size = _decklist(rng)
        deck = DeckSetup(size, mode="decklist", decklist=text)
        play = PlaySetup(go_first=rng.random() < 0.5)
        offered = ["land", "ramp", "draw", "creature", ANY_CARD]
        lines = tuple(
            Requirement(
                rng.choice(KINDS), rng.randint(0, 4), rng.choice(offered), rng.randint(0, 6)
            )
            for _ in range(rng.randint(1, 2))
        )
        goal = Goal(lines, rng.choice(["all", "any"]))
        out.append(_form_case(f"decklist {i}", deck, play, goal, lines))
    for i, rule in enumerate(_RULES):
        text, size = _decklist(rng)
        if rng.random() < 0.5:
            deck = DeckSetup(size, mode="decklist", decklist=text)
        else:
            deck = DeckSetup(
                60,
                (
                    CardType("land", 24, ("ramp",)),
                    CardType("ramp", 8),
                    CardType("draw", 6),
                    CardType("Sol Ring", 1, ("ramp",)),
                ),
            )
        lines = (Requirement(),)
        goal = Goal(lines, custom=rule)
        out.append(
            _form_case(f"rule {i}", deck, PlaySetup(go_first=rng.random() < 0.5), goal, lines)
        )
    return out


def _question_cases(rng: random.Random) -> list[Json]:
    """ "How many will I draw?" and "Turn by turn", as the desktop app shows them."""
    out = []
    for i in range(12):
        size = rng.choice([40, 60, 99])
        types = (
            CardType("land", rng.randint(14, 40)),
            CardType("ramp", rng.randint(0, 10), ("land",)),
        )
        deck = DeckSetup(size, types)
        play = PlaySetup(go_first=rng.random() < 0.5, draws_per_turn=rng.choice([1, 1, 2]))
        sc = build_scenario(deck, play, MulliganSetup())
        last = rng.randint(0, 6)
        lines = (
            Requirement(
                rng.choice(KINDS), rng.randint(0, 4), rng.choice(["land", "ramp", ANY_CARD]), 0
            ),
        )
        form = _form_case(f"q{i}", deck, play, Goal(lines), lines)["form"]
        if i % 2 == 0:
            card_type = rng.choice(["land", "ramp", ANY_CARD])
            view = draws(sc, card_type, last)
            form |= {"question": "draws", "drawsType": card_type, "lastTurn": str(last)}
            rows = [[r.values[0], [list(k.values) for k in r.children]] for r in view.rows]
        else:
            goal = Goal(lines)
            if i % 4 == 3:
                goal = Goal(lines, custom="land >= 3 OR ramp >= 1 @T2")
                form |= {"useRule": True, "rule": goal.custom}
            view = turn_by_turn(sc, goal, last)
            form |= {"question": "turns", "lastTurn": str(last)}
            rows = [list(r.values) for r in view.rows]
        out.append(
            {
                "name": f"{form['question']} {i}",
                "form": form,
                "headline": view.headline,
                "rows": rows,
            }
        )
    return out


def _mulligan_form(m: MulliganSetup) -> Json:
    return {
        "mulligans": m.enabled,
        "keepType": m.keep_type,
        "keepMin": str(m.keep_min),
        "keepMax": str(m.keep_max),
        "protect": [
            {"id": f"p{i}", "cardType": t, "upTo": str(n)} for i, (t, n) in enumerate(m.protect)
        ],
        "maxMulligans": str(m.max_mulligans),
        "freeFirst": m.free_first,
    }


def _mulligan_cases(rng: random.Random) -> list[Json]:
    """Mulligans: "What are my chances?" with a plan, and "Should I mulligan?"."""
    out = []
    for i in range(10):
        size = rng.choice([40, 60, 99])
        types = (CardType("land", rng.randint(14, 38)), CardType("ramp", rng.randint(0, 10)))
        deck = DeckSetup(size, types)
        play = PlaySetup(go_first=rng.random() < 0.5)
        keep_type = rng.choice(["land", "land", ""])
        mull = MulliganSetup(
            enabled=True,
            keep_type=keep_type,
            keep_min=rng.randint(1, 3),
            keep_max=rng.randint(4, 6),
            protect=(("land", rng.randint(2, 4)), ("ramp", rng.randint(0, 2)))[: rng.randint(1, 2)],
            max_mulligans=rng.randint(0, 3),
            free_first=rng.random() < 0.4,
        )
        lines = (
            Requirement(
                "at least", rng.randint(1, 4), rng.choice(["land", "ramp"]), rng.randint(0, 4)
            ),
        )
        goal = Goal(lines)
        sc = build_scenario(deck, play, mull)
        form = _form_case(f"m{i}", deck, play, goal, lines)["form"] | _mulligan_form(mull)
        if i % 2 == 0:
            view = chances(sc, goal)
            rows: list[Any] = []
        else:
            view = mulligan_advice(sc, goal)
            form |= {"question": "mulligan"}
            rows = [
                [
                    list(r.values),
                    [[list(k.values), [list(h.values) for h in k.children]] for k in r.children],
                ]
                for r in view.rows
            ]
        out.append(
            {
                "name": f"mulligan {i}",
                "form": form,
                "headline": view.headline,
                "details": list(view.details),
                "rows": rows,
            }
        )
    return out


def _how_many_cases() -> list[Json]:
    """ "How many should I play?" in each mode and aim, as the desktop app answers."""
    deck = DeckSetup(
        60, (CardType("land", 24), CardType("ramp", 6, ("land",)), CardType("draw", 4))
    )
    lines = (Requirement("at least", 4, "land", 4), Requirement("at least", 1, "ramp", 2))
    goal = Goal(lines)
    out = []
    for i, q in enumerate(
        (
            HowMany("one", "target", (Vary("land", 14, 30),), 80.0, goal=Goal((lines[0],))),
            HowMany("one", "target", (Vary("land", 20, 24),), 99.0, goal=Goal((lines[0],))),
            HowMany("share", "best", (Vary("land", 18, 26), Vary("ramp", 0, 8)), 0, 30, goal),
            HowMany("share", "target", (Vary("land", 14, 28), Vary("ramp", 0, 8)), 50.0, 50, goal),
            HowMany("share", "target", (Vary("land", 14, 28), Vary("ramp", 0, 8)), 70.0, 50, goal),
            HowMany("share", "target", (Vary("land", 14, 28), Vary("ramp", 0, 8)), 50.0, 16, goal),
            HowMany(
                "one",
                "target",
                (Vary("draw", 0, 8),),
                50.0,
                goal=Goal((Requirement("at least", 1, "draw", 3),)),
            ),
            # The best chance, with no target: at the top of the range, and inside it.
            HowMany("one", "best", (Vary("land", 14, 30),), goal=Goal((lines[0],))),
            HowMany(
                "one",
                "best",
                (Vary("land", 10, 40),),
                goal=Goal((Requirement("at least", 3, "land"), Requirement("at most", 5, "land"))),
            ),
        )
    ):
        sc = build_scenario(deck, PlaySetup(), MulliganSetup())
        try:
            view = how_many(deck, sc, q)
            result: Json = {
                "headline": view.headline,
                "details": list(view.details),
                "rows": [list(r.values) for r in view.rows],
            }
        except ValidationError as e:
            result = {"error": e.message}
        form = _form_case(f"h{i}", deck, PlaySetup(), q.goal, q.goal.requirements)["form"] | {
            "question": "howmany",
            "hmMode": q.mode,
            "hmAim": q.aim,
            "hmVary": [
                {"id": f"v{j}", "cardType": v.card_type, "low": str(v.low), "high": str(v.high)}
                for j, v in enumerate(q.vary)
            ],
            "hmTarget": f"{q.target_percent:g}",
            "hmSlots": str(q.slots),
        }
        out.append({"name": f"how many {i} ({q.mode}, {q.aim})", "form": form, **result})
    return out


def _percentages(rng: random.Random) -> list[Json]:
    """pct / in_words on edges and random fractions (strings compared exactly)."""
    values = [
        Fraction(0),
        Fraction(1),
        Fraction(1, 2),
        Fraction(1, 16),
        Fraction(1, 1000),
        Fraction(1, 1001),
        Fraction(1, 10**6),
        Fraction(1, 10**9),
        Fraction(999, 1000),
        Fraction(9995, 10000),
        Fraction(995, 1000),
        Fraction(994, 1000),
        Fraction(5, 1000),
        Fraction(6, 1000),
        Fraction(1, 10),
        Fraction(99, 1000),
        Fraction(15, 100),
        Fraction(25, 100),
        Fraction(38962, 97527),
        Fraction(1, 3),
        Fraction(2, 3),
        Fraction(1, 7),
        Fraction(1, 21),
        Fraction(1, 25),
        Fraction(3, 4000),
    ]
    for _ in range(300):
        d = rng.randint(1, 10 ** rng.randint(1, 12))
        values.append(Fraction(rng.randint(0, d), d))
    return [
        {"value": f"{v.numerator}/{v.denominator}", "pct": pct(v), "inWords": in_words(v)}
        for v in values
    ]


def build() -> Json:
    """Every golden case, deterministically."""
    with _python_engine():
        return _build()


def _build() -> Json:
    rng = random.Random(SEED)
    cases = [
        _case(name, ex.deck, ex.play, ex.goal)
        for name, ex in EXAMPLES.items()
        if ex.deck.mode == "types"
    ]
    cases += [_random_case(rng, i) for i in range(60)]
    return {
        "_about": "Generated by tests/web/make_fixtures.py from the Python reference. Do not edit.",
        "defaults": {
            "deck": asdict(DeckSetup()) | {"types": [asdict(t) for t in DeckSetup().types]},
            "play": asdict(PlaySetup()),
        },
        "cases": cases,
        "formCases": _form_cases(rng),
        "questionCases": _question_cases(rng),
        "mulliganCases": _mulligan_cases(rng),
        "howManyCases": _how_many_cases(),
        "percentages": _percentages(rng),
    }


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is out of date; run python -m tests.web.make_fixtures", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
