import { describe, expect, it } from "vitest";

import { EXAMPLES, fromExample, initialState, reducer, type AppState } from "./state.ts";

const start = initialState();
const landId = start.form.types[0]?.id ?? "";

function apply(state: AppState, ...actions: Parameters<typeof reducer>[1][]): AppState {
  return actions.reduce(reducer, state);
}

describe("reducer", () => {
  it("opens with the first example", () => {
    expect(start.form.deckSize).toBe("60");
    expect(start.form.goal.map((g) => g.cardType)).toEqual(["land", "removal"]);
  });

  it("applies format presets", () => {
    const s = apply(start, { type: "format", name: "Commander" });
    expect([s.form.deckSize, s.form.goFirst]).toEqual(["99", false]);
  });

  it("renames a card type everywhere it was chosen", () => {
    const s = apply(
      start,
      { type: "drawsType", value: "land" },
      { type: "typeChanged", id: landId, patch: { name: "Forest" } },
    );
    expect(s.form.goal[0]?.cardType).toBe("forest");
    expect(s.form.protect[0]?.cardType).toBe("forest");
    expect(s.form.hmVary[0]?.cardType).toBe("forest");
    expect(s.form.keep[0]?.rules[0]?.cardType).toBe("forest");
    expect(s.form.drawsType).toBe("forest");
  });

  it("fills in 'How many should I play?' from the good game, so the first press answers", () => {
    let s = apply(start, { type: "question", value: "howmany" });
    expect(s.form.hmVary.map((v) => [v.cardType, v.low, v.high])).toEqual([["land", "14", "40"]]);
    s = apply(s, { type: "howManyChanged", patch: { hmMode: "share" } });
    // The land row the player had is kept; removal is added around its step-1 count.
    expect(s.form.hmVary.map((v) => [v.cardType, v.low, v.high])).toEqual([
      ["land", "14", "40"],
      ["removal", "0", "30"],
    ]);
    expect(s.form.hmSlots).toBe("30");
    // Choosing the aim changes nothing else.
    const rows = s.form.hmVary;
    s = apply(s, { type: "howManyChanged", patch: { hmAim: "best" } });
    expect([s.form.hmAim, s.form.hmVary, s.form.hmSlots]).toEqual(["best", rows, "30"]);
    s = apply(s, { type: "howManyChanged", patch: { hmMode: "one" } });
    expect(s.form.hmVary.map((v) => v.cardType)).toEqual(["land"]);
    expect(s.form.hmAim).toBe("best");
    // Choosing the same mode again, or a target, changes nothing else.
    expect(apply(s, { type: "howManyChanged", patch: { hmMode: "one", hmTarget: "70" } }).form.hmVary).toBe(
      s.form.hmVary,
    );
  });

  it("fills in fresh ranges for card types not tried yet", () => {
    const s = apply(
      start,
      { type: "howManyChanged", patch: { hmMode: "share" } },
      { type: "question", value: "howmany" },
    );
    expect(s.form.hmVary.map((v) => [v.cardType, v.low, v.high])).toEqual([
      ["land", "14", "40"],
      ["removal", "0", "30"],
    ]);
    expect(new Set(s.form.hmVary.map((v) => v.id)).size).toBe(2);
  });

  it("uses the first card type when the good game names none, and leaves rows alone without types", () => {
    const anyGoal = apply(start, {
      type: "goalChanged",
      id: start.form.goal[0]?.id ?? "",
      patch: { cardType: "any card" },
    });
    const noRemoval = apply(anyGoal, { type: "goalRemoved", id: start.form.goal[1]?.id ?? "" });
    const s = apply(noRemoval, { type: "howManyChanged", patch: { hmMode: "share" } });
    expect(s.form.hmVary.map((v) => v.cardType)).toEqual(["land"]);
    expect(s.form.hmSlots).toBe("24");
    const empty = { ...start, form: { ...start.form, types: [], hmVary: [] } };
    const t = apply(empty, { type: "howManyChanged", patch: { hmMode: "share" } });
    expect([t.form.hmMode, t.form.hmVary]).toEqual(["share", []]);
  });

  it("chooses card counts: rows can be added, changed and removed", () => {
    // A value given with the change wins over the filled-in one.
    let s = apply(start, { type: "howManyChanged", patch: { hmMode: "share", hmSlots: "26" } });
    expect([s.form.hmMode, s.form.hmSlots]).toEqual(["share", "26"]);
    s = apply(s, { type: "varyAdded" });
    expect(s.form.hmVary[2]?.cardType).toBe("");
    const second = s.form.hmVary[1]?.id ?? "";
    s = apply(s, { type: "varyChanged", id: second, patch: { low: "2", high: "6" } });
    expect(s.form.hmVary[1]).toMatchObject({ low: "2", high: "6" });
    s = apply(s, { type: "varyRemoved", id: second });
    expect(s.form.hmVary.map((v) => v.id)).not.toContain(second);
  });

  it("builds kinds of hand to keep: and-lines, or-kinds, edits and removal", () => {
    const kind1 = start.form.keep[0]?.id ?? "";
    let s = apply(start, { type: "keepRuleAdded", group: kind1 });
    // "And also" starts with a card type this kind does not count yet, at least 1 of it.
    expect(s.form.keep[0]?.rules.map((r) => [r.cardType, r.min, r.max])).toEqual([
      ["land", "2", "5"],
      ["removal", "1", "7"],
    ]);
    const added = s.form.keep[0]?.rules[1]?.id ?? "";
    expect(added).toBe(String(start.nextId));
    s = apply(s, { type: "keepRuleChanged", id: added, patch: { min: "0", max: "2" } });
    expect(s.form.keep[0]?.rules[1]).toMatchObject({ min: "0", max: "2" });
    s = apply(s, { type: "keepGroupAdded" });
    expect(s.form.keep).toHaveLength(2);
    expect(s.form.keep[1]?.rules.map((r) => [r.cardType, r.min, r.max])).toEqual([["land", "2", "5"]]);
    expect(new Set([s.form.keep[1]?.id, s.form.keep[1]?.rules[0]?.id]).size).toBe(2);
    expect(s.nextId).toBe(start.nextId + 3);
    // Removing a kind's last line removes the kind; none left means "always keep".
    s = apply(s, { type: "keepRuleRemoved", id: s.form.keep[1]?.rules[0]?.id ?? "" });
    expect(s.form.keep).toHaveLength(1);
    s = apply(s, { type: "keepRuleRemoved", id: added });
    expect(s.form.keep[0]?.rules).toHaveLength(1);
    s = apply(s, { type: "keepRuleRemoved", id: s.form.keep[0]?.rules[0]?.id ?? "" });
    expect(s.form.keep).toEqual([]);
    // An unknown kind changes nothing.
    expect(apply(s, { type: "keepRuleAdded", group: "nope" })).toBe(s);
  });

  it("starts new keep lines from the good game's types with a pasted decklist", () => {
    let s = apply(start, { type: "deckMode", value: "list" }, { type: "keepGroupAdded" });
    expect(s.form.keep[1]?.rules[0]?.cardType).toBe("land");
    s = apply(start, {
      type: "goalChanged",
      id: start.form.goal[0]?.id ?? "",
      patch: { cardType: "any card" },
    });
    s = apply(s, { type: "deckMode", value: "list" }, { type: "goalRemoved", id: s.form.goal[1]?.id ?? "" });
    s = apply(s, { type: "keepGroupAdded" });
    expect(s.form.keep[1]?.rules[0]?.cardType).toBe(""); // never "any card": the player picks
  });

  it("loads kinds of hand from an example", () => {
    const commander = EXAMPLES.find((e) => e.title.startsWith("Commander"));
    if (commander === undefined) throw new Error("no Commander example");
    const s = fromExample(commander);
    expect(s.form.keep.map((g) => g.rules.map((r) => [r.cardType, r.min, r.max]))).toEqual([
      [["land", "3", "5"]],
      [
        ["land", "2", "2"],
        ["ramp", "1", "7"],
      ],
    ]);
  });

  it("renames goal lines along with a card type, keystroke by keystroke", () => {
    let s = start;
    for (const name of ["lan", "la", "", "M", "Mana", "Mana rock"]) {
      s = apply(s, { type: "typeChanged", id: landId, patch: { name } });
    }
    expect(s.form.goal[0]?.cardType).toBe("mana rock");
    expect(s.form.goal[1]?.cardType).toBe("removal");
  });

  it("does not rename lines when another type still has the old name", () => {
    const s = apply(
      start,
      { type: "typeChanged", id: start.form.types[1]?.id ?? "", patch: { name: "land" } },
      { type: "typeChanged", id: landId, patch: { name: "forest" } },
    );
    expect(s.form.goal[0]?.cardType).toBe("land");
  });

  it("adds rows with fresh ids and sensible defaults", () => {
    const s = apply(start, { type: "typeAdded" }, { type: "goalAdded" });
    const ids = [...s.form.types, ...s.form.goal].map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(s.form.types.at(-1)).toMatchObject({ name: "", count: "0", also: "" });
    expect(s.form.goal.at(-1)).toMatchObject({
      kind: "at least",
      amount: "1",
      cardType: "removal",
      turn: "3",
    });
  });

  it("a first goal line uses the first card type", () => {
    const empty = apply(start, ...start.form.goal.map((g) => ({ type: "goalRemoved" as const, id: g.id })));
    expect(apply(empty, { type: "goalAdded" }).form.goal[0]).toMatchObject({ cardType: "land", turn: "0" });
  });

  it("removes rows and edits fields", () => {
    const s = apply(
      start,
      { type: "typeRemoved", id: landId },
      { type: "deckSize", value: "40" },
      { type: "goFirst", value: false },
      { type: "drawsPerTurn", value: "2" },
      { type: "combine", value: "any" },
      { type: "goalChanged", id: start.form.goal[0]?.id ?? "", patch: { kind: "none" } },
    );
    expect(s.form.types.map((t) => t.name)).toEqual(["removal"]);
    expect([s.form.deckSize, s.form.goFirst, s.form.drawsPerTurn, s.form.combine]).toEqual([
      "40",
      false,
      "2",
      "any",
    ]);
    expect(s.form.goal[0]?.kind).toBe("none");
  });

  it("loads examples without reusing ids", () => {
    const commander = EXAMPLES.find((e) => e.title.startsWith("Commander"));
    if (commander === undefined) throw new Error("missing example");
    const s = apply(start, { type: "load", example: commander });
    expect(s.form.types.find((t) => t.name === "land and removal")?.also).toBe("land, removal");
    const before = new Set([...start.form.types, ...start.form.goal].map((r) => r.id));
    expect([...s.form.types, ...s.form.goal].some((r) => before.has(r.id))).toBe(false);
    expect(fromExample(commander).form.goFirst).toBe(false);
  });

  it("switches deck mode, edits the decklist and the rule", () => {
    const s = apply(start, { type: "deckMode", value: "list" }, { type: "decklist", value: "60 Forest" });
    expect([s.form.deckMode, s.form.decklist]).toEqual(["list", "60 Forest"]);
    expect(apply(s, { type: "rule", value: "land >= 1" }).form.rule).toBe("land >= 1");
  });

  it("starts the rule box from the lines once, and keeps a rule already written", () => {
    const on = apply(start, { type: "useRule", value: true, prefill: "land >= 3 @T3" });
    expect([on.form.useRule, on.form.rule]).toEqual([true, "land >= 3 @T3"]);
    const edited = apply(on, { type: "rule", value: "ramp >= 1" }, { type: "useRule", value: false });
    expect(edited.form.rule).toBe("ramp >= 1");
    const again = apply(edited, { type: "useRule", value: true, prefill: "other" });
    expect(again.form.rule).toBe("ramp >= 1");
    expect(apply(start, { type: "useRule", value: true }).form.rule).toBe("");
  });

  it("loads the decklist example", () => {
    const example = EXAMPLES.find((e) => e.decklist !== undefined);
    if (example === undefined) throw new Error("no decklist example");
    const s = apply(start, { type: "load", example });
    expect(s.form.deckMode).toBe("list");
    expect(s.form.decklist).toContain("#ramp");
  });
});
