/**
 * Checks the raw form and turns it into a setup, with plain-language problems per
 * field (FR-94). The engine validates again (with Python's rules); this layer exists
 * so a player is told *what to change, where*, in words they understand.
 */
import {
  ANY_CARD,
  FILLER,
  HAND_SIZE,
  MAX_DECK,
  MAX_DRAWS,
  MAX_MULLIGANS,
  MAX_TURN,
  type CardType,
  type Decklist,
  type FormState,
  type Goal,
  type KeepRule,
  type MulliganSetup,
  type Question,
  type PlaySetup,
  type Requirement,
  type Setup,
  type TypedRule,
} from "./model.ts";
import type { Core } from "../engine/core.ts";
import { readDecklist, readRule } from "./text.ts";

/** Where a problem is: a whole section, or one input of one row. */
export type FieldId =
  | "deckSize"
  | "drawsPerTurn"
  | "types"
  | "goal"
  | "decklist"
  | "rule"
  | "drawsType"
  | "lastTurn"
  | "mulligans"
  | "maxMulligans"
  | "protect"
  | "howmany"
  | "hmTarget"
  | "hmSlots"
  | `vary:${string}:${"cardType" | "range"}`
  | `protect:${string}:${"cardType" | "upTo"}`
  | `keep:${string}:${"cardType" | "range"}`
  | `type:${string}:${"name" | "count" | "also"}`
  | `goal:${string}:${"amount" | "cardType" | "turn"}`;

export interface Issue {
  readonly field: FieldId;
  readonly message: string;
}

/** Something worth knowing that does not stop the answer (e.g. a likely typo). */
export type Note = Issue;

export type Parsed =
  | { readonly ok: true; readonly setup: Setup; readonly notes: readonly Note[] }
  | { readonly ok: false; readonly issues: readonly Issue[]; readonly notes: readonly Note[] };

/**
 * Card-type names compare case-insensitively with whitespace collapsed (Python:
 * `" ".join(s.split()).casefold()`). The Rust core applies Python's exact Unicode
 * rules; this simpler form agrees on everything a keyboard normally produces, and only
 * decides duplicates and drop-down entries.
 */
export function cleanName(name: string): string {
  return name.trim().split(/\s+/u).join(" ").toLowerCase();
}

/** The "also counts as" box: comma-separated names, cleaned, blanks dropped. */
export function splitAlso(text: string): string[] {
  return text
    .split(",")
    .map(cleanName)
    .filter((n) => n !== "");
}

/** A whole number written with digits only (surrounding spaces allowed). */
export function parseWhole(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/u.test(t)) return null;
  const n = Number(t);
  return Number.isSafeInteger(n) ? n : null;
}

/** Cards drawn after the opening hand, through the draw step of `turn` (ADR-0004). */
export function drawsThrough(play: PlaySetup, turn: number): number {
  if (turn <= 0) return 0;
  return turn * play.drawsPerTurn - (play.goFirst ? play.drawsPerTurn : 0);
}

/** The latest turn the deck has cards for (at most MAX_TURN). */
export function lastPlayableTurn(play: PlaySetup, deckSize: number): number {
  let t = 0;
  while (t < MAX_TURN && HAND_SIZE + drawsThrough(play, t + 1) <= deckSize) t += 1;
  return t;
}

/** A name as the player wrote it (spaces tidied, capitals kept), for display. */
export function displayName(name: string): string {
  return name.trim().split(/\s+/u).join(" ");
}

/**
 * How to show each (cleaned) card-type name: as the player first wrote it, so "Lightning
 * Bolt" stays "Lightning Bolt" in the lists and the answer.
 */
export function typeLabels(types: readonly { name: string; also: string }[]): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const t of types) {
    const written = [t.name, ...t.also.split(",")].map(displayName).filter((n) => n !== "");
    for (const w of written) labels[cleanName(w)] ??= w;
  }
  return labels;
}

/** Names offered in the card-type lists: types, their "also" names, then any card. */
export function typeNames(types: readonly { name: string; also: string }[]): string[] {
  const names: string[] = [];
  for (const t of types) {
    for (const n of [cleanName(t.name), ...splitAlso(t.also)]) {
      if (n !== "" && !names.includes(n)) names.push(n);
    }
  }
  return [...names, ANY_CARD];
}

const RESERVED = new Set([ANY_CARD, FILLER]);

interface Collector {
  readonly problem: (field: FieldId, message: string) => void;
  readonly note: (field: FieldId, message: string) => void;
}

/** Step 1 with the card-type table: the deck size and the types. */
function typesDeck(form: FormState, c: Collector): { size: number | null; types: CardType[] } {
  const size = parseWhole(form.deckSize);
  if (form.deckSize.trim() === "") {
    c.problem("deckSize", "Enter how many cards are in your deck.");
  } else if (size === null) {
    c.problem("deckSize", "Use a whole number, like 60.");
  } else if (size < HAND_SIZE) {
    c.problem("deckSize", `A deck needs at least ${HAND_SIZE} cards, enough for an opening hand.`);
  } else if (size > MAX_DECK) {
    c.problem("deckSize", `Use ${MAX_DECK} cards or fewer.`);
  }
  const types: CardType[] = [];
  const seen = new Set<string>();
  for (const row of form.types) {
    const name = cleanName(row.name);
    if (name === "") {
      c.problem(`type:${row.id}:name`, "Give this card type a name, like “land”.");
    } else if (RESERVED.has(name)) {
      c.problem(`type:${row.id}:name`, `“${name}” is a name the calculator uses. Pick another.`);
    } else if (seen.has(name)) {
      c.problem(`type:${row.id}:name`, `You already have a card type called “${name}”.`);
    }
    seen.add(name);
    const count = parseWhole(row.count);
    if (count === null) {
      c.problem(`type:${row.id}:count`, "Use a whole number, 0 or more.");
    }
    const also = splitAlso(row.also);
    const reserved = also.find((a) => RESERVED.has(a));
    if (reserved !== undefined) {
      c.problem(`type:${row.id}:also`, `“${reserved}” is a name the calculator uses. Pick another.`);
    }
    types.push({ name, count: count ?? 0, also });
  }
  // "Also counts as" names that are not card types are allowed (they become new types),
  // but they are often typos, e.g. "land ramp" for "land, ramp".
  const typeSet = new Set(types.map((t) => t.name));
  for (const [i, row] of form.types.entries()) {
    const strangers = (types[i]?.also ?? []).filter((a) => !typeSet.has(a));
    if (strangers.length > 0) {
      const list = strangers.map((a) => `“${a}”`).join(" and ");
      c.note(
        `type:${row.id}:also`,
        `${list} ${strangers.length === 1 ? "is" : "are"} not in your list of card types, so ` +
          `${strangers.length === 1 ? "it becomes a new type" : "they become new types"}. ` +
          "To use several types, separate them with commas.",
      );
    }
  }
  const total = types.reduce((sum, t) => sum + t.count, 0);
  if (size !== null && total > size) {
    c.problem(
      "types",
      `Your card types add up to ${total} cards, but your deck has ${size}. ` +
        "Lower a number or raise the deck size.",
    );
  }
  return { size, types };
}

/** The names a goal line may pick (types and their "also" names, or decklist tags). */
export function offeredNames(form: FormState, decklist: Decklist | undefined): string[] {
  if (form.deckMode === "list") return [...(decklist?.tags.map(([t]) => t) ?? []), ANY_CARD];
  return typeNames(form.types);
}

/** "Up to which turn?" for the table questions. */
function lastTurnOf(form: FormState, last: number, c: Collector): number {
  const turn = parseWhole(form.lastTurn);
  if (turn === null || turn > MAX_TURN) {
    c.problem("lastTurn", "Pick a turn from the list.");
  } else if (turn > last) {
    c.problem("lastTurn", `Your deck runs out of cards after turn ${last}. Pick turn ${last} or earlier.`);
  }
  return turn ?? 0;
}

/** Step 3 with goal lines; `checkTurns` is false for "Turn by turn" (it ignores them). */
function goalLines(
  form: FormState,
  offered: readonly string[],
  last: number,
  c: Collector,
  checkTurns = true,
): Requirement[] {
  if (form.goal.length === 0) {
    c.problem("goal", "Add a line to say what a good game looks like.");
  }
  const requirements: Requirement[] = [];
  for (const row of form.goal) {
    const amount = row.kind === "none" ? 0 : parseWhole(row.amount);
    if (amount === null) {
      c.problem(`goal:${row.id}:amount`, "Use a whole number, 0 or more.");
    }
    if (!offered.includes(row.cardType)) {
      c.problem(`goal:${row.id}:cardType`, "Pick a card type from the list.");
    }
    const turn = parseWhole(row.turn);
    if (!checkTurns) {
      // "Turn by turn" asks about every turn, so a line's own turn does not matter.
    } else if (turn === null || turn > MAX_TURN) {
      c.problem(`goal:${row.id}:turn`, "Pick a turn from the list.");
    } else if (turn > last) {
      c.problem(
        `goal:${row.id}:turn`,
        `Your deck runs out of cards after turn ${last}. Pick turn ${last} or earlier.`,
      );
    }
    requirements.push({ kind: row.kind, amount: amount ?? 0, cardType: row.cardType, turn: turn ?? 0 });
  }
  return requirements;
}

/** Step 2, mulligans (Python's `build_scenario` checks, in plain words). */
function mulliganSetup(form: FormState, offered: readonly string[], c: Collector): MulliganSetup {
  const keep = form.keep.map((group) =>
    group.rules.map((row): KeepRule => {
      if (!offered.includes(row.cardType)) {
        c.problem(`keep:${row.id}:cardType`, "Pick a card type for the hands you keep.");
      }
      const min = parseWhole(row.min);
      const max = parseWhole(row.max);
      if (min === null || max === null) c.problem(`keep:${row.id}:range`, "Use whole numbers, like 2 to 5.");
      else if (min > max) c.problem(`keep:${row.id}:range`, "The first number is bigger than the second.");
      return { cardType: row.cardType, min: min ?? 0, max: max ?? 0 };
    }),
  );
  if (form.protect.length === 0) {
    c.problem("protect", "Add a card type to keep first when putting cards on the bottom.");
  }
  const protect: (readonly [string, number])[] = [];
  for (const row of form.protect) {
    if (!offered.includes(row.cardType)) {
      c.problem(`protect:${row.id}:cardType`, "Pick a card type from the list.");
    } else if (protect.some(([t]) => t === row.cardType)) {
      c.problem(`protect:${row.id}:cardType`, "This card type is already in the list.");
    }
    const upTo = parseWhole(row.upTo);
    if (upTo === null) c.problem(`protect:${row.id}:upTo`, "Use a whole number, 0 or more.");
    protect.push([row.cardType, upTo ?? 0]);
  }
  const maxMulligans = parseWhole(form.maxMulligans);
  if (maxMulligans === null || maxMulligans > MAX_MULLIGANS) {
    c.problem("maxMulligans", `Use a whole number from 0 to ${MAX_MULLIGANS}.`);
  }
  return {
    keep,
    protect,
    maxMulligans: maxMulligans ?? 0,
    freeFirst: form.freeFirst,
  };
}

/** An exact decimal percentage such as "90" or "92.5" (Python's `Fraction(str(x))`). */
export function parsePercent(text: string): string | null {
  const t = text.trim().replace(/%$/u, "").trim();
  return /^\d+(\.\d+)?$/u.test(t) ? t : null;
}

/** "How many should I play?" (Python's `how_many` checks, in plain words). */
function howMany(form: FormState, c: Collector): Question {
  if (form.deckMode !== "types") {
    c.problem("howmany", "This question needs your deck described as card types (step 1).");
  }
  const typeNamesOnly = form.types.map((t) => cleanName(t.name));
  const size = parseWhole(form.deckSize);
  const rows = form.hmMode === "one" ? form.hmVary.slice(0, 1) : form.hmVary;
  if (rows.length === 0) c.problem("howmany", "Choose at least one card type to change.");
  const vary: (readonly [string, number, number])[] = [];
  for (const row of rows) {
    if (!typeNamesOnly.includes(row.cardType)) {
      c.problem(`vary:${row.id}:cardType`, "Pick one of your card types.");
    } else if (vary.some(([n]) => n === row.cardType)) {
      c.problem(`vary:${row.id}:cardType`, "This card type is already in the list.");
    }
    const low = parseWhole(row.low);
    const high = parseWhole(row.high);
    if (low === null || high === null) c.problem(`vary:${row.id}:range`, "Use whole numbers, like 14 to 30.");
    else if (low > high) c.problem(`vary:${row.id}:range`, "The first number is bigger than the second.");
    else if (size !== null && high > size) {
      c.problem(`vary:${row.id}:range`, `This can't be more than the ${String(size)} cards in your deck.`);
    }
    vary.push([row.cardType, low ?? 0, high ?? 0]);
  }
  // The 'from' numbers must fit next to the card types that keep their counts.
  const lows = vary.reduce((sum, [, low]) => sum + low, 0);
  const others = form.types
    .filter((t) => !vary.some(([n]) => n === cleanName(t.name)))
    .map((t) => parseWhole(t.count));
  const room =
    size === null || others.includes(null) ? null : size - others.reduce<number>((s, n) => s + (n ?? 0), 0);
  if (room !== null) {
    if (lows > room) {
      c.problem(
        "howmany",
        `The 'from' numbers add up to ${String(lows)} cards, but your other card types leave room for only ${String(room)}.`,
      );
    }
  }
  const target = parsePercent(form.hmTarget);
  if (form.hmAim === "target" && (target === null || Number(target) <= 0 || Number(target) > 100)) {
    c.problem("hmTarget", "Choose a target above 0 and up to 100 percent, like 90.");
  }
  const slots = parseWhole(form.hmSlots);
  if (form.hmMode === "share") {
    if (slots === null) c.problem("hmSlots", "Use a whole number, like 20.");
    else if (size !== null && slots > size) {
      c.problem("hmSlots", `This can't be more than the ${String(size)} cards in your deck.`);
    } else if (lows > slots) {
      c.problem(
        "hmSlots",
        `The 'from' numbers add up to ${String(lows)} cards, more than the ${String(slots)} allowed.`,
      );
    }
  }
  return {
    kind: "howmany",
    mode: form.hmMode,
    aim: form.hmAim,
    vary,
    target: target ?? "0",
    slots: slots ?? 0,
    room: room ?? 0,
  };
}

/**
 * Checks the whole form. `core` reads pasted decklists and typed rules (instantly, on
 * the page); the card-type table and goal lines need no core.
 */
export function parseForm(form: FormState, core: Core): Parsed {
  const issues: Issue[] = [];
  const notes: Note[] = [];
  const c: Collector = {
    problem: (field, message) => issues.push({ field, message }),
    note: (field, message) => notes.push({ field, message }),
  };

  // Step 1: the deck.
  let size: number | null;
  let types: CardType[] = [];
  let decklist: Decklist | undefined;
  if (form.deckMode === "list") {
    const read = readDecklist(core, form.decklist);
    if (read.ok) {
      decklist = read.value;
      size = decklist.size;
      if (size < HAND_SIZE) {
        c.problem(
          "decklist",
          `Your deck has ${size} cards; it needs at least ${HAND_SIZE} for an opening hand.`,
        );
      }
    } else {
      c.problem("decklist", read.message);
      size = null;
    }
  } else {
    ({ size, types } = typesDeck(form, c));
  }

  // Step 2: how you play.
  const draws = parseWhole(form.drawsPerTurn);
  if (draws === null || draws > MAX_DRAWS) {
    c.problem("drawsPerTurn", `Use a whole number from 0 to ${MAX_DRAWS} (usually 1).`);
  }
  const play: PlaySetup = { goFirst: form.goFirst, drawsPerTurn: draws ?? 1 };

  // Step 3: the question, and a good game as lines or as a typed rule.
  const last = size !== null && draws !== null ? lastPlayableTurn(play, size) : MAX_TURN;
  const offered = offeredNames(form, decklist);
  const mulligan = form.mulligans ? mulliganSetup(form, offered, c) : undefined;
  if (form.question === "mulligan" && mulligan === undefined) {
    c.problem("mulligans", "Turn on mulligans in step 2 first.");
  }
  let requirements: Requirement[] = [];
  let rule: TypedRule | undefined;
  let question: Question = { kind: "chances" };
  if (form.question === "howmany") question = howMany(form, c);
  if (form.question === "draws") {
    if (!offered.includes(form.drawsType)) c.problem("drawsType", "Pick a card type from the list.");
    question = { kind: "draws", cardType: form.drawsType, lastTurn: lastTurnOf(form, last, c) };
  } else {
    if (form.useRule) {
      const read = readRule(core, form.rule);
      if (read.ok) rule = read.value;
      else c.problem("rule", read.message);
    } else {
      requirements = goalLines(form, offered, last, c, form.question === "chances");
    }
    if (form.question === "turns") question = { kind: "turns", lastTurn: lastTurnOf(form, last, c) };
    if (form.question === "mulligan") question = { kind: "mulligan" };
  }

  if (issues.length > 0 || size === null) return { ok: false, issues, notes };
  const goal: Goal =
    rule === undefined
      ? { requirements, combine: form.combine }
      : { requirements, combine: form.combine, rule };
  return {
    ok: true,
    setup: {
      deck: { size, types },
      play,
      goal,
      question,
      ...(decklist === undefined ? {} : { decklist }),
      ...(mulligan === undefined ? {} : { mulligan }),
    },
    notes,
  };
}
