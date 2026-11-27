/**
 * The form's state and every change a player can make to it (a pure reducer).
 *
 * Rows carry stable ids so React keeps focus on the right input when rows are added or
 * removed, and so problems can point at one input of one row.
 */
import {
  ANY_CARD,
  FORMATS,
  type HowManyMode,
  type Combine,
  type DeckMode,
  type QuestionKind,
  type FormatName,
  type FormState,
  type GoalRow,
  type KeepGroupRow,
  type KeepRuleRow,
  type ProtectRow,
  type VaryRow,
  type Kind,
  type TypeRow,
} from "../forms/model.ts";
import { cleanName, parseWhole } from "../forms/parse.ts";

export interface AppState {
  readonly form: FormState;
  /** Next row id; ids are never reused. */
  readonly nextId: number;
}

export type Action =
  | { readonly type: "deckSize"; readonly value: string }
  | { readonly type: "format"; readonly name: FormatName }
  | { readonly type: "typeChanged"; readonly id: string; readonly patch: Partial<Omit<TypeRow, "id">> }
  | { readonly type: "typeAdded" }
  | { readonly type: "typeRemoved"; readonly id: string }
  | { readonly type: "goFirst"; readonly value: boolean }
  | { readonly type: "drawsPerTurn"; readonly value: string }
  | { readonly type: "goalChanged"; readonly id: string; readonly patch: Partial<Omit<GoalRow, "id">> }
  | { readonly type: "goalAdded" }
  | { readonly type: "goalRemoved"; readonly id: string }
  | { readonly type: "combine"; readonly value: Combine }
  | { readonly type: "deckMode"; readonly value: DeckMode }
  | { readonly type: "decklist"; readonly value: string }
  | { readonly type: "useRule"; readonly value: boolean; readonly prefill?: string }
  | { readonly type: "rule"; readonly value: string }
  | { readonly type: "question"; readonly value: QuestionKind }
  | { readonly type: "drawsType"; readonly value: string }
  | { readonly type: "lastTurn"; readonly value: string }
  | { readonly type: "mulligans"; readonly value: boolean }
  | {
      readonly type: "mulliganChanged";
      readonly patch: Partial<Pick<FormState, "maxMulligans" | "freeFirst">>;
    }
  | {
      readonly type: "keepRuleChanged";
      readonly id: string;
      readonly patch: Partial<Omit<KeepRuleRow, "id">>;
    }
  /** Adds a line to a kind of hand ("and also"). */
  | { readonly type: "keepRuleAdded"; readonly group: string }
  /** Removes a line; a kind of hand left with no lines goes too. */
  | { readonly type: "keepRuleRemoved"; readonly id: string }
  /** Adds another kind of hand ("or"). */
  | { readonly type: "keepGroupAdded" }
  | { readonly type: "protectChanged"; readonly id: string; readonly patch: Partial<Omit<ProtectRow, "id">> }
  | { readonly type: "protectAdded" }
  | {
      readonly type: "howManyChanged";
      readonly patch: Partial<Pick<FormState, "hmMode" | "hmAim" | "hmTarget" | "hmSlots">>;
    }
  | { readonly type: "varyChanged"; readonly id: string; readonly patch: Partial<Omit<VaryRow, "id">> }
  | { readonly type: "varyAdded" }
  | { readonly type: "varyRemoved"; readonly id: string }
  | { readonly type: "protectRemoved"; readonly id: string }
  | { readonly type: "load"; readonly example: Example };

/** A complete filled-in form, for the examples list. */
export interface Example {
  readonly title: string;
  readonly deckSize: number;
  readonly goFirst: boolean;
  readonly types: readonly { name: string; count: number; also?: readonly string[] }[];
  /** A pasted decklist (then `types` and `deckSize` are not used). */
  readonly decklist?: string;
  /** Mulligan settings, when the example uses them. */
  readonly mulligan?: {
    /** Kinds of hand, each a list of (card type, min, max); none means "always keep". */
    readonly keep: readonly (readonly (readonly [string, number, number])[])[];
    readonly protect: readonly (readonly [string, number])[];
    readonly maxMulligans?: number;
    readonly freeFirst?: boolean;
  };
  readonly goal: readonly { kind: Kind; amount: number; cardType: string; turn: number }[];
  readonly combine?: Combine;
}

/** Examples (the desktop app's, without mulligans: the web app has none yet). */
export const EXAMPLES: readonly Example[] = [
  {
    title: "60-card deck: lands and removal by turn 3",
    deckSize: 60,
    goFirst: true,
    types: [
      { name: "land", count: 24 },
      { name: "removal", count: 6 },
    ],
    goal: [
      { kind: "at least", amount: 3, cardType: "land", turn: 3 },
      { kind: "at least", amount: 1, cardType: "removal", turn: 3 },
    ],
  },
  {
    title: "60-card deck with mulligans",
    deckSize: 60,
    goFirst: true,
    types: [
      { name: "land", count: 24 },
      { name: "removal", count: 6 },
    ],
    mulligan: {
      keep: [[["land", 2, 5]]],
      protect: [
        ["land", 3],
        ["removal", 1],
      ],
    },
    goal: [
      { kind: "at least", amount: 3, cardType: "land", turn: 3 },
      { kind: "at least", amount: 1, cardType: "removal", turn: 3 },
    ],
  },
  {
    title: "40-card Limited: lands and your key card",
    deckSize: 40,
    goFirst: true,
    types: [
      { name: "land", count: 17 },
      { name: "key card", count: 1 },
      { name: "removal", count: 4 },
    ],
    goal: [
      { kind: "at least", amount: 4, cardType: "land", turn: 4 },
      { kind: "at least", amount: 1, cardType: "key card", turn: 6 },
    ],
  },
  {
    title: "Commander: ramp on turn 2",
    deckSize: 99,
    goFirst: false,
    types: [
      { name: "land", count: 35 },
      { name: "land and removal", count: 2, also: ["land", "removal"] },
      { name: "ramp", count: 12 },
      { name: "draw", count: 10 },
      { name: "removal", count: 8 },
    ],
    mulligan: {
      keep: [
        [["land", 3, 5]],
        [
          ["land", 2, 2],
          ["ramp", 1, 7],
        ],
      ],
      protect: [
        ["land", 3],
        ["ramp", 1],
        ["draw", 1],
      ],
      freeFirst: true,
    },
    goal: [
      { kind: "at least", amount: 2, cardType: "land", turn: 2 },
      { kind: "at least", amount: 1, cardType: "ramp", turn: 2 },
    ],
  },
  {
    title: "Pasted decklist with #tags",
    deckSize: 99,
    goFirst: false,
    types: [],
    decklist:
      "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n36 Forest #land\n1 Sol Ring #ramp\n" +
      "9 Arcane Signet #ramp\n10 Divination #draw\n43 Bear\n",
    goal: [{ kind: "at least", amount: 1, cardType: "ramp", turn: 2 }],
  },
];

/** The keep rule a new form starts with: one kind of hand, 2 to 5 land (Python's `DEFAULT_KEEP`). */
const DEFAULT_KEEP: readonly (readonly (readonly [string, number, number])[])[] = [[["land", 2, 5]]];

export function fromExample(example: Example, firstId = 1): AppState {
  let next = firstId;
  const id = (): string => String(next++);
  const types = example.types.map((t) => ({
    id: id(),
    name: t.name,
    count: String(t.count),
    also: (t.also ?? []).join(", "),
  }));
  const goal = example.goal.map((g) => ({
    id: id(),
    kind: g.kind,
    amount: String(g.amount),
    cardType: g.cardType,
    turn: String(g.turn),
  }));
  return {
    form: {
      deckMode: example.decklist === undefined ? "types" : "list",
      deckSize: String(example.deckSize),
      types,
      decklist: example.decklist ?? "",
      goFirst: example.goFirst,
      drawsPerTurn: "1",
      goal,
      combine: example.combine ?? "all",
      useRule: false,
      rule: "",
      question: "chances",
      drawsType: example.goal[0]?.cardType ?? "",
      lastTurn: "5",
      mulligans: example.mulligan !== undefined,
      keep: (example.mulligan?.keep ?? DEFAULT_KEEP).map((rules): KeepGroupRow => ({
        id: id(),
        rules: rules.map(([cardType, min, max]) => ({
          id: id(),
          cardType,
          min: String(min),
          max: String(max),
        })),
      })),
      protect: (example.mulligan?.protect ?? [["land", 3]]).map(([cardType, upTo]) => ({
        id: id(),
        cardType,
        upTo: String(upTo),
      })),
      maxMulligans: String(example.mulligan?.maxMulligans ?? 2),
      freeFirst: example.mulligan?.freeFirst ?? false,
      hmMode: "one",
      hmAim: "target",
      hmVary: [{ id: id(), cardType: example.types[0]?.name ?? "land", low: "14", high: "40" }],
      hmTarget: "60",
      hmSlots: "20",
    },
    nextId: next,
  };
}

/** The page opens with the first example already answered (FR-97). */
export function initialState(): AppState {
  const first = EXAMPLES[0];
  if (first === undefined) throw new Error("no examples");
  return fromExample(first);
}

/**
 * Fills in "How many should I play?" from the deck and the good game, so the first press
 * gives an answer: the card types the good game counts become the types to try (rows the
 * player already set up for them are kept), with ranges around their step-1 counts, and
 * "cards allowed" starts at their total.
 */
function seedHowMany(form: FormState, mode: HowManyMode, nextId: number): [Partial<FormState>, number] {
  const counts = new Map(form.types.map((t) => [cleanName(t.name), parseWhole(t.count) ?? 0] as const));
  const size = parseWhole(form.deckSize) ?? 60;
  const inGoal = [...new Set(form.goal.map((g) => g.cardType))].filter((n) => counts.has(n));
  const first = cleanName(form.types[0]?.name ?? "");
  const wanted = inGoal.length > 0 ? inGoal : first === "" ? [] : [first];
  const pick = mode === "one" ? wanted.slice(0, 1) : wanted;
  if (pick.length === 0) return [{ hmMode: mode }, 0];
  const total = pick.reduce((sum, n) => sum + (counts.get(n) ?? 0), 0);
  let used = 0;
  const hmVary = pick.map((name): VaryRow => {
    const kept = form.hmVary.find((v) => v.cardType === name);
    if (kept !== undefined) return kept;
    const c = counts.get(name) ?? 0;
    const [low, high] =
      mode === "one" ? [Math.max(0, c - 10), Math.min(size, c + 16)] : [0, Math.min(size, total)];
    used += 1;
    return { id: String(nextId + used - 1), cardType: name, low: String(low), high: String(high) };
  });
  const slots = mode === "share" && total > 0 ? { hmSlots: String(total) } : {};
  return [{ hmMode: mode, hmVary, ...slots }, used];
}

/**
 * Card types a new keep line may start with: the card-type table's names, then the good
 * game's (the only names known without reading a pasted decklist), never "any card".
 */
function keepableNames(form: FormState): string[] {
  const table = form.deckMode === "types" ? form.types.map((t) => cleanName(t.name)) : [];
  const names = [...table, ...form.goal.map((g) => g.cardType)];
  return [...new Set(names)].filter((n) => n !== "" && n !== ANY_CARD);
}

function patchRow<T extends { id: string }>(rows: readonly T[], id: string, patch: Partial<T>): T[] {
  return rows.map((r) => (r.id === id ? { ...r, ...patch } : r));
}

export function reducer(state: AppState, action: Action): AppState {
  const { form } = state;
  const next = (f: Partial<FormState>, used = 0): AppState => ({
    form: { ...form, ...f },
    nextId: state.nextId + used,
  });
  switch (action.type) {
    case "deckSize":
      return next({ deckSize: action.value });
    case "format": {
      const preset = FORMATS[action.name];
      return next({ deckSize: String(preset.size), goFirst: preset.goFirst, freeFirst: preset.freeFirst });
    }
    case "typeChanged": {
      const before = form.types.find((t) => t.id === action.id);
      const types = patchRow<TypeRow>(form.types, action.id, action.patch);
      // Renaming a card type renames it wherever it was chosen, keystroke by keystroke.
      if (before !== undefined && action.patch.name !== undefined) {
        const oldName = cleanName(before.name);
        const newName = cleanName(action.patch.name);
        const stillUsed = form.types.some((t) => t.id !== action.id && cleanName(t.name) === oldName);
        if (oldName !== newName && !stillUsed) {
          const follow = (name: string): string => (name === oldName ? newName : name);
          return next({
            types,
            goal: form.goal.map((g) => ({ ...g, cardType: follow(g.cardType) })),
            protect: form.protect.map((r) => ({ ...r, cardType: follow(r.cardType) })),
            hmVary: form.hmVary.map((r) => ({ ...r, cardType: follow(r.cardType) })),
            keep: form.keep.map((g) => ({
              ...g,
              rules: g.rules.map((r) => ({ ...r, cardType: follow(r.cardType) })),
            })),
            drawsType: follow(form.drawsType),
          });
        }
      }
      return next({ types });
    }
    case "typeAdded":
      return next(
        { types: [...form.types, { id: String(state.nextId), name: "", count: "0", also: "" }] },
        1,
      );
    case "typeRemoved":
      return next({ types: form.types.filter((t) => t.id !== action.id) });
    case "goFirst":
      return next({ goFirst: action.value });
    case "drawsPerTurn":
      return next({ drawsPerTurn: action.value });
    case "goalChanged":
      return next({ goal: patchRow<GoalRow>(form.goal, action.id, action.patch) });
    case "goalAdded": {
      const last = form.goal.at(-1);
      const firstType = cleanName(form.types[0]?.name ?? "") || ANY_CARD;
      const row: GoalRow = {
        id: String(state.nextId),
        kind: "at least",
        amount: "1",
        cardType: last?.cardType ?? firstType,
        turn: last?.turn ?? "0",
      };
      return next({ goal: [...form.goal, row] }, 1);
    }
    case "goalRemoved":
      return next({ goal: form.goal.filter((g) => g.id !== action.id) });
    case "combine":
      return next({ combine: action.value });
    case "load":
      return fromExample(action.example, state.nextId);
    case "deckMode":
      return next({ deckMode: action.value });
    case "decklist":
      return next({ decklist: action.value });
    case "useRule":
      // Ticking the box starts from the lines, written as a rule (if there is no rule yet).
      return next({
        useRule: action.value,
        rule: action.value && form.rule.trim() === "" ? (action.prefill ?? "") : form.rule,
      });
    case "rule":
      return next({ rule: action.value });
    case "question": {
      if (action.value !== "howmany" || form.question === "howmany") return next({ question: action.value });
      const [seed, used] = seedHowMany(form, form.hmMode, state.nextId);
      return next({ question: action.value, ...seed }, used);
    }
    case "drawsType":
      return next({ drawsType: action.value });
    case "lastTurn":
      return next({ lastTurn: action.value });
    case "mulligans":
      return next({ mulligans: action.value });
    case "mulliganChanged":
      return next(action.patch);
    case "keepRuleChanged":
      return next({
        keep: form.keep.map((g) => ({
          ...g,
          rules: patchRow<KeepRuleRow>(g.rules, action.id, action.patch),
        })),
      });
    case "keepRuleAdded": {
      // "And also": a card type this kind of hand does not count yet, at least 1 of it.
      const group = form.keep.find((g) => g.id === action.group);
      if (group === undefined) return state;
      const used = new Set(group.rules.map((r) => r.cardType));
      const name = keepableNames(form).find((t) => !used.has(t)) ?? "";
      const row: KeepRuleRow = { id: String(state.nextId), cardType: name, min: "1", max: "7" };
      return next(
        { keep: form.keep.map((g) => (g.id === action.group ? { ...g, rules: [...g.rules, row] } : g)) },
        1,
      );
    }
    case "keepRuleRemoved":
      return next({
        keep: form.keep
          .map((g) => ({ ...g, rules: g.rules.filter((r) => r.id !== action.id) }))
          .filter((g) => g.rules.length > 0),
      });
    case "keepGroupAdded": {
      // "Or": another kind of hand, starting from the first card type at 2 to 5.
      const name = keepableNames(form)[0] ?? "";
      const group: KeepGroupRow = {
        id: String(state.nextId),
        rules: [{ id: String(state.nextId + 1), cardType: name, min: "2", max: "5" }],
      };
      return next({ keep: [...form.keep, group] }, 2);
    }
    case "protectChanged":
      return next({ protect: patchRow<ProtectRow>(form.protect, action.id, action.patch) });
    case "protectAdded": {
      const used = new Set(form.protect.map((p) => p.cardType));
      const name = form.goal.map((g) => g.cardType).find((t) => !used.has(t)) ?? "";
      return next({ protect: [...form.protect, { id: String(state.nextId), cardType: name, upTo: "1" }] }, 1);
    }
    case "howManyChanged": {
      const mode = action.patch.hmMode;
      if (mode === undefined || mode === form.hmMode) return next(action.patch);
      const [seed, used] = seedHowMany(form, mode, state.nextId);
      return next({ ...seed, ...action.patch }, used);
    }
    case "varyChanged":
      return next({ hmVary: patchRow<VaryRow>(form.hmVary, action.id, action.patch) });
    case "varyAdded": {
      const used = new Set(form.hmVary.map((v) => v.cardType));
      const name = form.types.map((t) => cleanName(t.name)).find((t) => !used.has(t)) ?? "";
      return next(
        { hmVary: [...form.hmVary, { id: String(state.nextId), cardType: name, low: "0", high: "10" }] },
        1,
      );
    }
    case "varyRemoved":
      return next({ hmVary: form.hmVary.filter((v) => v.id !== action.id) });
    case "protectRemoved":
      return next({ protect: form.protect.filter((p) => p.id !== action.id) });
  }
}
