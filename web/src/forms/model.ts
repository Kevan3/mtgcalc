/**
 * What the player types (raw form state) and what it means once checked (setup).
 *
 * The setup types mirror `mtgcalc_gui.forms` (DeckSetup, PlaySetup, Goal) so the two
 * apps describe a game the same way; tests/web/make_fixtures.py writes them in this
 * shape for the parity tests.
 */

/** "Any card" in the card-type lists: every card in the deck. */
export const ANY_CARD = "any card";
/** Name of the cards that belong to no listed type (as Python's Deck.from_counts). */
export const FILLER = "(other)";

export const KINDS = ["at least", "at most", "exactly", "none"] as const;
export type Kind = (typeof KINDS)[number];
export type Combine = "all" | "any";

// ---------------------------------------------------------------------------------
// Checked setup (numbers are numbers, names are cleaned)
// ---------------------------------------------------------------------------------

export interface CardType {
  readonly name: string;
  readonly count: number;
  readonly also: readonly string[];
}

export interface DeckSetup {
  readonly size: number;
  readonly types: readonly CardType[];
}

export interface PlaySetup {
  readonly goFirst: boolean;
  readonly drawsPerTurn: number;
}

export interface Requirement {
  readonly kind: Kind;
  readonly amount: number;
  readonly cardType: string;
  readonly turn: number;
}

export interface Goal {
  readonly requirements: readonly Requirement[];
  readonly combine: Combine;
  /** A typed rule, which replaces the lines (Python's `Goal.custom`). */
  readonly rule?: TypedRule;
}

/** A typed rule as written, and as the core read it (a `to_dict` condition). */
export interface TypedRule {
  readonly text: string;
  readonly condition: unknown;
}

/** A pasted decklist as written, and what the core read from it. */
export interface Decklist {
  readonly text: string;
  /** Cards in the library (the part that is shuffled). */
  readonly size: number;
  /** Library cards per tag, sorted by tag (Python's `Deck.tag_counts`). */
  readonly tags: readonly (readonly [string, number])[];
  /** Cards in the command zone. */
  readonly commanders: readonly string[];
}

/** The question asked (the desktop app's question tabs, port stages 1 and 3). */
export type QuestionKind = "chances" | "draws" | "turns" | "mulligan" | "howmany";

/** "How many should I play?": change one card type, or share cards between several. */
export type HowManyMode = "one" | "share";

/** What counts as best: the highest chance (no target), or the fewest cards reaching a target. */
export type HowManyAim = "best" | "target";

export type Question =
  | { readonly kind: "chances" }
  | {
      readonly kind: "howmany";
      readonly mode: HowManyMode;
      readonly aim: HowManyAim;
      /** The card types to change: (name, from, to). */
      readonly vary: readonly (readonly [string, number, number])[];
      /** The target percentage as typed (exact decimal), for the "target" aim. */
      readonly target: string;
      /** The most cards the types may use between them, for "share". */
      readonly slots: number;
      /** Cards left in the deck after the card types that keep their counts. */
      readonly room: number;
    }
  | { readonly kind: "mulligan" }
  | { readonly kind: "draws"; readonly cardType: string; readonly lastTurn: number }
  | { readonly kind: "turns"; readonly lastTurn: number };

/** Mulligan settings, checked (Python's `MulliganSetup` when enabled). */
export interface MulliganSetup {
  /** "" means "always keep the first hand". */
  readonly keepType: string;
  readonly keepMin: number;
  readonly keepMax: number;
  /** Card types to keep first when putting cards on the bottom, and up to how many. */
  readonly protect: readonly (readonly [string, number])[];
  readonly maxMulligans: number;
  readonly freeFirst: boolean;
}

export interface Setup {
  /** With a decklist, `deck.size` is its library size and `deck.types` is empty. */
  readonly deck: DeckSetup;
  readonly play: PlaySetup;
  readonly goal: Goal;
  readonly decklist?: Decklist;
  /** Absent means "chances" (the golden cases of increment 1 have no question). */
  readonly question?: Question;
  /** Absent means no mulligans. */
  readonly mulligan?: MulliganSetup;
}

// ---------------------------------------------------------------------------------
// Raw form state (strings, exactly as typed)
// ---------------------------------------------------------------------------------

export interface TypeRow {
  readonly id: string;
  readonly name: string;
  readonly count: string;
  readonly also: string;
}

export interface GoalRow {
  readonly id: string;
  readonly kind: Kind;
  readonly amount: string;
  readonly cardType: string;
  readonly turn: string;
}

export type DeckMode = "types" | "list";

export interface VaryRow {
  readonly id: string;
  readonly cardType: string;
  readonly low: string;
  readonly high: string;
}

export interface ProtectRow {
  readonly id: string;
  readonly cardType: string;
  readonly upTo: string;
}

export interface FormState {
  /** "types": the card-type table; "list": a pasted decklist. */
  readonly deckMode: DeckMode;
  readonly deckSize: string;
  readonly types: readonly TypeRow[];
  readonly decklist: string;
  readonly goFirst: boolean;
  readonly drawsPerTurn: string;
  readonly goal: readonly GoalRow[];
  readonly combine: Combine;
  /** Write my own rule instead of the lines. */
  readonly useRule: boolean;
  readonly rule: string;
  readonly question: QuestionKind;
  /** "How many will I draw?": which card type. */
  readonly drawsType: string;
  /** "How many will I draw?" and "Turn by turn": up to which turn. */
  readonly lastTurn: string;
  /** Step 2, mulligans (the London mulligan). */
  readonly mulligans: boolean;
  readonly keepType: string;
  readonly keepMin: string;
  readonly keepMax: string;
  readonly protect: readonly ProtectRow[];
  readonly maxMulligans: string;
  readonly freeFirst: boolean;
  /** "How many should I play?". */
  readonly hmMode: HowManyMode;
  readonly hmAim: HowManyAim;
  readonly hmVary: readonly VaryRow[];
  readonly hmTarget: string;
  readonly hmSlots: string;
}

/** Format presets (as the desktop app): cards in the library, and who draws first. */
export const FORMATS = {
  "60-card": { size: 60, goFirst: true, freeFirst: false },
  "40-card Limited": { size: 40, goFirst: true, freeFirst: false },
  Commander: { size: 99, goFirst: false, freeFirst: true },
} as const;

/** Most mulligans the form accepts (a 7-card draw allows 7 bottomed cards at most). */
export const MAX_MULLIGANS = 6;
export type FormatName = keyof typeof FORMATS;

/** Turns offered in the "when" lists. Later turns are rarely meaningful. */
export const MAX_TURN = 20;
/** Largest deck the form accepts (the engine itself allows 65,535 cards). */
export const MAX_DECK = 1000;
/** Most cards drawn per turn the form accepts. */
export const MAX_DRAWS = 10;
/** Cards in the opening hand (mulligans are not part of the web app yet). */
export const HAND_SIZE = 7;
