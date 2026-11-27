/**
 * Builds the engine request for a setup, in the JSON format of
 * `mtgcalc.model.serialization.to_dict` (ADR-0013 §3).
 *
 * A port of `mtgcalc_gui.forms.build_scenario` + `goal_condition`: the parity tests
 * require the exact same JSON as Python for every golden case.
 */
import {
  ANY_CARD,
  FILLER,
  HAND_SIZE,
  type KeepRule,
  type Question,
  type Requirement,
  type Setup,
} from "./model.ts";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

/** A request (ADR-0013 §3): the deck as a scenario or as decklist text, plus a query
 *  and/or a question. */
export type Request = Readonly<Record<string, Json>>;

/**
 * Python serializes a frozenset as items sorted by `repr`, so `"mana rock"` sorts
 * before `"mana"` (a space comes before the closing quote). Rust ignores the order;
 * matching it keeps the JSON byte-comparable with Python's.
 */
function reprKey(s: string): string {
  if (s.includes("'") && !s.includes('"')) return `"${s}"`;
  return `'${s.replace(/\\/gu, "\\\\").replace(/'/gu, "\\'")}'`;
}

function frozenset(items: Iterable<string>): Json {
  const sorted = [...new Set(items)].sort((a, b) => {
    const ka = reprKey(a);
    const kb = reprKey(b);
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  return { type: "frozenset", items: sorted };
}

function card(name: string, quantity: number, tags: Iterable<string>): Json {
  return { type: "Card", name, quantity, tags: frozenset(tags), zone: "library" };
}

/** Python's `Deck.from_counts`: one card per type with a count, plus the filler. */
function deckJson(setup: Setup): Json {
  const cards: Json[] = [];
  let total = 0;
  for (const t of setup.deck.types) {
    total += t.count;
    if (t.count > 0) cards.push(card(t.name, t.count, [t.name, ...t.also]));
  }
  const rest = setup.deck.size - total;
  if (rest > 0) cards.push(card(FILLER, rest, [FILLER]));
  return { type: "Deck", cards, name: null };
}

function selectorJson(cardType: string): Json {
  return cardType === ANY_CARD ? { type: "Everything" } : { type: "Tag", name: cardType };
}

/** One goal line, bound to its turn (or not, for "Turn by turn"). */
function requirementJson(r: Requirement, withTurn = true): Json {
  const [op, value] =
    r.kind === "none"
      ? ["==", 0]
      : r.kind === "at least"
        ? [">=", r.amount]
        : r.kind === "at most"
          ? ["<=", r.amount]
          : ["==", r.amount];
  const leaf: Json = { type: "Compare", sel: selectorJson(r.cardType), op, value };
  return withTurn ? { type: "At", turn: r.turn, item: leaf } : leaf;
}

/** Python's `goal_condition(goal, with_turns=...)`. */
function goalCondition(setup: Setup, withTurns: boolean): Json {
  if (setup.goal.rule !== undefined) return setup.goal.rule.condition as Json;
  // Python's `goal_condition`: any kind (`Or`) of all its lines (`And`), never wrapped needlessly.
  const kinds = setup.goal.groups.map((group) => {
    const lines = group.map((r) => requirementJson(r, withTurns));
    return lines.length === 1 && lines[0] !== undefined ? lines[0] : { type: "And", items: lines };
  });
  return kinds.length === 1 && kinds[0] !== undefined ? kinds[0] : { type: "Or", items: kinds };
}

/**
 * Python's `keep_condition`: any kind of hand (`Or`), each with all its lines (`And`);
 * one line or one kind is not wrapped, and no kinds means "keep any hand".
 */
function keepJson(keep: readonly (readonly KeepRule[])[]): Json {
  const kinds = keep.map((rules) => {
    const lines = rules.map((r): Json => ({
      type: "Between",
      sel: selectorJson(r.cardType),
      lo: r.min,
      hi: r.max,
    }));
    return lines.length === 1 && lines[0] !== undefined ? lines[0] : { type: "And", items: lines };
  });
  if (kinds.length === 0) return { type: "Const", value: true };
  return kinds.length === 1 && kinds[0] !== undefined ? kinds[0] : { type: "Or", items: kinds };
}

/** Python's `MulliganConfig` from `build_scenario` (null without mulligans). */
function mulliganJson(setup: Setup): Json {
  const m = setup.mulligan;
  if (m === undefined) return null;
  return {
    type: "MulliganConfig",
    priority: m.protect.map(([cardType, quota]) => ({
      type: "PriorityGroup",
      selector: selectorJson(cardType),
      quota,
      name: null,
    })),
    keep_rule: keepJson(m.keep),
    max_mulligans: m.maxMulligans,
    free_mulligans: m.freeFirst ? 1 : 0,
    draw_size: HAND_SIZE,
  };
}

/** An exact decimal percentage ("92.5") as a reduced fraction of 1 ("37/40"). */
export function percentFraction(percent: string): string {
  const [whole = "0", frac = ""] = percent.split(".");
  let num = BigInt(whole + frac);
  let den = 100n * 10n ** BigInt(frac.length);
  const gcd = (a: bigint, b: bigint): bigint => (b === 0n ? a : gcd(b, a % b));
  const g = num === 0n ? den : gcd(num, den);
  num /= g;
  den /= g;
  return `${num.toString()}/${den.toString()}`;
}

const OBJECTIVES = {
  one: { best: "max_probability", target: "min_count" },
  share: { best: "max_probability", target: "min_total" },
} as const;

/** Python's `how_many` problem: the changed types are variables, the others fixed. */
function problemJson(setup: Setup, q: Question & { kind: "howmany" }, game: Json, mulligan: Json): Json {
  const changed = new Set(q.vary.map(([n]) => n));
  const alsoOf = (name: string): readonly string[] =>
    setup.deck.types.find((t) => t.name === name)?.also ?? [];
  return {
    type: "OptimizeProblem",
    deck_size: setup.deck.size,
    variables: q.vary.map(([name, lo, hi]) => ({
      type: "Variable",
      name,
      lo,
      hi,
      tags: frozenset(alsoOf(name)),
    })),
    query: { type: "Query", condition: goalCondition(setup, true), given: null, turn: 0 },
    // The JSON key, not the deprecated String.prototype.fixed the rule mistakes it for.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    fixed: setup.deck.types
      .filter((t) => !changed.has(t.name))
      .map((t) => [t.name, { type: "Category", count: t.count, tags: frozenset(t.also) }]),
    game,
    mulligan,
    objective: OBJECTIVES[q.mode][q.aim],
    target: q.aim === "target" ? { type: "Fraction", value: percentFraction(q.target) } : null,
    budget: q.mode === "share" ? q.slots : null,
    exhaustive_limit: 5000,
    assume_monotone: null,
    workers: null,
  };
}

function upTo(last: number): Json {
  return Array.from({ length: last + 1 }, (_, t) => t);
}

export function buildRequest(setup: Setup): Request {
  const game: Json = {
    type: "GameConfig",
    hand_size: HAND_SIZE,
    on_play: setup.play.goFirst,
    draws_per_turn: setup.play.drawsPerTurn,
    draw_overrides: [],
    extra_draws: [],
  };
  const mulligan = mulliganJson(setup);
  const deck: Request =
    setup.decklist !== undefined
      ? { decklist: setup.decklist.text, game, ...(mulligan === null ? {} : { mulligan }) }
      : { scenario: { type: "Scenario", deck: deckJson(setup), game, mulligan } };
  const question = setup.question ?? { kind: "chances" };
  switch (question.kind) {
    case "chances":
      return {
        ...deck,
        query: { type: "Query", condition: goalCondition(setup, true), given: null, turn: 0 },
      };
    case "draws":
      return {
        ...deck,
        question: {
          type: "Distributions",
          selector: selectorJson(question.cardType),
          turns: upTo(question.lastTurn),
        },
      };
    case "howmany":
      return { optimize: problemJson(setup, question, game, mulligan), one_fewer: question.mode === "one" };
    case "mulligan":
      return {
        ...deck,
        query: { type: "Query", condition: goalCondition(setup, true), given: null, turn: 0 },
        question: { type: "MulliganAdvice" },
      };
    case "turns":
      return {
        ...deck,
        query: { type: "Query", condition: goalCondition(setup, false), given: null, turn: 0 },
        question: { type: "TurnTable", turns: upTo(question.lastTurn) },
      };
  }
}
