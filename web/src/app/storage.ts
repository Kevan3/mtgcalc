/**
 * Remembers the player's form in this browser only (NFR-18 allows it), so a reload does
 * not lose their deck. Anything unreadable is ignored: the page then opens with the
 * example, as on a first visit. Storage may be missing or blocked (private windows);
 * every access is guarded.
 */
import {
  KINDS,
  type FormState,
  type GoalRow,
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
  keepType: "land",
  keepMin: "2",
  keepMax: "5",
  protect: [{ id: "p1", cardType: "land", upTo: "3" }],
  maxMulligans: "2",
  freeFirst: false,
  hmMode: "need",
  hmVary: [{ id: "v1", cardType: "land", low: "14", high: "40" }],
  hmTarget: "60",
  hmSlots: "20",
} as const;

/** Fills in fields an older version of the page did not save. */
function upgrade(x: unknown): unknown {
  if (typeof x !== "object" || x === null) return x;
  const s = x as { form?: unknown };
  if (typeof s.form !== "object" || s.form === null) return x;
  return { ...s, form: { ...ADDED, ...s.form } };
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
    isString(f.keepType) &&
    isString(f.keepMin) &&
    isString(f.keepMax) &&
    isString(f.maxMulligans) &&
    typeof f.freeFirst === "boolean" &&
    (f.hmMode === "need" || f.hmMode === "split" || f.hmMode === "fewest") &&
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
    (f.combine === "all" || f.combine === "any") &&
    Array.isArray(f.types) &&
    f.types.length <= 50 &&
    f.types.every(isTypeRow) &&
    Array.isArray(f.goal) &&
    f.goal.length <= 50 &&
    f.goal.every(isGoalRow)
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
