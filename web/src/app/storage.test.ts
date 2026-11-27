import { describe, expect, it } from "vitest";

import { goalRows } from "../forms/model.ts";
import { initialState } from "./state.ts";
import { isAppState, loadState, saveState, STORAGE_KEY } from "./storage.ts";

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => {
      data[k] = v;
    },
  };
}

describe("storage", () => {
  it("round-trips the app state", () => {
    const store = memory();
    saveState(initialState(), store);
    expect(loadState(store)).toEqual(initialState());
  });

  it.each([
    ["nothing saved", undefined],
    ["not JSON", "{oops"],
    ["wrong shape", JSON.stringify({ form: { deckSize: 60 }, nextId: 3 })],
    [
      "bad row",
      JSON.stringify({
        ...initialState(),
        form: { ...initialState().form, goal: [{ id: "1", rules: [{ id: "2", kind: "maybe" }] }] },
      }),
    ],
    ["bad id counter", JSON.stringify({ ...initialState(), nextId: -1 })],
    [
      "huge list",
      JSON.stringify({
        ...initialState(),
        form: { ...initialState().form, types: Array(51).fill({ id: "x", name: "", count: "0", also: "" }) },
      }),
    ],
  ])("ignores %s", (_, text) => {
    const store = memory(text === undefined ? {} : { [STORAGE_KEY]: text });
    expect(loadState(store)).toBeNull();
  });

  it("never throws when storage is blocked or full", () => {
    const blocked = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    };
    expect(loadState(blocked)).toBeNull();
    expect(() => {
      saveState(initialState(), blocked);
    }).not.toThrow();
    expect(isAppState(null)).toBe(false);
  });

  it("upgrades a setup saved by the first version (before decklists and rules)", () => {
    const old = { ...initialState(), form: { ...initialState().form } } as Record<string, unknown>;
    const form = old["form"] as Record<string, unknown>;
    for (const key of ["deckMode", "decklist", "useRule", "rule"]) Reflect.deleteProperty(form, key);
    const store = memory({ [STORAGE_KEY]: JSON.stringify(old) });
    expect(loadState(store)?.form).toMatchObject({
      deckMode: "types",
      decklist: "",
      useRule: false,
      rule: "",
    });
  });

  it.each([
    ["need", { hmMode: "one", hmAim: "target", hmSlots: "20" }],
    ["split", { hmMode: "share", hmAim: "best", hmSlots: "20" }],
    // "fewest" had no limit on the cards: it may use the whole deck.
    ["fewest", { hmMode: "share", hmAim: "target", hmSlots: "60" }],
  ])("upgrades the old how-many mode %s to a mode and an aim", (old, expected) => {
    const saved = { ...initialState(), form: { ...initialState().form, hmMode: old } } as Record<
      string,
      unknown
    >;
    Reflect.deleteProperty(saved["form"] as Record<string, unknown>, "hmAim");
    expect(loadState(memory({ [STORAGE_KEY]: JSON.stringify(saved) }))?.form).toMatchObject(expected);
  });

  it.each([
    [
      "one line",
      { keepType: "removal", keepMin: "1", keepMax: "3" },
      [{ id: "k1", rules: [{ id: "k2", cardType: "removal", min: "1", max: "3" }] }],
    ],
    ["“keep any hand”", { keepType: "", keepMin: "2", keepMax: "5" }, []],
  ])("upgrades a keep rule saved as %s to kinds of hand", (_, old, keep) => {
    const form = { ...initialState().form, ...old } as Record<string, unknown>;
    Reflect.deleteProperty(form, "keep");
    const loaded = loadState(memory({ [STORAGE_KEY]: JSON.stringify({ ...initialState(), form }) }));
    expect(loaded?.form.keep).toEqual(keep);
    expect(loaded?.form).not.toHaveProperty("keepType");
  });

  it.each([
    ["all", [{ id: "g1", rules: ["A", "B"] }]],
    [
      "any",
      [
        { id: "g1", rules: ["A"] },
        { id: "g2", rules: ["B"] },
      ],
    ],
  ])("upgrades good-game lines saved with “%s” to kinds of good game", (combine, expected) => {
    const lines = goalRows(initialState().form);
    const form = { ...initialState().form, goal: lines, combine } as Record<string, unknown>;
    const loaded = loadState(memory({ [STORAGE_KEY]: JSON.stringify({ ...initialState(), form }) }));
    const byName = { A: lines[0], B: lines[1] };
    expect(loaded?.form.goal).toEqual(
      expected.map((g) => ({ id: g.id, rules: g.rules.map((n) => byName[n as "A" | "B"]) })),
    );
    expect(loaded?.form).not.toHaveProperty("combine");
  });

  it("drops an empty old good game, which then asks for a line", () => {
    const form = { ...initialState().form, goal: [], combine: "all" } as Record<string, unknown>;
    const loaded = loadState(memory({ [STORAGE_KEY]: JSON.stringify({ ...initialState(), form }) }));
    expect(loaded?.form.goal).toEqual([]);
  });

  it("gives a setup saved before mulligans the default keep rule", () => {
    const form = { ...initialState().form } as Record<string, unknown>;
    Reflect.deleteProperty(form, "keep");
    const loaded = loadState(memory({ [STORAGE_KEY]: JSON.stringify({ ...initialState(), form }) }));
    expect(loaded?.form.keep).toEqual([
      { id: "k1", rules: [{ id: "k2", cardType: "land", min: "2", max: "5" }] },
    ]);
  });

  it.each([
    ["an unknown how-many mode", { hmMode: "fewest-ish" }],
    ["a kind of hand with no lines", { keep: [{ id: "k1", rules: [] }] }],
    ["a kind of good game with no lines", { goal: [{ id: "g1", rules: [] }] }],
    ["a kind of good game with a bad line", { goal: [{ id: "g1", rules: [{ id: "1", kind: "maybe" }] }] }],
    ["an old good game that is not a list", { goal: "land", combine: "all" }],
    ["a kind of hand that is not an object", { keep: ["land"] }],
    ["a kind of hand without lines", { keep: [{ id: "k1" }] }],
    ["a bad keep line", { keep: [{ id: "k1", rules: [{ id: "k2", cardType: "land", min: 2, max: "5" }] }] }],
    ["a keep line that is not an object", { keep: [{ id: "k1", rules: [null] }] }],
    ["an old keep rule that is not text", { keep: "land", keepType: 3 }],
    ["an unknown how-many aim", { hmAim: "most" }],
    ["a bad keep-first row", { protect: [{ id: "1", cardType: 3, upTo: "1" }] }],
    ["a keep-first row that is not an object", { protect: ["land"] }],
    ["an unknown question", { question: "optimize" }],
    ["a type row that is not an object", { types: [null] }],
    ["a goal row that is not an object", { goal: [1] }],
  ])("ignores a saved setup with %s", (_, patch) => {
    const state = { ...initialState(), form: { ...initialState().form, ...patch } };
    expect(loadState(memory({ [STORAGE_KEY]: JSON.stringify(state) }))).toBeNull();
  });

  it("ignores saved data without a form", () => {
    expect(loadState(memory({ [STORAGE_KEY]: JSON.stringify({ nextId: 3 }) }))).toBeNull();
    expect(loadState(memory({ [STORAGE_KEY]: JSON.stringify(7) }))).toBeNull();
    expect(loadState(memory({ [STORAGE_KEY]: JSON.stringify({ form: 1, nextId: 3 }) }))).toBeNull();
  });
});
