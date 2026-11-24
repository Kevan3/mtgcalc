/**
 * Pasted decklists and typed rules: what the core read, and plain-language problems.
 *
 * The core's parse errors are Python's (`ParseError(message, line, column)`), written
 * for programmers. Each known message gets a sentence a player can act on; anything
 * unexpected is still shown, with its position, rather than hidden.
 */
import type { Core } from "../engine/core.ts";
import type { Decklist, TypedRule } from "./model.ts";

export type Read<T> =
  { readonly ok: true; readonly value: T } | { readonly ok: false; readonly message: string };

interface ErrorReply {
  readonly type: "Error";
  readonly kind: string;
  readonly field?: string;
  readonly message: string;
  readonly line?: number;
  readonly column?: number;
}

function isError(x: unknown): x is ErrorReply {
  return typeof x === "object" && x !== null && (x as { type?: unknown }).type === "Error";
}

/** Python's repr of a short text, as it appears inside the core's messages: 'x' or "x". */
const QUOTED = /^(?:'(.*)'|"(.*)")$/su;

function unquote(s: string): string {
  const m = QUOTED.exec(s);
  return m === null ? s : (m[1] ?? m[2] ?? s);
}

/** "expected 'int' (found 'x')" → ["expected 'int'", "x"]. */
function splitFound(message: string): [string, string | null] {
  const m = /^(.*) \(found (.*)\)$/su.exec(message);
  return m === null ? [message, null] : [m[1] ?? message, unquote(m[2] ?? "")];
}

// ---------------------------------------------------------------------------------
// Decklists
// ---------------------------------------------------------------------------------

function deckProblem(e: ErrorReply): string {
  const at = e.line === undefined ? "" : `Line ${String(e.line)}: `;
  switch (e.message) {
    case "expected '<quantity> <card name>'":
      return `${at}start the line with how many copies, like “4 Lightning Bolt”.`;
    case "quantity must be at least 1":
      return `${at}the number of copies must be 1 or more.`;
    case "missing card name":
      return `${at}a card name is missing after the number.`;
    case "decklist is empty":
      return "Paste your decklist: one card per line, like “4 Lightning Bolt”.";
    case "library must contain at least one card":
      return "Your decklist has no cards in the main deck (only a commander or sideboard).";
    default:
      if (e.message.startsWith("decklist longer than")) return "This decklist is too long to read.";
      if (e.kind === "unsupported") return "This deck has more cards than the calculator can handle.";
      return `${at}${e.message}`;
  }
}

interface CardJson {
  readonly name: string;
  readonly quantity: number;
  readonly tags: { readonly items: readonly string[] };
  readonly zone: string;
}

/** Reads a pasted decklist with the core. */
export function readDecklist(core: Core, text: string): Read<Decklist> {
  if (text.trim() === "") {
    return { ok: false, message: "Paste your decklist: one card per line, like “4 Lightning Bolt”." };
  }
  const reply: unknown = JSON.parse(core.parseDeck(text));
  if (isError(reply)) return { ok: false, message: deckProblem(reply) };
  const cards = (reply as { cards: readonly CardJson[] }).cards;
  const library = cards.filter((c) => c.zone === "library");
  const counts = new Map<string, number>();
  for (const c of library) {
    for (const t of c.tags.items) counts.set(t, (counts.get(t) ?? 0) + c.quantity);
  }
  const byCodePoint = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
  return {
    ok: true,
    value: {
      text,
      size: library.reduce((sum, c) => sum + c.quantity, 0),
      tags: [...counts.entries()].sort(([a], [b]) => byCodePoint(a, b)),
      commanders: cards.filter((c) => c.zone === "commander").map((c) => c.name),
    },
  };
}

// ---------------------------------------------------------------------------------
// Typed rules
// ---------------------------------------------------------------------------------

const RULE_WORDS: readonly (readonly [RegExp, (found: string, m: RegExpExecArray) => string])[] = [
  [/^expected 'int'$/u, () => "a number should come here"],
  [/^expected 'op'$/u, () => "a comparison such as >= should come here"],
  [/^expected '>='$/u, () => "write >= here, as in assign(land >= 3, ramp >= 1)"],
  [/^expected '\)'$/u, () => "a closing bracket “)” is missing"],
  [/^expected '\('$/u, () => "an opening bracket “(” should come here"],
  [/^expected ':'$/u, () => 'write a colon here, as in card:"Sol Ring"'],
  [/^expected 'string'$/u, () => 'a name in double quotes should come here, as in card:"Sol Ring"'],
  [/^expected 'dotdot'$/u, () => "write a range as 2..4"],
  [/^expected a selector$/u, () => "a card type should come here"],
  [/^expected a turn such as T3$/u, () => "write a turn after @, as in @T3"],
  [/^unexpected trailing input$/u, (f) => `“${f}” does not fit here`],
  [/^range must satisfy lo <= hi$/u, () => "the first number of a range must not be bigger than the second"],
  [/^demand must be at least 1$/u, () => "each part of assign(...) needs at least 1 card"],
  [
    /^(atleast|exactly) needs at least one condition$/u,
    (_, m) => `${m[1] ?? "atleast"}(...) needs at least one condition after the number`,
  ],
  [/^tag name must not be empty$/u, () => "a card type name cannot be empty"],
  [/^card name must not be empty$/u, () => "a card name cannot be empty"],
  [/^nesting deeper than \d+$/u, () => "too many brackets inside each other"],
];

function ruleProblem(e: ErrorReply): string {
  if (e.kind !== "parse") return e.message;
  const where = e.column === undefined ? "" : `At character ${String(e.column)}: `;
  if (e.message.startsWith("unexpected character ")) {
    return `${where}“${unquote(e.message.slice("unexpected character ".length))}” cannot be used in a rule.`;
  }
  if (e.message.startsWith("expression longer than")) return "This rule is too long.";
  const [core, found] = splitFound(e.message);
  const keyword = /^'(.*)' is a keyword; write tag:"(.*)"$/u.exec(core);
  if (keyword !== null) {
    return `${where}“${keyword[1] ?? ""}” is a special word. To use it as a card type, write tag:"${keyword[2] ?? ""}".`;
  }
  for (const [pattern, say] of RULE_WORDS) {
    const m = pattern.exec(core);
    if (m !== null) {
      const end = found === "end of input" ? " (the rule ended too soon)" : "";
      return `${where}${say(found ?? "", m)}${end}.`;
    }
  }
  return `${where}${e.message}`;
}

/** Reads a typed rule with the core (Python's `parse_condition`: no GIVEN). */
export function readRule(core: Core, text: string): Read<TypedRule> {
  if (text.trim() === "") {
    return { ok: false, message: "Type a rule, or untick the box to use the lines above." };
  }
  const reply: unknown = JSON.parse(core.parseRule(text, 0));
  if (isError(reply)) return { ok: false, message: ruleProblem(reply) };
  const query = reply as { condition: unknown; given: unknown };
  if (query.given !== null) {
    return { ok: false, message: "GIVEN cannot be used here: describe one good game." };
  }
  return { ok: true, value: { text, condition: query.condition } };
}

/** The rule-language text of a condition (to pre-fill the rule box), or null. */
export function ruleText(core: Core, condition: unknown): string | null {
  const reply: unknown = JSON.parse(
    core.formatRule(JSON.stringify({ type: "Query", condition, given: null, turn: 0 })),
  );
  if (isError(reply)) return null;
  return (reply as { text: string }).text;
}
