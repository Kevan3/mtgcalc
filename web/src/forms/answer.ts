/**
 * Reads the engine's JSON reply (ADR-0013 §3) and says it in words.
 *
 * Every error kind gets its own plain message (FR-99); the technical text is kept
 * separately so it can be shown under "details" for bug reports, never as the message.
 */
import { ANY_CARD, HAND_SIZE, type Goal, type Question } from "./model.ts";
import { percentFraction } from "./request.ts";
import {
  describeGoal,
  drawsHeadline,
  exactWords,
  headline,
  inWords,
  mean,
  parseFraction,
  pct,
  tails,
  turnsHeadline,
  twoDecimals,
  type Exact,
} from "./words.ts";

export type View =
  | {
      readonly kind: "answer";
      readonly headline: string;
      /** Supporting sentences (e.g. that mulligans are included). */
      readonly details: readonly string[];
      readonly precise: string;
      readonly fraction: string;
      readonly probability: Exact;
    }
  | {
      readonly kind: "draws";
      readonly headline: string;
      /** What is counted: a card type, or "cards". */
      readonly what: string;
      readonly rows: readonly DrawsRow[];
    }
  | {
      readonly kind: "turns";
      readonly headline: string;
      readonly rows: readonly TurnsRow[];
    }
  | {
      readonly kind: "mulligan";
      readonly headline: string;
      readonly details: readonly string[];
      /** Your plan, step by step. */
      readonly yourPlan: readonly AdviceRow[];
      /** The best possible plan: its chance, and each step's keep rule and hands. */
      readonly best: { readonly value: string; readonly steps: readonly BestStep[] };
    }
  | {
      readonly kind: "howmany";
      readonly headline: string;
      readonly details: readonly string[];
      /** Options tried, highest chance first: counts, chance, in words. */
      readonly rows: readonly {
        readonly option: string;
        readonly chance: string;
        readonly words: string;
        /** This row is the answer in the headline. */
        readonly chosen: boolean;
      }[];
    }
  | {
      readonly kind: "problem";
      readonly headline: string;
      readonly advice: string;
      readonly details: string;
    };

/** "How many will I draw?": one turn, with the chance of each number. */
export interface DrawsRow {
  readonly turn: number;
  /** The average number seen, e.g. "2.80". */
  readonly average: string;
  /** For k = 0, 1, ...: percentages of exactly / at least / at most k. */
  readonly counts: readonly {
    readonly k: number;
    readonly exactly: string;
    readonly atLeast: string;
    readonly atMost: string;
  }[];
}

/** "Should I mulligan?": one step of your plan. */
export interface AdviceRow {
  readonly step: string;
  readonly getHere: string;
  readonly keepIt: string;
  readonly goodGame: string;
}

/** "Should I mulligan?": one step of the best plan, with every hand it may draw. */
export interface BestStep {
  readonly title: string;
  readonly keepIt: string;
  readonly hands: readonly { readonly text: string; readonly chance: string; readonly goodGame: string }[];
}

/** "Turn by turn": one turn. */
export interface TurnsRow {
  readonly turn: number;
  readonly cardsSeen: number;
  readonly chance: string;
  readonly words: string;
}

/** What a reply needs to be put into words: its goal, names and question. */
export interface Wording {
  readonly goal: Goal;
  readonly labels?: Readonly<Record<string, string>>;
  readonly question?: Question;
  /** Whether the answer includes mulligans (it then says so). */
  readonly mulligans?: boolean;
}

const PROBLEMS: Record<string, { headline: string; advice: string }> = {
  too_large: {
    headline: "This question is too big to work out exactly.",
    advice: "Try fewer card types or fewer lines, or ask about an earlier turn.",
  },
  unsupported: {
    headline: "This question goes beyond what the calculator can do yet.",
    advice: "Try fewer card types or fewer lines.",
  },
  validation: {
    headline: "The calculator could not use this setup.",
    advice: "Check the numbers in your deck and your lines.",
  },
};

const BUG = {
  headline: "Something went wrong inside the calculator.",
  advice: "Please try again. If it keeps happening, report it with the details below.",
};

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function problem(kind: string, details: string): View {
  const text = PROBLEMS[kind] ?? BUG;
  return { kind: "problem", ...text, details };
}

/** Validation problems a typed rule can cause, said in plain words (else null). */
function ruleTrouble(field: string, message: string): { headline: string; advice: string } | null {
  const card = /^no library card named (.*)$/u.exec(message);
  if (field === "selector" && card !== null) {
    return {
      headline: `Your rule names a card that is not in your deck: ${card[1] ?? ""}.`,
      advice: 'Check the spelling inside card:"...", or add the card to your decklist.',
    };
  }
  if (field === "game" && message.includes("draws exceed")) {
    return {
      headline: "Your rule looks further ahead than your deck has cards for.",
      advice: "Use an earlier turn after @.",
    };
  }
  return null;
}

function fractionOf(x: unknown): Exact | null {
  if (!isRecord(x) || typeof x["value"] !== "string") return null;
  try {
    return parseFraction(x["value"]);
  } catch {
    return null;
  }
}

function drawsView(
  w: Wording,
  question: Question & { kind: "draws" },
  data: Record<string, unknown>,
): View | null {
  const items = Array.isArray(data["items"]) ? (data["items"] as unknown[]) : null;
  if (items === null) return null;
  const rows: DrawsRow[] = [];
  for (const item of items) {
    if (!isRecord(item) || typeof item["turn"] !== "number" || !Array.isArray(item["pmf"])) return null;
    const pmf = (item["pmf"] as unknown[]).map(fractionOf);
    if (pmf.some((p) => p === null)) return null;
    const exact = pmf as Exact[];
    rows.push({
      turn: item["turn"],
      average: twoDecimals(mean(exact)),
      counts: exact.map((_, k) => {
        const t = tails(exact, k);
        return { k, exactly: pct(t.exactly), atLeast: pct(t.atLeast), atMost: pct(t.atMost) };
      }),
    });
  }
  const last = rows.at(-1);
  const lastItem = items.at(-1);
  if (last === undefined || !isRecord(lastItem)) return null;
  const what =
    question.cardType === ANY_CARD ? "cards" : (w.labels?.[question.cardType] ?? question.cardType);
  const lastPmf = (lastItem["pmf"] as unknown[]).map(fractionOf) as Exact[];
  return { kind: "draws", headline: drawsHeadline(what, mean(lastPmf), last.turn), what, rows };
}

/** Python's `_step_name`: "First 7 cards", "After 2 mulligans (keep 6)". */
function stepName(depth: number, hand: number): string {
  if (depth === 0) return "First 7 cards";
  return `After ${String(depth)} mulligan${depth > 1 ? "s" : ""} (keep ${String(hand)})`;
}

function cmp(a: Exact, b: Exact): number {
  const d = a.num * b.den - b.num * a.den;
  return d > 0n ? 1 : d < 0n ? -1 : 0;
}

function adviceView(w: Wording, data: Record<string, unknown>): View | null {
  const report = data["report"];
  const best = data["best"];
  if (
    !isRecord(report) ||
    !isRecord(best) ||
    !Array.isArray(report["rows"]) ||
    !Array.isArray(best["rows"])
  ) {
    return null;
  }
  const pSuccess = fractionOf(report["p_success"]);
  const value = fractionOf(best["value"]);
  const em = fractionOf(report["expected_mulligans"]);
  const eh = fractionOf(report["expected_hand_size"]);
  const atoms = Array.isArray(best["atoms"]) ? (best["atoms"] as unknown[]) : null;
  if (pSuccess === null || value === null || em === null || eh === null || atoms === null) return null;
  const yourPlan: AdviceRow[] = [];
  for (const r of report["rows"] as unknown[]) {
    if (!isRecord(r) || typeof r["depth"] !== "number" || typeof r["hand_size"] !== "number") return null;
    const [reach, keep, forced] = [r["p_reach"], r["p_keep_given_reach"], r["p_success_forced"]].map(
      fractionOf,
    );
    if (!reach || !keep || !forced) return null;
    yourPlan.push({
      step: stepName(r["depth"], r["hand_size"]),
      getHere: pct(reach),
      keepIt: pct(keep),
      goodGame: pct(forced),
    });
  }
  const never = (report["rows"] as Record<string, unknown>[])[0];
  const neverP = never ? fractionOf(never["p_success_forced"]) : null;
  if (neverP === null) return null;
  const labels = atoms.map((names) =>
    Array.isArray(names) && names.length === 1
      ? String(names[0])
      : (names as unknown[]).map(String).join(" / "),
  );
  const bestRows = best["rows"] as unknown[];
  const steps: BestStep[] = [];
  for (const [i, r] of bestRows.entries()) {
    if (
      !isRecord(r) ||
      typeof r["depth"] !== "number" ||
      typeof r["hand_size"] !== "number" ||
      !Array.isArray(r["hands"])
    ) {
      return null;
    }
    const cont = fractionOf(r["continuation_value"]);
    const keep = fractionOf(r["p_keep_given_reach"]);
    if (!cont || !keep) return null;
    const hands = (r["hands"] as unknown[]).map((h) => {
      const rec = isRecord(h) ? h : {};
      const counts = Array.isArray(rec["atom_counts"]) ? (rec["atom_counts"] as number[]) : [];
      return {
        counts,
        probability: fractionOf(rec["probability"]) ?? { num: 0n, den: 1n },
        success: fractionOf(rec["success"]) ?? { num: 0n, den: 1n },
        keep: rec["keep"] === true,
      };
    });
    // Python: sorted by (-success, -probability), a stable sort.
    hands.sort((a, b) => cmp(b.success, a.success) || cmp(b.probability, a.probability));
    const rule = i === bestRows.length - 1 ? "keep any hand" : `keep if its chance is at least ${pct(cont)}`;
    steps.push({
      title: `${stepName(r["depth"], r["hand_size"])}: ${rule}`,
      keepIt: pct(keep),
      hands: hands.map((h) => {
        const parts = h.counts.flatMap((n, k) => (n > 0 ? [`${String(n)} ${labels[k] ?? "?"}`] : []));
        const other = HAND_SIZE - h.counts.reduce((a, b) => a + b, 0);
        if (other > 0) parts.push(`${String(other)} other`);
        return {
          text: `${parts.join(", ")}  ->  ${h.keep ? "keep" : "mulligan"}`,
          chance: pct(h.probability),
          goodGame: pct(h.success),
        };
      }),
    });
  }
  return {
    kind: "mulligan",
    headline:
      `With your mulligan plan you get a good game ${pct(pSuccess)} of the time. ` +
      `Never mulliganing: ${pct(neverP)}. The best possible plan: ${pct(value)}.`,
    details: [
      `A good game means: ${describeGoal(w.goal, w.labels ?? {})}.`,
      `On average you mulligan ${twoDecimals(em)} times and keep ${twoDecimals(eh)} cards.`,
      "The best plan (below) keeps a hand only when that hand is at least as good as mulliganing would be on average.",
    ],
    yourPlan,
    best: { value: pct(value), steps },
  };
}

const PROVEN = "This is guaranteed to be the best answer.";
const HEURISTIC =
  "There were too many combinations to try them all, so this is the best one found by a smart search; it is very likely, but not guaranteed, to be the best.";

function countsText(x: unknown): string | null {
  if (!Array.isArray(x)) return null;
  const parts: string[] = [];
  for (const pair of x as unknown[]) {
    if (!Array.isArray(pair) || typeof pair[0] !== "string" || typeof pair[1] !== "number") return null;
    parts.push(`${String(pair[1])} ${pair[0]}`);
  }
  return parts.join(", ");
}

function targetOf(q: Question & { kind: "howmany" }): Exact {
  return parseFraction(percentFraction(q.target));
}

/** Python's message when no counts reach the target (the GUI's `how_many`). */
export function unreachable(q: Question & { kind: "howmany" }): string {
  const top = q.vary.map(([n, , hi]) => `${String(hi)} ${n}`).join(", ");
  return (
    `${pct(targetOf(q))} cannot be reached even with ${top}. Raise the 'to' numbers, lower the target, or add ` +
    "the other card types your good game needs (card types not listed keep their step-1 counts)."
  );
}

function howManyView(
  w: Wording,
  q: Question & { kind: "howmany" },
  data: Record<string, unknown>,
): View | null {
  const chosen = countsText(data["counts"]);
  const p = fractionOf(data["probability"]);
  if (chosen === null || p === null || !Array.isArray(data["counts"]) || !Array.isArray(data["frontier"]))
    return null;
  const good = describeGoal(w.goal, w.labels ?? {});
  const counts = data["counts"] as [string, number][];
  const details: string[] = [];
  let headline: string;
  if (q.mode === "need") {
    const [name, c] = counts[0] ?? ["", 0];
    headline = `Play ${String(c)} ${name}: you then have ${good} in ${pct(p)} of games, which reaches your ${pct(targetOf(q))} target.`;
    const fewer = fractionOf(data["one_fewer"]);
    if (fewer !== null) details.push(`With ${String(c - 1)} ${name} it would be ${pct(fewer)}.`);
  } else if (q.mode === "split") {
    headline = `Best use of ${String(q.slots)} cards: ${chosen}. You then have ${good} in ${pct(p)} of games.`;
  } else {
    const total = counts.reduce((a, [, c]) => a + c, 0);
    headline = `The fewest cards that reach ${pct(targetOf(q))}: ${String(total)} (${chosen}), giving ${pct(p)}.`;
  }
  details.push(data["proven_optimal"] === true ? PROVEN : HEURISTIC);
  const rows = [];
  for (const entry of (data["frontier"] as unknown[]).slice(0, 12)) {
    if (!Array.isArray(entry)) return null;
    const option = countsText(entry[0]);
    const chance = fractionOf(entry[1]);
    if (option === null || chance === null) return null;
    rows.push({ option, chance: pct(chance), words: inWords(chance), chosen: option === chosen });
  }
  return { kind: "howmany", headline, details, rows };
}

function turnsView(w: Wording, data: Record<string, unknown>): View | null {
  const raw = Array.isArray(data["rows"]) ? (data["rows"] as unknown[]) : null;
  if (raw === null) return null;
  const rows: TurnsRow[] = [];
  for (const r of raw) {
    if (!isRecord(r) || typeof r["turn"] !== "number" || typeof r["cards_seen"] !== "number") return null;
    const p = fractionOf(r["probability"]);
    if (p === null) return null;
    rows.push({ turn: r["turn"], cardsSeen: r["cards_seen"], chance: pct(p), words: inWords(p) });
  }
  return { kind: "turns", headline: turnsHeadline(w.goal, w.labels), rows };
}

/** The view for a reply (`wording`: the goal, names and question it answers). */
export function readReply(
  wording: Wording | Goal,
  reply: string,
  labels?: Readonly<Record<string, string>>,
): View {
  const w: Wording = "requirements" in wording ? { goal: wording, ...(labels ? { labels } : {}) } : wording;
  let data: unknown;
  try {
    data = JSON.parse(reply);
  } catch {
    return problem("internal", `unreadable reply: ${reply.slice(0, 200)}`);
  }
  if (!isRecord(data)) return problem("internal", "reply is not an object");
  const asked = w.question ?? { kind: "chances" };
  if (data["type"] === "Error" && data["kind"] === "infeasible" && asked.kind === "howmany") {
    return {
      kind: "problem",
      headline: "Your target cannot be reached with these numbers.",
      advice: unreachable(asked),
      // An unreachable target is an answer, not a fault: no "details for a bug report".
      details: "",
    };
  }
  if (data["type"] === "Error") {
    const kind = typeof data["kind"] === "string" ? data["kind"] : "internal";
    const fieldName = typeof data["field"] === "string" ? data["field"] : "";
    const field = fieldName === "" ? "" : `${fieldName}: `;
    const message = typeof data["message"] === "string" ? data["message"] : "";
    const trouble = kind === "validation" ? ruleTrouble(fieldName, message) : null;
    if (trouble !== null) return { kind: "problem", ...trouble, details: `${kind}: ${field}${message}` };
    return problem(kind, `${kind}: ${field}${message}`);
  }
  const question = w.question ?? { kind: "chances" };
  const unexpected = (): View => problem("internal", `unexpected reply: ${reply.slice(0, 200)}`);
  if (question.kind === "draws") {
    const view = data["type"] === "Distributions" ? drawsView(w, question, data) : null;
    return view ?? unexpected();
  }
  if (question.kind === "howmany") {
    const view = data["type"] === "OptimizeResult" ? howManyView(w, question, data) : null;
    return view ?? unexpected();
  }
  if (question.kind === "mulligan") {
    const view = data["type"] === "MulliganAdvice" ? adviceView(w, data) : null;
    return view ?? unexpected();
  }
  if (question.kind === "turns") {
    const view = data["type"] === "TurnTable" ? turnsView(w, data) : null;
    return view ?? unexpected();
  }
  const p = data["type"] === "Probability" ? fractionOf(data["exact"]) : null;
  if (p === null) return unexpected();
  const details =
    w.mulligans === true ? ["This includes the games where you mulligan, following your plan."] : [];
  return {
    kind: "answer",
    headline: headline(w.goal, p, w.labels ?? {}),
    details,
    ...exactWords(p),
    probability: p,
  };
}
