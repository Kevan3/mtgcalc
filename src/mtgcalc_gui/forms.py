"""Plain-language logic behind the GUI (no Tk; fully unit-testable).

The GUI speaks in everyday terms ("card types", "a good game", "by turn 3"); this module
translates those answers into mtgcalc objects and turns results back into sentences and
tables. Every function raises :class:`mtgcalc.MtgCalcError` subclasses on bad input,
with messages written for players rather than programmers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Literal

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
    api,
    everything,
    format_decklist,
    parse_condition,
    parse_decklist,
    tag,
)
from mtgcalc.analysis.optimizer import Objective
from mtgcalc.errors import InfeasibleError, MtgCalcError, ValidationError
from mtgcalc.model.conditions import And, At, Between, Compare, Condition, Const, Or
from mtgcalc.model.mulligan import KEEP_ANY
from mtgcalc.model.results import ConditionalResult, Probability
from mtgcalc.model.selectors import Selector
from mtgcalc_online import fetch_deck, recognize

ANY_CARD = "any card"

# ---------------------------------------------------------------------------------------
# Display model
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Row:
    """One table row; ``children`` are shown nested under it."""

    values: tuple[str, ...]
    children: tuple[Row, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultView:
    """What a question page shows.

    ``headline`` is the one-sentence answer, ``details`` are supporting sentences, the
    table is optional, and ``legend`` explains each column in plain words.
    """

    headline: str
    details: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    legend: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Settings:
    """Technical options, hidden behind the Settings dialog."""

    method: Literal["exact", "montecarlo", "auto"] = "exact"
    games: int = 200_000
    seed: int | None = None
    fractions: bool = False


def fixed(x: Fraction | float, places: int) -> str:
    """``x`` with ``places`` decimals. An exact value is rounded exactly, ties to even.

    Formatting ``float(x)`` instead would round the nearest binary number, so 147/40 =
    3.675 (stored as 3.67499...) would print as "3.67"; the web app rounds exactly.
    """
    if isinstance(x, float):
        return f"{x:.{places}f}"
    n = round(x * 10**places)  # Fraction.__round__ rounds ties to even
    sign, n = ("-" if n < 0 else ""), abs(n)
    whole, frac = divmod(n, 10**places)
    return f"{sign}{whole}.{frac:0{places}d}" if places else f"{sign}{whole}"


def pct(p: Fraction | float, settings: Settings = Settings()) -> str:
    """A probability as a percentage, e.g. ``"47.7%"`` (plus the exact fraction if asked)."""
    value = p * 100
    if 0 < value < Fraction(1, 1000):
        text = "less than 0.001%"
    elif Fraction(1, 10) <= value <= Fraction(999, 10) or value in (0, 100):
        text = f"{fixed(value, 1)}%"
    else:
        text = f"{fixed(value, 3)}%"
    if settings.fractions and isinstance(p, Fraction) and p.denominator != 1:
        text += f" (= {p.numerator}/{p.denominator})"
    return text


def in_words(p: Fraction | float) -> str:
    """Rough everyday phrasing of a probability.

    Near the middle: "about 4 games in 10". Rare things: "about 1 game in 25". Near-certain
    things: "all but about 1 game in 25" (never "about 10 games in 10").
    """
    if p == 0:
        return "never"
    if p == 1:
        return "every game"
    x = float(p)
    if x >= 0.995:
        return "almost every game"
    if x <= 0.005:
        return "almost never"
    if x < 0.15:
        return f"about 1 game in {round(1 / x)}"
    if x > 0.85:
        return f"all but about 1 game in {round(1 / (1 - x))}"
    return f"about {round(x * 10)} games in 10"


def turn_words(turn: int) -> str:
    """``0`` -> "in your opening hand", ``3`` -> "by turn 3"."""
    return "in your opening hand" if turn == 0 else f"by turn {turn}"


# ---------------------------------------------------------------------------------------
# Step 1 and 2: the deck and how you play
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CardType:
    """A kind of card you care about, e.g. 24 "land", or 2 "mdfc" that also count as land."""

    name: str
    count: int
    also: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeckSetup:
    """Step 1. ``mode`` "types" uses the card-type table; "decklist" uses pasted text."""

    size: int = 60
    types: tuple[CardType, ...] = (CardType("land", 24), CardType("removal", 6))
    mode: Literal["types", "decklist"] = "types"
    decklist: str = ""


@dataclass(frozen=True, slots=True)
class PlaySetup:
    """Step 2 (without mulligans)."""

    go_first: bool = True
    draws_per_turn: int = 1
    extra_draws: tuple[tuple[int, int], ...] = ()  # (turn, extra cards)


@dataclass(frozen=True, slots=True)
class KeepRule:
    """One line of a keep rule: the hand has ``low`` to ``high`` cards of ``card_type``."""

    card_type: str
    low: int
    high: int


#: The default keep rule: one kind of hand, with 2 to 5 land.
DEFAULT_KEEP: tuple[tuple[KeepRule, ...], ...] = ((KeepRule("land", 2, 5),),)


@dataclass(frozen=True, slots=True)
class MulliganSetup:
    """Step 2, mulligans.

    ``keep`` lists the kinds of hand you keep: a hand is kept when it matches *any* kind,
    and it matches a kind when *every* line of that kind holds. No kinds means "always
    keep the first hand".
    """

    enabled: bool = False
    keep: tuple[tuple[KeepRule, ...], ...] = DEFAULT_KEEP
    protect: tuple[tuple[str, int], ...] = (("land", 3),)  # (card type, keep up to)
    max_mulligans: int = 2
    free_first: bool = False


#: Format presets for the three buttons: (cards in library, go first, free first mulligan).
FORMATS: dict[str, tuple[int, bool, bool]] = {
    "60-card": (60, True, False),
    "40-card Limited": (40, True, False),
    "Commander": (99, False, True),
}


def _clean(name: str) -> str:
    return " ".join(name.split()).casefold()


def type_names(deck: DeckSetup) -> list[str]:
    """Names offered in every "card type" dropdown (types, their extra labels, tags)."""
    names: list[str] = []
    if deck.mode == "decklist":
        try:
            names = list(parse_decklist(deck.decklist).tag_counts())
        except MtgCalcError:  # an unfinished decklist simply offers no names yet
            names = []
    else:
        for t in deck.types:
            for n in (t.name, *t.also):
                if _clean(n) and _clean(n) not in names:
                    names.append(_clean(n))
    return [*names, ANY_CARD]


def selector_for(name: str) -> Selector:
    """The selector for a dropdown choice."""
    return everything() if name == ANY_CARD else tag(name)


def build_deck(deck: DeckSetup) -> Deck:
    """Turn step 1 into a :class:`Deck` (other cards become anonymous filler)."""
    if deck.mode == "decklist":
        if not deck.decklist.strip():
            raise ValidationError("decklist", "paste a decklist, or switch to card types")
        return parse_decklist(deck.decklist)
    if deck.size < 1:
        raise ValidationError("cards in deck", "must be at least 1")
    seen: set[str] = set()
    categories: dict[str, Category] = {}
    for t in deck.types:
        name = _clean(t.name)
        if not name:
            raise ValidationError("card types", "every card type needs a name")
        if name in seen:
            raise ValidationError("card types", f"'{t.name}' is listed twice")
        if t.count < 0:
            raise ValidationError("card types", f"'{t.name}' cannot have a negative count")
        seen.add(name)
        categories[name] = Category(t.count, frozenset(_clean(a) for a in t.also if _clean(a)))
    total = sum(c.count for c in categories.values())
    if total > deck.size:
        raise ValidationError(
            "card types", f"the card types add up to {total}, more than the {deck.size} cards"
        )
    return Deck.from_counts(deck.size, categories)


def build_scenario(deck: DeckSetup, play: PlaySetup, mull: MulliganSetup) -> Scenario:
    """Steps 1 and 2 as a :class:`Scenario`."""
    game = GameConfig(
        hand_size=7,
        on_play=play.go_first,
        draws_per_turn=play.draws_per_turn,
        extra_draws=_merge_extra(play.extra_draws),
    )
    mulligan = None
    if mull.enabled:
        if not mull.protect:
            raise ValidationError(
                "mulligans", "choose at least one card type to keep when bottoming"
            )
        keep = keep_condition(mull.keep)
        protect: list[PriorityGroup] = []
        for name, n in mull.protect:
            group = PriorityGroup(selector_for(name), n)
            if any(g.selector == group.selector for g in protect):
                raise ValidationError("keep first", f"'{name}' is listed twice")
            protect.append(group)
        mulligan = MulliganConfig(
            priority=tuple(protect),
            keep_rule=keep,
            max_mulligans=mull.max_mulligans,
            free_mulligans=1 if mull.free_first else 0,
        )
    return Scenario(build_deck(deck), game, mulligan)


def keep_condition(keep: tuple[tuple[KeepRule, ...], ...]) -> Condition:
    """The keep rule as a condition: any kind of hand (``Or``), each with all its lines (``And``).

    A single line stays a plain ``Between`` and a single kind a plain ``And``, so the
    condition is never wrapped needlessly. No kinds means "keep any hand".
    """
    kinds: list[Condition] = []
    for n, rules in enumerate(keep, start=1):
        if not rules:
            raise ValidationError("keep rule", f"kind of hand {n} has no card types; add one")
        lines: list[Condition] = []
        for r in rules:
            if r.low > r.high:
                raise ValidationError("keep rule", "the smallest number is above the largest")
            lines.append(Between(selector_for(r.card_type), r.low, r.high))
        kinds.append(lines[0] if len(lines) == 1 else And(tuple(lines)))
    if not kinds:
        return KEEP_ANY
    return kinds[0] if len(kinds) == 1 else Or(tuple(kinds))


def _merge_extra(extra: tuple[tuple[int, int], ...]) -> dict[int, int]:
    merged: dict[int, int] = {}
    for turn, n in extra:
        if turn < 1:
            raise ValidationError("extra cards", "extra cards are drawn on turn 1 or later")
        merged[turn] = merged.get(turn, 0) + n
    return merged


def describe_scenario(sc: Scenario) -> str:
    """A plain summary of the deck and play settings."""
    counts = sc.deck.tag_counts()
    parts = [f"{n} {t}" for t, n in counts.items() if t != "(other)"]
    other = sc.deck.size - sum(c.quantity for c in sc.deck.library if c.tags - {"(other)"})
    if other:
        parts.append(f"{other} other cards")
    first = "you go first (no draw on turn 1)" if sc.game.on_play else "you draw on turn 1"
    text = f"{sc.deck.size}-card deck: {', '.join(parts) or 'no card types'}; {first}."
    if sc.mulligan is not None:
        m = sc.mulligan
        free = ", first one free" if m.free_mulligans else ""
        text += f" Mulligans allowed (up to {m.max_mulligans}{free})."
    return text


@dataclass(frozen=True, slots=True)
class ImportedDeck:
    """A deck downloaded from a link, as editable decklist text plus a summary."""

    text: str
    summary: str


def import_deck(link: str) -> ImportedDeck:
    """Download the deck at ``link`` (network; run it off the UI thread).

    Raises:
        DeckFetchError: with a message for the player (unsupported link, offline, ...).
    """
    source, _ = recognize(link)
    deck = fetch_deck(link)
    commanders = [c.name for c in deck.cards if c.zone == "commander"]
    tags = list(deck.tag_counts())
    parts = [f"Imported '{deck.name}' from {source.name}: {deck.size} cards in the deck"]
    if commanders:
        parts.append(f"commander {', '.join(commanders)}")
    if tags:
        shown = ", ".join(tags[:6]) + (", ..." if len(tags) > 6 else "")
        parts.append(f"{len(tags)} tags ({shown})")
    return ImportedDeck(
        format_decklist(deck),
        "; ".join(parts) + ". Check or edit the cards and tags in the box.",
    )


# ---------------------------------------------------------------------------------------
# Goals: "what counts as a good game"
# ---------------------------------------------------------------------------------------

Kind = Literal["at least", "at most", "exactly", "none"]
KINDS: tuple[Kind, ...] = ("at least", "at most", "exactly", "none")


@dataclass(frozen=True, slots=True)
class Requirement:
    """One row of the goal builder: e.g. at least 3 land by turn 3."""

    kind: Kind = "at least"
    amount: int = 1
    card_type: str = "land"
    turn: int = 0


@dataclass(frozen=True, slots=True)
class Goal:
    """What a good game is: kinds of good game, each a tuple of lines (FR-106).

    A game is good when it fits *any* kind, and it fits a kind when *every* line of that
    kind holds (as the kinds of hand to keep, ADR-0014). ``custom`` (a typed rule)
    overrides the lines.
    """

    groups: tuple[tuple[Requirement, ...], ...] = ((Requirement(),),)
    custom: str = ""

    @classmethod
    def all_of(cls, *lines: Requirement, custom: str = "") -> Goal:
        """One kind of good game: every line must hold."""
        return cls((tuple(lines),) if lines else (), custom)

    @classmethod
    def any_of(cls, *lines: Requirement) -> Goal:
        """One kind per line: any line will do."""
        return cls(tuple((r,) for r in lines))

    @property
    def requirements(self) -> tuple[Requirement, ...]:
        """Every line, kind by kind."""
        return tuple(r for group in self.groups for r in group)


def _requirement(r: Requirement, with_turn: bool) -> Condition:
    if r.amount < 0:
        raise ValidationError("goal", "numbers cannot be negative")
    sel = selector_for(r.card_type)
    leaf: Condition
    if r.kind == "none":
        leaf = Compare(sel, "==", 0)
    elif r.kind == "at least":
        leaf = Compare(sel, ">=", r.amount)
    elif r.kind == "at most":
        leaf = Compare(sel, "<=", r.amount)
    else:
        leaf = Compare(sel, "==", r.amount)
    return At(r.turn, leaf) if with_turn else leaf


def goal_condition(goal: Goal, *, with_turns: bool = True) -> Condition:
    """The goal as a condition. ``with_turns=False`` drops the per-row turns."""
    if goal.custom.strip():
        return parse_condition(goal.custom)
    if not goal.requirements:
        raise ValidationError("goal", "add at least one requirement")
    kinds: list[Condition] = []
    for n, group in enumerate(goal.groups, start=1):
        if not group:
            raise ValidationError("goal", f"kind of good game {n} has no lines; add one")
        lines = [_requirement(r, with_turns) for r in group]
        kinds.append(lines[0] if len(lines) == 1 else And(tuple(lines)))
    return kinds[0] if len(kinds) == 1 else Or(tuple(kinds))


def describe_goal(goal: Goal, *, with_turns: bool = True) -> str:
    """The goal in words, e.g. "at least 3 land by turn 3 and at least 1 removal, or ...".

    Lines of a kind are joined with "and", kinds with "or".
    """
    if goal.custom.strip():
        return f"your rule ({goal.custom.strip()})"

    def line(r: Requirement) -> str:
        what = r.card_type
        if r.card_type == ANY_CARD:
            what = "card" if r.kind != "none" and r.amount == 1 else "cards"
        amount = "no" if r.kind == "none" else f"{r.kind} {r.amount}"
        text = f"{amount} {what}"
        return f"{text} {turn_words(r.turn)}" if with_turns else text

    kinds = [" and ".join(line(r) for r in group) for group in goal.groups]
    # Kinds of one line each read "A or B"; a kind with several lines needs the comma.
    return (", or " if any(len(g) > 1 for g in goal.groups) else " or ").join(kinds)


def goal_as_text(goal: Goal, *, with_turns: bool = True) -> str:
    """The goal in the typed-rule language (to pre-fill the "type your own" box)."""
    return api.format_condition(goal_condition(goal, with_turns=with_turns))


# ---------------------------------------------------------------------------------------
# Question 1: what are my chances?
# ---------------------------------------------------------------------------------------


def _value(p: Probability) -> Fraction | float:
    return p.exact if p.exact is not None else p.value


def _how(p: Probability) -> str:
    if p.method == "exact":
        return ""
    lo, hi = p.ci95 or (p.value, p.value)
    return f" (simulated; very likely between {pct(lo)} and {pct(hi)})"


def chances(
    sc: Scenario, goal: Goal, only_if: Goal | None = None, settings: Settings = Settings()
) -> ResultView:
    """The chance of a good game, optionally only counting games where ``only_if`` holds."""
    cond = goal_condition(goal)
    given = goal_condition(only_if) if only_if is not None else None
    res = api.probability(
        sc, Query(cond, given), engine=settings.method, trials=settings.games, seed=settings.seed
    )
    details: list[str] = []
    if sc.mulligan is not None:
        details.append("This includes the games where you mulligan, following your plan.")
    if isinstance(res, ConditionalResult):
        assert only_if is not None
        if res.result is None:
            return ResultView(
                f"That never happens: {describe_goal(only_if)} is impossible with this deck."
            )
        p = _value(res.result)
        headline = (
            f"In the games where you have {describe_goal(only_if)}, you have "
            f"{describe_goal(goal)} {pct(p, settings)} of the time ({in_words(p)})"
            f"{_how(res.result)}."
        )
        details.append(
            f"Those games are {pct(_value(res.given), settings)} of all games; both things "
            f"happen together in {pct(_value(res.joint), settings)} of all games."
        )
    else:
        p = _value(res)
        headline = (
            f"You have {describe_goal(goal)} in {pct(p, settings)} of games "
            f"({in_words(p)}){_how(res)}."
        )
        details += [f"Note: {w}" for w in res.warnings]
    return ResultView(headline, tuple(details))


# ---------------------------------------------------------------------------------------
# Question 2: how many will I draw?
# ---------------------------------------------------------------------------------------


def draws(
    sc: Scenario, card_type: str, last_turn: int, settings: Settings = Settings()
) -> ResultView:
    """For each turn up to ``last_turn``: the chance of drawing each number of a card type."""
    if last_turn < 0:
        raise ValidationError("turn", "choose turn 0 or later")
    sel = selector_for(card_type)
    what = "cards" if card_type == ANY_CARD else card_type
    rows = []
    averages = []
    for t in range(last_turn + 1):
        d = api.distribution(sc, sel, t)
        averages.append((t, d.mean))
        kids = tuple(
            Row(
                (
                    f"{k} {what}",
                    pct(d.exactly(k), settings),
                    pct(d.at_least(k), settings),
                    pct(d.at_most(k), settings),
                )
            )
            for k in range(len(d.pmf))
        )
        label = "Opening hand" if t == 0 else f"By turn {t}"
        rows.append(Row((f"{label}  (average {fixed(d.mean, 2)})", "", "", ""), kids))
    t, avg = averages[-1]
    return ResultView(
        f"On average you will have seen {fixed(avg, 2)} {what} {turn_words(t)}.",
        ("Click a turn to see the chance of each number.",),
        headers=("When / how many", "Exactly this many", "This many or more", "This many or fewer"),
        rows=tuple(rows),
        legend=(
            ("Exactly this many", "the chance of having seen exactly that number"),
            ("This many or more", "the chance of at least that number (useful for 'I need 3')"),
            ("This many or fewer", "the chance of no more than that number (flooding)"),
        ),
    )


# ---------------------------------------------------------------------------------------
# Question 3: turn by turn
# ---------------------------------------------------------------------------------------


def turn_by_turn(
    sc: Scenario, goal: Goal, last_turn: int, settings: Settings = Settings()
) -> ResultView:
    """The chance of the goal (ignoring its own turns) by each turn up to ``last_turn``."""
    if last_turn < 0:
        raise ValidationError("turn", "choose turn 0 or later")
    cond = goal_condition(goal, with_turns=False)
    table = api.turn_table(sc, cond, list(range(last_turn + 1)))
    rows = tuple(
        Row(
            (
                "Opening hand" if r.turn == 0 else f"Turn {r.turn}",
                str(r.cards_seen),
                pct(r.probability, settings),
                in_words(r.probability),
            )
        )
        for r in table.rows
    )
    return ResultView(
        f"The chance of having {describe_goal(goal, with_turns=False)}, turn by turn.",
        headers=("When", "Cards seen", "Chance", "In words"),
        rows=rows,
        legend=(("Cards seen", "your opening hand plus every card drawn so far"),),
    )


# ---------------------------------------------------------------------------------------
# Question 4: should I mulligan?
# ---------------------------------------------------------------------------------------


def _step_name(depth: int, hand: int) -> str:
    if depth == 0:
        return "First 7 cards"
    return f"After {depth} mulligan{'s' if depth > 1 else ''} (keep {hand})"


def mulligan_advice(sc: Scenario, goal: Goal, settings: Settings = Settings()) -> ResultView:
    """How your mulligan plan does, compared with never mulliganing and the best plan."""
    if sc.mulligan is None:
        raise ValidationError("mulligans", "turn on mulligans in step 2 first")
    cond = goal_condition(goal)
    rep = api.mulligan_report(sc, cond)
    best = api.optimal_keep(sc, cond)
    never = rep.rows[0].p_success_forced
    headline = (
        f"With your mulligan plan you get a good game {pct(rep.p_success, settings)} of the "
        f"time. Never mulliganing: {pct(never, settings)}. The best possible plan: "
        f"{pct(best.value, settings)}."
    )
    details = (
        f"A good game means: {describe_goal(goal)}.",
        f"On average you mulligan {fixed(rep.expected_mulligans, 2)} times and keep "
        f"{fixed(rep.expected_hand_size, 2)} cards.",
        "The best plan (below) keeps a hand only when that hand is at least as good as "
        "mulliganing would be on average.",
    )
    your_plan = Row(
        ("Your plan", "", "", ""),
        tuple(
            Row(
                (
                    _step_name(r.depth, r.hand_size),
                    pct(r.p_reach, settings),
                    pct(r.p_keep_given_reach, settings),
                    pct(r.p_success_forced, settings),
                )
            )
            for r in rep.rows
        ),
    )
    labels = [names[0] if len(names) == 1 else " / ".join(names) for names in best.atoms]
    draw_size = sc.mulligan.draw_size
    last = len(best.rows) - 1
    steps = []
    for r in best.rows:
        hands = []
        for h in sorted(r.hands, key=lambda h: (-h.success, -h.probability)):
            parts = [f"{n} {lbl}" for n, lbl in zip(h.atom_counts, labels, strict=True) if n]
            other = draw_size - sum(h.atom_counts)
            if other:
                parts.append(f"{other} other")
            hands.append(
                Row(
                    (
                        f"{', '.join(parts)}  ->  {'keep' if h.keep else 'mulligan'}",
                        "",
                        pct(h.probability, settings),
                        pct(h.success, settings),
                    )
                )
            )
        rule = (
            "keep any hand"
            if r.depth == last
            else f"keep if its chance is at least {pct(r.continuation_value, settings)}"
        )
        steps.append(
            Row(
                (
                    f"{_step_name(r.depth, r.hand_size)}: {rule}",
                    "",
                    pct(r.p_keep_given_reach, settings),
                    "",
                ),
                tuple(hands),
            )
        )
    best_plan = Row(("Best possible plan", "", "", pct(best.value, settings)), tuple(steps))
    return ResultView(
        headline,
        details,
        headers=("Step", "Get here", "Keep it", "Good game if kept"),
        rows=(your_plan, best_plan),
        legend=(
            ("Get here", "how often you mulligan this far"),
            (
                "Keep it",
                "how often you keep the hand at this step (best plan: how often that exact "
                "draw comes up)",
            ),
            ("Good game if kept", "your chance of a good game if you keep the hand"),
            (
                "Hands",
                "cards are grouped by the card types this question uses; 'other' is "
                "everything else",
            ),
        ),
    )


# ---------------------------------------------------------------------------------------
# Question 5: how many should I play?
# ---------------------------------------------------------------------------------------

Mode = Literal["one", "share"]
Aim = Literal["best", "target"]
_OBJECTIVES: dict[tuple[Mode, Aim], Objective] = {
    ("one", "best"): "max_probability",
    ("one", "target"): "min_count",
    ("share", "best"): "max_probability",
    ("share", "target"): "min_total",
}


@dataclass(frozen=True, slots=True)
class Vary:
    """A card type the program may change, between ``low`` and ``high`` copies."""

    card_type: str
    low: int
    high: int


@dataclass(frozen=True, slots=True)
class HowMany:
    """Question 5: choose card counts.

    ``mode`` says which counts change:

    * "one": ONE card type, within its range.
    * "share": several card types, using at most ``slots`` cards between them.

    ``aim`` says what counts as best:

    * "best": the highest chance (ties go to fewer cards). No target is needed.
    * "target": the fewest cards that reach ``target_percent``.
    """

    mode: Mode = "one"
    aim: Aim = "target"
    vary: tuple[Vary, ...] = (Vary("land", 14, 40),)
    target_percent: float = 90.0
    slots: int = 20
    goal: Goal = field(default_factory=lambda: Goal.all_of(Requirement("at least", 4, "land", 4)))


def how_many(
    deck: DeckSetup, sc: Scenario, q: HowMany, settings: Settings = Settings()
) -> ResultView:
    """Choose card counts; the other card types of step 1 stay as they are."""
    if deck.mode != "types":
        raise ValidationError("deck", "this question needs the deck described as card types")
    if not q.vary:
        raise ValidationError("card types to change", "choose at least one card type")
    if q.mode == "one" and len(q.vary) != 1:
        raise ValidationError("card types to change", "choose exactly one card type")
    names = [_clean(v.card_type) for v in q.vary]
    known = {_clean(t.name): t for t in deck.types}
    for v, n in zip(q.vary, names, strict=True):
        if n not in known:
            raise ValidationError("card types to change", f"'{v.card_type}' is not in your deck")
        if v.low > v.high:
            raise ValidationError("card types to change", f"'{v.card_type}': from is above to")
    fixed = tuple(
        (_clean(t.name), Category(t.count, frozenset(_clean(a) for a in t.also)))
        for t in deck.types
        if _clean(t.name) not in names
    )
    variables = tuple(
        Variable(n, v.low, v.high, frozenset(_clean(a) for a in known[n].also))
        for v, n in zip(q.vary, names, strict=True)
    )
    lows = sum(v.low for v in q.vary)
    room = deck.size - sum(c.count for _, c in fixed)
    if lows > room:
        raise ValidationError(
            "card types to change",
            f"the 'from' numbers add up to {lows} cards, but your other card types leave "
            f"room for only {room}",
        )
    if q.mode == "share" and q.slots < 0:
        raise ValidationError("cards allowed", "choose 0 or more cards")
    if q.mode == "share" and lows > q.slots:
        raise ValidationError(
            "cards allowed",
            f"the 'from' numbers add up to {lows} cards, more than the {q.slots} cards allowed",
        )
    if q.aim == "target" and not 0 < q.target_percent <= 100:
        raise ValidationError("target", "choose a target between 0 and 100 percent")
    target = Fraction(str(q.target_percent)) / 100
    problem = OptimizeProblem(
        deck_size=deck.size,
        variables=variables,
        query=Query(goal_condition(q.goal)),
        fixed=fixed,
        game=sc.game,
        mulligan=sc.mulligan,
        objective=_OBJECTIVES[q.mode, q.aim],
        target=target if q.aim == "target" else None,
        budget=q.slots if q.mode == "share" else None,
    )
    try:
        res = api.optimize(problem)
    except InfeasibleError:
        # The checks above leave only one way to fail: a target out of reach.
        raise ValidationError("target", _unreachable(q, names, target)) from None
    chosen = ", ".join(f"{c} {n}" for n, c in res.counts)
    good = describe_goal(q.goal)
    p = pct(res.probability, settings)
    details: list[str] = []
    if q.mode == "one":
        ((name, c),) = res.counts
        var = variables[0]
        if q.aim == "target":
            headline = (
                f"Play {c} {name}: you then have {good} in {p} of games, which reaches your "
                f"{pct(target)} target."
            )
        else:
            headline = (
                f"Play {c} {name}: you then have {good} in {p} of games, the best chance "
                f"from {var.lo} to {var.hi} {name}."
            )
        if c > var.lo:
            details.append(_one_fewer(problem, c, settings))
        if q.aim == "best" and c == var.hi < room:
            details.append(
                f"{c} is your 'to' number: a higher 'to' number might give a better chance."
            )
    elif q.aim == "best":
        headline = f"Best use of {q.slots} cards: {chosen}. You then have {good} in {p} of games."
    else:
        total = sum(c for _, c in res.counts)
        headline = f"The fewest cards that reach {pct(target)}: {total} ({chosen}), giving {p}."
    details.append(
        "This is guaranteed to be the best answer."
        if res.proven_optimal
        else "There were too many combinations to try them all, so this is the best one "
        "found by a smart search; it is very likely, but not guaranteed, to be the best."
    )
    rows = tuple(
        Row((", ".join(f"{c} {n}" for n, c in pt), pct(p, settings), in_words(p)))
        for pt, p in res.frontier[:12]
    )
    return ResultView(
        headline,
        tuple(details),
        headers=("Option tried", "Chance", "In words"),
        rows=rows,
        legend=(("Option tried", "the best options the program calculated, best first"),),
    )


def _unreachable(q: HowMany, names: list[str], target: Fraction) -> str:
    """Advice when no counts reach the target."""
    top = ", ".join(f"{v.high} {n}" for v, n in zip(q.vary, names, strict=True))
    rest = (
        "add the other card types your good game needs (card types not listed keep their "
        "step-1 counts)."
    )
    if q.mode == "one":
        return (
            f"{pct(target)} cannot be reached even with {top}. Raise the 'to' numbers, lower "
            f"the target, or {rest}"
        )
    return (
        f"{pct(target)} cannot be reached with at most {q.slots} cards (up to {top}). Raise "
        f"the 'to' numbers or the cards allowed, lower the target, or {rest}"
    )


def _one_fewer(problem: OptimizeProblem, c: int, settings: Settings) -> str:
    (var,) = problem.variables
    smaller = replace(
        problem,
        variables=(replace(var, lo=c - 1, hi=c - 1),),
        objective="max_probability",
        target=None,
    )
    p = api.optimize(smaller).probability
    return f"With {c - 1} {var.name} it would be {pct(p, settings)}."


# Used by the GUI's "type your own rule" helper.
def check_rule(text: str) -> str:
    """Validate a typed rule and return it in canonical form (raises ParseError)."""
    cond = parse_condition(text)
    if isinstance(cond, Const):
        return "true" if cond.value else "false"
    return api.format_condition(cond)


def keep_rule_words(m: MulliganSetup) -> str:
    """The keep rule in words.

    For example "keep a hand with 3 to 4 land, or with 2 land and 1 to 7 draw".
    """
    if not m.keep:
        return "always keep your first hand"

    def line(r: KeepRule) -> str:
        what = "cards" if r.card_type == ANY_CARD else r.card_type
        amount = str(r.low) if r.low == r.high else f"{r.low} to {r.high}"
        return f"{amount} {what}"

    kinds = [" and ".join(line(r) for r in rules) for rules in m.keep]
    return "keep a hand with " + ", or with ".join(kinds)


__all__ = [
    "ANY_CARD",
    "FORMATS",
    "KINDS",
    "Aim",
    "CardType",
    "DeckSetup",
    "Goal",
    "HowMany",
    "KeepRule",
    "MulliganSetup",
    "PlaySetup",
    "Requirement",
    "ResultView",
    "Row",
    "Settings",
    "Vary",
    "build_deck",
    "build_scenario",
    "chances",
    "check_rule",
    "describe_goal",
    "describe_scenario",
    "draws",
    "goal_as_text",
    "goal_condition",
    "how_many",
    "in_words",
    "keep_condition",
    "keep_rule_words",
    "mulligan_advice",
    "pct",
    "turn_by_turn",
    "turn_words",
    "type_names",
]
