/**
 * Everything the page says to explain itself, in one place so it can be reviewed for
 * plain language on its own (FR-96). Wording follows `mtgcalc_gui.help` so the desktop
 * and web apps explain things the same way.
 */

export const TITLE = "Card draw odds";

export const INTRO =
  "How often will a game go the way you want? Describe your deck and what a good game " +
  "looks like. The answer below updates as you type.";

export const STEPS = {
  deck: "1. Your deck",
  play: "2. How you play",
  goal: "3. Your question",
} as const;

export const HINTS = {
  format:
    "Quick start: sets the deck size and who draws first for that kind of game. Your card types stay as they are, so check their numbers.",
  deckSize:
    "How many cards you shuffle at the start. For Commander use 99 (your commander starts outside the deck).",
  types:
    "List the kinds of cards you care about and how many you play. Every card you don't list counts as “other cards”.",
  typeName: "A name you choose, like land, ramp or removal, or one card such as sol ring.",
  typeCount: "How many cards of this type are in the deck.",
  typeAlso: "Optional. Other types these cards also count as, separated by commas.",
  typeAlsoLong:
    "Count every card once. A card that is two things at once gets its own row: for 2 cards that are both a land and a ramp card, add a row “land and ramp”, 2, also counts as “land, ramp”, and leave those 2 out of your land and ramp numbers.",
  decklist:
    "Paste a list with one card per line, like “4 Lightning Bolt”. Add #tags after a name to group cards, like “1 Sol Ring #ramp”; the tags become the card types you can ask about. Moxfield (Export > Copy as plain text) and Archidekt lists work as they are.",
  rule: "Write a good game as a rule. Lines without @ are checked in the opening hand.",
  goFirst: "Going first, you skip your first draw. In multiplayer games like Commander, nobody skips it.",
  draws: "Normally 1. Use 2 if something lets you draw an extra card every turn.",
  mulligans:
    "Shuffle away a bad opening hand and draw 7 new cards, then put 1 card on the bottom for each mulligan you have taken (the London mulligan).",
  keep: "A hand is kept if it fits any one kind of hand below, and it fits a kind when every line is true. Any other hand is mulliganed. The hand after your last mulligan is always kept.",
  protect:
    "Top line first. “Up to 3” means keep at most 3 of them safe; extras can go to the bottom. Cards not listed go to the bottom before anything listed.",
  maxMulligans: "You always keep the hand after the last one.",
  free: "Multiplayer rule: your first mulligan is free (you still keep 7 cards).",
  vary: "The calculator tries every count in these ranges. Card types you don't list keep their numbers from step 1.",
  slots: "The most cards these card types may use between them.",
  aim: "“The best chance” needs no target: the calculator finds the counts with the highest chance. “A target chance” finds the fewest cards that reach the chance you choose.",
  target: "The chance you want to reach, in percent, like 90.",
  goal: "Describe a good game, one line per thing you want. Add more lines with the button.",
  combine: "“All” means every line must happen. “Any” means at least one line is enough.",
  turn: "“By turn 3” means after you draw your card for turn 3. The opening hand is the 7 cards you start with.",
} as const;

/** The rule language in brief (from the desktop app's "Writing your own rules"). */
export const RULE_GUIDE: readonly (readonly [string, string])[] = [
  ["land >= 3", "at least 3 land (also >, <=, <, ==, !=)"],
  ["land in 2..4", "between 2 and 4 land"],
  ['card:"Sol Ring" >= 1', "a specific card"],
  ['tag:"mana rock" >= 1', "a card type whose name has spaces"],
  ["any(ramp, draw) >= 2", "2 cards that are ramp or draw"],
  ["all(land, ramp) >= 1", "a card that is both land and ramp"],
  ["none(land) >= 4", "4 cards that are not land"],
  ["everything >= 9", "any 9 cards"],
  ["land >= 3 @T3", "by turn 3 (lines without @ are checked in the opening hand)"],
  ["(land >= 3 AND ramp >= 1) @T2", "several things by turn 2"],
  ["A AND B, A OR B, NOT A, A XOR B", "both, either, not, exactly one of them"],
  ["A -> B", "if A then B"],
  ["atleast(2, A, B, C), exactly(1, A, B, C)", "how many of the parts must hold"],
  ["assign(land >= 3, ramp >= 1)", "3 land and 1 ramp from different cards"],
];

export const STATUS = {
  first: "Working out your first answer…",
  updating: "Updating…",
  toUpdate: "To update the answer:",
  finishTyping: "Finish typing to update the answer.",
  pressRun: "Press “Find the best counts” to work it out (it can take a few seconds).",
  searching: "Trying different counts… this can take a few seconds.",
  outOfDate: "Out of date: this answer is for an earlier version of your setup.",
} as const;

export const ABOUT =
  "Every answer is worked out exactly from the numbers in your deck: nothing is guessed or " +
  "simulated. Everything runs in your browser; nothing you type is sent anywhere.";
