"""Everything the GUI says to explain itself: tooltips, page intros, help pages, examples.

Written for players who have never used the tool. Kept apart from the widgets so the
wording can be reviewed on its own (and reused by the future web app).
"""

from __future__ import annotations

from dataclasses import dataclass

from mtgcalc_gui.forms import (
    CardType,
    DeckSetup,
    Goal,
    KeepRule,
    MulliganSetup,
    PlaySetup,
    Requirement,
)

#: Hover text for inputs, keyed by a short id used in app.py.
TIPS: dict[str, str] = {
    "format": "Quick start: sets the deck size and the usual rules for that format.",
    "size": "How many cards you shuffle at the start. For Commander use 99 (your "
    "commander starts outside the deck).",
    "mode_types": "Describe your deck as a few card types, e.g. '24 land, 6 removal'. "
    "Best for 'what if' questions.",
    "mode_list": "Use a real deck: paste a decklist, open a file, or import a deck link. "
    "Add #tags after a card name to group it, e.g. '4 Lightning Bolt #removal'.",
    "link": "Paste a link to a public Archidekt deck and press Import: the cards and their "
    "categories (as #tags) appear in the box below, ready to edit.\nMoxfield blocks "
    "other programs, so for Moxfield use Export > Copy as plain text and paste that.",
    "type_name": "A name for a kind of card you care about, e.g. land, ramp, removal, or a "
    "specific card such as 'sol ring'.",
    "type_count": "How many cards of this type are in the deck.",
    "type_also": "Optional. Other types these cards ALSO count as, separated by commas.\n"
    "Example: card type 'mdfc', how many 2, also counts as 'land, removal' - those 2 "
    "cards then count as mdfc, as land and as removal.",
    "go_first": "Going first, you skip your first draw. In multiplayer games (like "
    "Commander) nobody skips it.",
    "draws": "Cards you draw each turn. Normally 1.",
    "extra": "Cards you draw on top of your normal draw, e.g. turn 3: 2 extra for a "
    "draw-two spell.",
    "mull_on": "Allow redrawing a bad opening hand (the London mulligan: draw 7 new "
    "cards, then put 1 on the bottom for each mulligan you have taken).",
    "keep": "Which opening hands you are happy to keep. A hand is kept if it fits any one "
    "kind of hand, and it fits a kind when every line of that kind is true. Any other hand "
    "is mulliganed. With no kinds of hand, you keep every hand.",
    "protect": "When you put cards on the bottom, these are kept first, top line first. "
    "'up to 3' means keep at most 3 of them safe; extras can go to the bottom. Cards "
    "not listed go to the bottom before anything listed.",
    "max_mull": "The most mulligans you will take. You always keep the hand after the last one.",
    "free": "Multiplayer rule: your first mulligan is free (you still keep 7 cards).",
    "goal": "Describe a good game, one line per requirement. Add lines for more requirements.",
    "combine": "'All' means every line must be true. 'Any' means at least one line.",
    "custom": "For experienced users: type a rule directly (see Help > Writing your own "
    "rules). It replaces the lines above.",
    "only_if": "Only count the games where this is true. Example: 'chance of casting my "
    "3-drop, in the games where I have 3 lands'.",
    "last_turn": "Show every turn from the opening hand up to this turn.",
    "card_type": "Which kind of card to count.",
    "hm_mode": "What to ask the program to work out.",
    "hm_vary": "The card types the program may change, and the range of counts to try. "
    "All other card types keep their counts from step 1.",
    "hm_aim": "'The best chance' needs no target: the program finds the counts that give the "
    "highest chance. 'A target chance' finds the fewest cards that reach the chance you choose.",
    "hm_target": "The chance you want to reach, in percent.",
    "hm_slots": "The most cards these card types may use between them.",
}

#: Short introductions at the top of each question page.
INTROS: dict[str, str] = {
    "chances": "How often will a game go the way you want? Describe a good game below "
    "and press Answer.",
    "draws": "How many cards of one type will you have seen by each turn?",
    "turns": "How does your chance improve turn by turn? (The turns in the lines below "
    "are ignored; every turn is shown instead.)",
    "mulligan": "Is your mulligan plan a good one? Compares it with never mulliganing "
    "and with the best possible plan, and shows which hands the best plan keeps. "
    "Turn on mulligans in step 2 first.",
    "howmany": "Let the program choose how many cards to play. It tries different "
    "counts for the card types you pick and keeps everything else from step 1.",
}

GETTING_STARTED = """\
GETTING STARTED

This tool tells you how likely things are to happen in your games, for example
"how often will I have 3 lands by turn 3?". Every answer is calculated exactly
from the numbers in your deck - nothing is guessed or simulated (unless you ask
for a simulation in Settings).

1. Describe your deck (left, step 1)
   Click a format button, then list the kinds of cards you care about with how
   many you play, e.g. "land 24" and "removal 6". Everything you don't list is
   counted as "other cards". A card can count as more than one type: a land that
   can also be cast as removal goes in "also counts as".
   Or choose "Paste a decklist" and use #tags, e.g. "4 Lightning Bolt #removal".

2. Say how you play (left, step 2)
   Do you go first? How many cards do you draw each turn? Do you mulligan bad
   hands? If you mulligan, say which hands you keep and which cards you would
   rather keep when you have to put cards on the bottom.

3. Ask a question (right)
   Pick a tab:
     What are my chances?   - how often a game goes well
     How many will I draw?  - how many of one card type you'll have seen
     Turn by turn           - how a chance grows from turn to turn
     Should I mulligan?     - how good your mulligan plan is
     How many should I play? - let the program pick the card counts
   Build "a good game" from simple lines like
       [at least] [3] [land] [by turn 3]
   then press Answer. The first sentence of the answer is the important part;
   the table underneath has the details.

Tips
  - "By turn 3" means after you draw on turn 3. "Opening hand" means the 7 cards
    you keep before your first turn.
  - Hover over any field for an explanation.
  - Examples (menu) fills everything in so you can see how it works.
"""

WORDS = """\
WHAT THE WORDS MEAN

Card type        A kind of card you care about (land, ramp, removal...). You name
                 them yourself.
Also counts as   A card can be several types at once. It then counts for each of
                 them, e.g. a land/removal card counts as a land AND as removal.
Other cards      Every card you didn't give a type.
Opening hand     The 7 cards you start with (after any mulligans).
By turn 3        After drawing your card for turn 3.
Going first      You skip the draw on your first turn.

Mulligan         Shuffling a bad opening hand away and drawing 7 new cards. After
                 each mulligan you put 1 card on the bottom of your deck (the first
                 one is free in multiplayer).
Keep first       Which cards you protect when putting cards on the bottom.
Good game        Whatever you describe in the question - the thing you want to
                 happen.
Never mulliganing  Your chance if you always kept your first 7 cards.
Best possible plan The highest chance any keep-or-mulligan choice could give you,
                 with your "keep first" order.

Guaranteed best  The program tried every option (or proved the rest can't win).
Best found       There were too many options to try them all; the program searched
                 smartly, so the answer is very likely - but not certainly - the best.
Simulated        In Settings you can choose to simulate games instead of calculating
                 exactly. Answers then come with a range, e.g. "between 47% and 48%".
"""

RULES = """\
WRITING YOUR OWN RULES (for experienced users)

Instead of building a good game from lines, you can type a rule. Tick
"Type my own rule" under the lines.

Counting cards
  land >= 3              at least 3 land      (also  >  <=  <  ==  !=)
  land in 2..4           between 2 and 4
  card:"Sol Ring" >= 1   a specific card
  tag:"mana rock" >= 1   a type whose name has spaces
  any(ramp, draw) >= 2   2 cards that are ramp OR draw
  all(land, ramp) >= 1   a card that is land AND ramp
  none(land) >= 4        4 cards that are not land
  everything >= 9        any 9 cards

When
  land >= 3 @T3          by turn 3              land >= 2 @T0   opening hand
  (land >= 3 AND ramp >= 1) @T2                 several things by turn 2
  Lines without @ are checked in the opening hand.

Combining
  A AND B    A OR B    NOT A    A XOR B (exactly one of them)
  A -> B     (if A then B)
  atleast(2, A, B, C)    exactly(1, A, B, C)

Each card used once
  assign(land >= 3, ramp >= 1)   3 land and 1 ramp from DIFFERENT cards
  (normally a land/ramp card would count for both)
"""


@dataclass(frozen=True, slots=True)
class Example:
    """A complete filled-in setup for the Examples menu."""

    deck: DeckSetup
    play: PlaySetup
    mulligan: MulliganSetup
    goal: Goal


_LANDS_AND_REMOVAL = Goal(
    (Requirement("at least", 3, "land", 3), Requirement("at least", 1, "removal", 3))
)

EXAMPLES: dict[str, Example] = {
    "60-card deck: lands and removal by turn 3": Example(
        DeckSetup(60, (CardType("land", 24), CardType("removal", 6))),
        PlaySetup(),
        MulliganSetup(),
        _LANDS_AND_REMOVAL,
    ),
    "60-card deck with mulligans": Example(
        DeckSetup(60, (CardType("land", 24), CardType("removal", 6))),
        PlaySetup(),
        MulliganSetup(enabled=True, protect=(("land", 3), ("removal", 1))),
        _LANDS_AND_REMOVAL,
    ),
    "40-card Limited: lands and a bomb": Example(
        DeckSetup(40, (CardType("land", 17), CardType("bomb", 1), CardType("removal", 4))),
        PlaySetup(),
        MulliganSetup(),
        Goal((Requirement("at least", 4, "land", 4), Requirement("at least", 1, "bomb", 6))),
    ),
    "Commander: ramp on turn 2": Example(
        DeckSetup(
            99,
            (
                CardType("land", 35),
                CardType("mdfc", 2, ("land", "removal")),
                CardType("ramp", 12),
                CardType("draw", 10),
                CardType("removal", 8),
            ),
        ),
        PlaySetup(go_first=False),
        MulliganSetup(
            enabled=True,
            keep=(
                (KeepRule("land", 3, 5),),
                (KeepRule("land", 2, 2), KeepRule("ramp", 1, 7)),
            ),
            protect=(("land", 3), ("ramp", 1), ("draw", 1)),
            free_first=True,
        ),
        Goal((Requirement("at least", 2, "land", 2), Requirement("at least", 1, "ramp", 2))),
    ),
    "Pasted decklist with #tags": Example(
        DeckSetup(
            mode="decklist",
            decklist="Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n36 Forest #land\n"
            "1 Sol Ring #ramp\n9 Arcane Signet #ramp\n10 Divination #draw\n43 Bear\n",
        ),
        PlaySetup(go_first=False),
        MulliganSetup(),
        Goal((Requirement("at least", 1, "ramp", 2),)),
    ),
}
