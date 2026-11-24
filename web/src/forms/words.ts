/**
 * Answers in words (port of `pct`, `in_words`, `turn_words`, `describe_goal` and the
 * `chances` headline in `mtgcalc_gui.forms`).
 *
 * Probabilities stay exact: every rounding is done on the exact fraction with BigInt,
 * to the nearest value and ties to even (FR-95), never on a floating-point copy.
 */
import { ANY_CARD, type Goal } from "./model.ts";

/** An exact probability `num / den` (den > 0). */
export interface Exact {
  readonly num: bigint;
  readonly den: bigint;
}

/** Parses Python's `"n/d"` fraction text. */
export function parseFraction(text: string): Exact {
  const match = /^(\d+)\/(\d+)$/u.exec(text);
  if (match?.[1] === undefined || match[2] === undefined || BigInt(match[2]) === 0n) {
    throw new Error(`not a fraction: ${text}`);
  }
  return { num: BigInt(match[1]), den: BigInt(match[2]) };
}

/** `round(a / b)` for a, b >= 0, b > 0, ties to even. */
export function roundHalfEven(a: bigint, b: bigint): bigint {
  const q = a / b;
  const twice = 2n * (a % b);
  if (twice > b || (twice === b && q % 2n === 1n)) return q + 1n;
  return q;
}

/** `scaled` hundredths/thousandths as text with `places` decimals. */
function decimal(scaled: bigint, places: number): string {
  const unit = 10n ** BigInt(places);
  const frac = (scaled % unit).toString().padStart(places, "0");
  return `${scaled / unit}.${frac}`;
}

/**
 * A probability as a percentage: one decimal between 0.1% and 99.9% (and for 0% and
 * 100%), three decimals outside that range, and "less than 0.001%" for tiny values.
 */
export function pct({ num, den }: Exact): string {
  // value = 100 * num / den, compared exactly against the thresholds.
  const hundred = 100n * num;
  if (num > 0n && hundred * 1000n < den) return "less than 0.001%";
  const oneDecimal = num === 0n || num === den || (hundred * 10n >= den && hundred * 10n <= 999n * den);
  if (oneDecimal) return `${decimal(roundHalfEven(hundred * 10n, den), 1)}%`;
  return `${decimal(roundHalfEven(hundred * 1000n, den), 3)}%`;
}

/**
 * Rough everyday phrasing. Near the middle: "about 4 games in 10". Rare things: "about 1
 * game in 25". Near-certain things: "all but about 1 game in 25".
 */
export function inWords({ num, den }: Exact): string {
  if (num === 0n) return "never";
  if (num === den) return "every game";
  if (1000n * num >= 995n * den) return "almost every game";
  if (1000n * num <= 5n * den) return "almost never";
  if (100n * num < 15n * den) return `about 1 game in ${roundHalfEven(den, num)}`;
  if (100n * num > 85n * den) return `all but about 1 game in ${roundHalfEven(den, den - num)}`;
  return `about ${roundHalfEven(10n * num, den)} games in 10`;
}

/** `0` → "in your opening hand", `3` → "by turn 3". */
export function turnWords(turn: number): string {
  return turn === 0 ? "in your opening hand" : `by turn ${turn}`;
}

/** The goal in words, e.g. "at least 3 land by turn 3 and at least 1 removal by turn 3". */
export function describeGoal(
  goal: Goal,
  labels: Readonly<Record<string, string>> = {},
  withTurns = true,
): string {
  if (goal.rule !== undefined) return `your rule (${goal.rule.text.trim()})`;
  const words = goal.requirements.map((r) => {
    const what =
      r.cardType !== ANY_CARD
        ? (labels[r.cardType] ?? r.cardType)
        : r.kind !== "none" && r.amount === 1
          ? "card"
          : "cards";
    const amount = r.kind === "none" ? "no" : `${r.kind} ${r.amount}`;
    return withTurns ? `${amount} ${what} ${turnWords(r.turn)}` : `${amount} ${what}`;
  });
  return words.join(goal.combine === "all" ? " and " : " or ");
}

/** The one-sentence answer (FR-85, FR-95). */
export function headline(goal: Goal, p: Exact, labels: Readonly<Record<string, string>> = {}): string {
  return `You have ${describeGoal(goal, labels)} in ${pct(p)} of games (${inWords(p)}).`;
}

/**
 * "Show the exact numbers": the percentage to four decimals, then the exact fraction
 * with a plain explanation of where such large numbers come from.
 */
export function exactWords({ num, den }: Exact): { precise: string; fraction: string } {
  const group = (n: bigint): string => n.toString().replace(/\B(?=(\d{3})+(?!\d))/gu, ",");
  return {
    precise: `${decimal(roundHalfEven(100n * 10_000n * num, den), 4)}%`,
    fraction: `${group(num)} / ${group(den)}`,
  };
}

/** The exact mean of a distribution, `sum(k * pmf[k])`. */
export function mean(pmf: readonly Exact[]): Exact {
  // Every pmf entry of one distribution shares the engine's denominator up to reduction,
  // so a common denominator keeps the numbers small.
  const lcm = (a: bigint, b: bigint): bigint => (a / gcd(a, b)) * b;
  const den = pmf.reduce((acc, p) => lcm(acc, p.den), 1n);
  const num = pmf.reduce((acc, p, k) => acc + BigInt(k) * p.num * (den / p.den), 0n);
  return { num, den };
}

function gcd(a: bigint, b: bigint): bigint {
  return b === 0n ? a : gcd(b, a % b);
}

/** `x` with two decimals, rounded from the exact value (ties to even), e.g. "2.80". */
export function twoDecimals({ num, den }: Exact): string {
  return decimal(roundHalfEven(100n * num, den), 2);
}

/** P(exactly k), P(at least k), P(at most k) from a pmf. */
export function tails(pmf: readonly Exact[], k: number): { exactly: Exact; atLeast: Exact; atMost: Exact } {
  const sum = (ps: readonly Exact[]): Exact => {
    const den = ps.reduce((acc, p) => (acc / gcd(acc, p.den)) * p.den, 1n);
    return { num: ps.reduce((acc, p) => acc + p.num * (den / p.den), 0n), den };
  };
  return {
    exactly: pmf[k] ?? { num: 0n, den: 1n },
    atLeast: sum(pmf.slice(k)),
    atMost: sum(pmf.slice(0, k + 1)),
  };
}

/** "How many will I draw?": "On average you will have seen 2.80 land by turn 3." */
export function drawsHeadline(what: string, average: Exact, lastTurn: number): string {
  return `On average you will have seen ${twoDecimals(average)} ${what} ${turnWords(lastTurn)}.`;
}

/** "Turn by turn": "The chance of having at least 3 land, turn by turn." */
export function turnsHeadline(goal: Goal, labels: Readonly<Record<string, string>> = {}): string {
  return `The chance of having ${describeGoal(goal, labels, false)}, turn by turn.`;
}
