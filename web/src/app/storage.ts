/**
 * Remembers the player's form in this browser only (NFR-18 allows it), so a reload does
 * not lose their deck. Anything unreadable is ignored: the page then opens with the
 * example, as on a first visit. Storage may be missing or blocked (private windows);
 * every access is guarded.
 */
import {
  KINDS,
  type FormState,
  type GoalGroupRow,
  type GoalRow,
  type KeepGroupRow,
  type KeepRuleRow,
  type ProtectRow,
  type TypeRow,
  type VaryRow,
} from "../forms/model.ts";
import type { AppState } from "./state.ts";

export const STORAGE_KEY = "mtgcalc.web.form.v1";

function isString(x: unknown): x is string {
  return typeof x === "string";
}

function isTypeRow(x: unknown): x is TypeRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  return isString(r["id"]) && isString(r["name"]) && isString(r["count"]) && isString(r["also"]);
}

function isVaryRow(x: unknown): x is VaryRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  return isString(r["id"]) && isString(r["cardType"]) && isString(r["low"]) && isString(r["high"]);
}

function isProtectRow(x: unknown): x is ProtectRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  return isString(r["id"]) && isString(r["cardType"]) && isString(r["upTo"]);
}

function isKeepRuleRow(x: unknown): x is KeepRuleRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  return isString(r["id"]) && isString(r["cardType"]) && isString(r["min"]) && isString(r["max"]);
}

/** A kind of hand to keep: 1 to 50 lines (an empty kind is never saved). */
function isKeepGroupRow(x: unknown): x is KeepGroupRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  const rules = r["rules"];
  return (
    isString(r["id"]) &&
    Array.isArray(rules) &&
    rules.length >= 1 &&
    rules.length <= 50 &&
    rules.every(isKeepRuleRow)
  );
}

function isGoalRow(x: unknown): x is GoalRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  return (
    isString(r["id"]) &&
    (KINDS as readonly unknown[]).includes(r["kind"]) &&
    isString(r["amount"]) &&
    isString(r["cardType"]) &&
    isString(r["turn"])
  );
}

/** A kind of good game: 1 to 50 lines (an empty kind is never saved). */
function isGoalGroupRow(x: unknown): x is GoalGroupRow {
  if (typeof x !== "object" || x === null) return false;
  const r = x as Record<string, unknown>;
  const rules = r["rules"];
  return (
    isString(r["id"]) &&
    Array.isArray(rules) &&
    rules.length >= 1 &&
    rules.length <= 50 &&
    rules.every(isGoalRow)
  );
}

/** Fields added after the first version, with their defaults (older saves lack them). */
const ADDED = {
  deckMode: "types",
  decklist: "",
  useRule: false,
  rule: "",
  question: "chances",
  drawsType: "",
  lastTurn: "5",
  mulligans: false,
  keep: [{ id: "k1", rules: [{ id: "k2", cardType: "land", min: "2", max: "5" }] }],
  protect: [{ id: "p1", cardType: "land", upTo: "3" }],
  maxMulligans: "2",
  freeFirst: false,
  hmMode: "one",
  hmAim: "target",
  hmVary: [{ id: "v1", cardType: "land", low: "14", high: "40" }],
  hmTarget: "60",
  hmSlots: "20",
} as const;

/**
 * "How many should I play?" had three modes before the aim was added; each maps to a
 * mode and an aim. "fewest" had no limit on the cards, so it gets the whole deck.
 */
function upgradeHowMany(form: Record<string, unknown>): Record<string, unknown> {
  switch (form["hmMode"]) {
    case "need":
      return { ...form, hmMode: "one", hmAim: "target" };
    case "split":
      return { ...form, hmMode: "share", hmAim: "best" };
    case "fewest":
      return { ...form, hmMode: "share", hmAim: "target", hmSlots: form["deckSize"] };
    default:
      return form;
  }
}

/**
 * The keep rule was one line (`keepType`, `keepMin`, `keepMax`; type "" = keep any hand)
 * before kinds of hand were added; it becomes one kind with that line, or no kinds.
 */
function upgradeKeep(form: Record<string, unknown>): Record<string, unknown> {
  if (!("keepType" in form)) return form;
  const { keepType, keepMin, keepMax, ...rest } = form;
  if (!isString(keepType)) return rest;
  if (keepType === "") return { ...rest, keep: [] };
  const rule = { id: "k2", cardType: keepType, min: keepMin, max: keepMax };
  return { ...rest, keep: [{ id: "k1", rules: [rule] }] };
}

/**
 * The good game was a list of lines with one "all"/"any" switch (`combine`) before kinds
 * of good game were added: "all" becomes one kind with every line, "any" one kind per line.
 */
function upgradeGoal(form: Record<string, unknown>): Record<string, unknown> {
  if (!("combine" in form)) return form;
  const { combine, goal, ...rest } = form;
  if (!Array.isArray(goal)) return { ...rest, goal };
  const lines: unknown[] = goal;
  const id = (i: number): string => `g${String(i + 1)}`;
  const groups =
    combine === "any"
      ? lines.map((line, i) => ({ id: id(i), rules: [line] }))
      : [{ id: id(0), rules: lines }];
  return { ...rest, goal: groups.filter((g) => g.rules.length > 0) };
}

/** Fills in fields an older version of the page did not save. */
function upgrade(x: unknown): unknown {
  if (typeof x !== "object" || x === null) return x;
  const s = x as { form?: unknown };
  if (typeof s.form !== "object" || s.form === null) return x;
  return { ...s, form: upgradeHowMany(upgradeKeep(upgradeGoal({ ...ADDED, ...s.form }))) };
}

/** Whether `x` is a complete, well-formed saved state (never trusts storage). */
export function isAppState(x: unknown): x is AppState {
  if (typeof x !== "object" || x === null) return false;
  const s = x as { form?: unknown; nextId?: unknown };
  if (typeof s.nextId !== "number" || !Number.isSafeInteger(s.nextId) || s.nextId < 1) return false;
  const f = s.form as Partial<Record<keyof FormState, unknown>> | undefined;
  if (typeof f !== "object") return false;
  return (
    (f.deckMode === "types" || f.deckMode === "list") &&
    ["chances", "draws", "turns", "mulligan", "howmany"].includes(String(f.question)) &&
    typeof f.mulligans === "boolean" &&
    Array.isArray(f.keep) &&
    f.keep.length <= 50 &&
    f.keep.every(isKeepGroupRow) &&
    isString(f.maxMulligans) &&
    typeof f.freeFirst === "boolean" &&
    (f.hmMode === "one" || f.hmMode === "share") &&
    (f.hmAim === "best" || f.hmAim === "target") &&
    isString(f.hmTarget) &&
    isString(f.hmSlots) &&
    Array.isArray(f.hmVary) &&
    f.hmVary.length <= 50 &&
    f.hmVary.every(isVaryRow) &&
    Array.isArray(f.protect) &&
    f.protect.length <= 50 &&
    f.protect.every(isProtectRow) &&
    isString(f.drawsType) &&
    isString(f.lastTurn) &&
    isString(f.decklist) &&
    f.decklist.length <= 1_000_000 &&
    typeof f.useRule === "boolean" &&
    isString(f.rule) &&
    f.rule.length <= 10_000 &&
    isString(f.deckSize) &&
    typeof f.goFirst === "boolean" &&
    isString(f.drawsPerTurn) &&
    Array.isArray(f.types) &&
    f.types.length <= 50 &&
    f.types.every(isTypeRow) &&
    Array.isArray(f.goal) &&
    f.goal.length <= 50 &&
    f.goal.every(isGoalGroupRow)
  );
}

/** The browser's storage; reading it can itself throw (e.g. blocked in some iframes). */
function browserStorage(): Storage | undefined {
  return (globalThis as { localStorage?: Storage }).localStorage;
}

export function loadState(storage?: Pick<Storage, "getItem">): AppState | null {
  try {
    const text = (storage ?? browserStorage())?.getItem(STORAGE_KEY) ?? null;
    if (text === null) return null;
    const data = upgrade(JSON.parse(text));
    return isAppState(data) ? data : null;
  } catch {
    return null;
  }
}

export function saveState(state: AppState, storage?: Pick<Storage, "setItem">): void {
  try {
    (storage ?? browserStorage())?.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Full or blocked storage: the page still works, it just will not remember.
  }
}
