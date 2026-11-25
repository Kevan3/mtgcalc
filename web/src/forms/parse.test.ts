import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { initialState } from "../app/state.ts";
import { testCore } from "../test/core.ts";
import { probability } from "../test/wasm.ts";
import { readReply } from "./answer.ts";
import { ANY_CARD, KINDS, MAX_DECK, type FormState } from "./model.ts";
import {
  cleanName,
  drawsThrough,
  lastPlayableTurn,
  parseForm,
  parseWhole,
  splitAlso,
  typeLabels,
  typeNames,
  type FieldId,
} from "./parse.ts";
import { buildRequest } from "./request.ts";

const base: FormState = initialState().form;

function issues(form: FormState): Record<string, string> {
  const parsed = parseForm(form, testCore);
  return parsed.ok ? {} : Object.fromEntries(parsed.issues.map((i) => [i.field, i.message]));
}

function withType(patch: Partial<FormState["types"][number]>, index = 0): FormState {
  return { ...base, types: base.types.map((t, i) => (i === index ? { ...t, ...patch } : t)) };
}

function withLine(patch: Partial<FormState["goal"][number]>, index = 0): FormState {
  return { ...base, goal: base.goal.map((g, i) => (i === index ? { ...g, ...patch } : g)) };
}

describe("small helpers", () => {
  it("cleans names like Python's split/casefold for keyboard text", () => {
    expect(cleanName("  Mana   ROCK ")).toBe("mana rock");
    expect(splitAlso(" Land, ,REMOVAL ,")).toEqual(["land", "removal"]);
  });

  it("reads whole numbers only", () => {
    expect(parseWhole(" 24 ")).toBe(24);
    for (const bad of ["", "-1", "2.5", "1e3", "twelve", "0x10", "9".repeat(20)]) {
      expect(parseWhole(bad)).toBeNull();
    }
  });

  it("counts draws as the game does (going first skips turn 1)", () => {
    expect(drawsThrough({ goFirst: true, drawsPerTurn: 1 }, 3)).toBe(2);
    expect(drawsThrough({ goFirst: false, drawsPerTurn: 1 }, 3)).toBe(3);
    expect(drawsThrough({ goFirst: false, drawsPerTurn: 2 }, 0)).toBe(0);
  });

  it("knows the last turn a deck has cards for", () => {
    expect(lastPlayableTurn({ goFirst: true, drawsPerTurn: 1 }, 10)).toBe(4); // 7 + 3
    expect(lastPlayableTurn({ goFirst: false, drawsPerTurn: 1 }, 10)).toBe(3);
    expect(lastPlayableTurn({ goFirst: true, drawsPerTurn: 0 }, 7)).toBe(20);
  });

  it("offers types, their 'also' names, then any card", () => {
    expect(
      typeNames([
        { name: "MDFC", also: "land, removal" },
        { name: "land", also: "" },
      ]),
    ).toEqual(["mdfc", "land", "removal", ANY_CARD]);
  });
});

describe("labels and notes", () => {
  it("shows names as first typed, matched without regard to case", () => {
    expect(
      typeLabels([
        { name: " Lightning   Bolt ", also: "LAND, Mana Rock" },
        { name: "land", also: "" },
      ]),
    ).toEqual({
      "lightning bolt": "Lightning Bolt",
      land: "LAND",
      "mana rock": "Mana Rock",
    });
  });

  it("notes 'also counts as' names that are not card types, without blocking", () => {
    const form = {
      ...base,
      types: base.types.map((t, i) => (i === 0 ? { ...t, also: "removal, land ramp, ramp" } : t)),
    };
    const parsed = parseForm(form, testCore);
    expect(parsed.ok).toBe(true);
    expect(parsed.notes.map((n) => n.message)).toEqual([
      "“land ramp” and “ramp” are not in your list of card types, so they become new types. To use several types, separate them with commas.",
    ]);
  });
});

describe("parseForm", () => {
  it("accepts the opening example", () => {
    const parsed = parseForm(base, testCore);
    expect(parsed.ok).toBe(true);
  });

  it.each([
    ["", "Enter how many cards are in your deck."],
    ["sixty", "Use a whole number, like 60."],
    ["0", "A deck needs at least 7 cards, enough for an opening hand."],
    ["6", "A deck needs at least 7 cards, enough for an opening hand."],
    [String(MAX_DECK + 1), `Use ${MAX_DECK} cards or fewer.`],
  ])("explains a bad deck size %j", (deckSize, message) => {
    expect(issues({ ...base, deckSize })["deckSize"]).toBe(message);
  });

  it("explains card-type names", () => {
    const id = base.types[0]?.id ?? "";
    expect(issues(withType({ name: " " }))[`type:${id}:name`]).toMatch(/Give this card type a name/u);
    expect(issues(withType({ name: "Any Card" }))[`type:${id}:name`]).toMatch(/calculator uses/u);
    expect(issues(withType({ name: "(other)" }))[`type:${id}:name`]).toMatch(/calculator uses/u);
    const second = base.types[1]?.id ?? "";
    expect(issues(withType({ name: "LAND" }, 1))[`type:${second}:name`]).toBe(
      "You already have a card type called “land”.",
    );
    expect(issues(withType({ also: "land, any card" }))[`type:${id}:also`]).toMatch(/calculator uses/u);
  });

  it("explains counts and totals", () => {
    const id = base.types[0]?.id ?? "";
    expect(issues(withType({ count: "-2" }))[`type:${id}:count`]).toBe("Use a whole number, 0 or more.");
    expect(issues(withType({ count: "70" }))["types"]).toBe(
      "Your card types add up to 76 cards, but your deck has 60. Lower a number or raise the deck size.",
    );
  });

  it("explains draws", () => {
    expect(issues({ ...base, drawsPerTurn: "11" })["drawsPerTurn"]).toMatch(/from 0 to 10/u);
    expect(issues({ ...base, drawsPerTurn: "" })["drawsPerTurn"]).toMatch(/usually 1/u);
  });

  it("explains goal lines", () => {
    const id = base.goal[0]?.id ?? "";
    expect(issues(withLine({ amount: "x" }))[`goal:${id}:amount`]).toBe("Use a whole number, 0 or more.");
    expect(issues(withLine({ kind: "none", amount: "x" }))).toEqual({}); // no amount for "no"
    expect(issues(withLine({ cardType: "ramp" }))[`goal:${id}:cardType`]).toBe(
      "Pick a card type from the list.",
    );
    expect(issues(withLine({ turn: "99" }))[`goal:${id}:turn`]).toBe("Pick a turn from the list.");
    expect(
      issues({ ...base, deckSize: "10", goal: base.goal.map((g) => ({ ...g, turn: "6" })) })[
        `goal:${id}:turn`
      ],
    ).toBe("Your deck runs out of cards after turn 4. Pick turn 4 or earlier.");
    expect(issues({ ...base, goal: [] })["goal"]).toMatch(/Add a line/u);
  });

  describe("How many should I play?", () => {
    const hm: FormState = { ...base, question: "howmany" };
    const share: FormState = {
      ...hm,
      hmMode: "share",
      hmVary: [
        { id: "v1", cardType: "land", low: "14", high: "30" },
        { id: "v2", cardType: "removal", low: "2", high: "8" },
      ],
      hmSlots: "30",
    };
    const question = (form: FormState) => {
      const parsed = parseForm(form, testCore);
      return parsed.ok ? parsed.setup.question : undefined;
    };

    it("needs a target only when aiming for one", () => {
      expect(issues({ ...hm, hmTarget: "x" })["hmTarget"]).toMatch(/Choose a target/u);
      expect(issues({ ...hm, hmAim: "best", hmTarget: "x" })).toEqual({});
      expect(question({ ...hm, hmAim: "best" })).toMatchObject({ mode: "one", aim: "best", room: 54 });
    });

    it("checks that the 'from' numbers fit next to the card types that stay", () => {
      const tooMany = { ...hm, hmVary: [{ id: "v1", cardType: "land", low: "55", high: "58" }] };
      expect(issues(tooMany)["howmany"]).toBe(
        "The 'from' numbers add up to 55 cards, but your other card types leave room for only 54.",
      );
      expect(issues({ ...tooMany, hmAim: "best" })["howmany"]).toMatch(/room for only 54/u);
    });

    it("checks the cards allowed when sharing, with either aim", () => {
      expect(question(share)).toMatchObject({ mode: "share", aim: "target", slots: 30, room: 60 });
      for (const hmAim of ["best", "target"] as const) {
        expect(issues({ ...share, hmAim, hmSlots: "10" })["hmSlots"]).toBe(
          "The 'from' numbers add up to 16 cards, more than the 10 allowed.",
        );
        expect(issues({ ...share, hmAim, hmSlots: "61" })["hmSlots"]).toMatch(/more than the 60 cards/u);
        expect(issues({ ...share, hmAim, hmSlots: "" })["hmSlots"]).toMatch(/whole number/u);
      }
      // A single card type ignores the cards allowed.
      expect(issues({ ...hm, hmSlots: "" })).toEqual({});
    });
  });

  it("reports every problem at once, each in its own place", () => {
    const fields = Object.keys(issues({ ...base, deckSize: "", drawsPerTurn: "x", goal: [] })) as FieldId[];
    expect(fields.sort()).toEqual(["deckSize", "drawsPerTurn", "goal"]);
  });
});

describe("whatever the form accepts, the engine accepts (property)", () => {
  const name = fc.constantFrom("land", "Ramp", " card  draw ", "removal", "Mana Rock", "bomb");
  const form = fc
    .record({
      // Small decks are where the edge cases are (fewer cards than an opening hand, ...).
      deckSize: fc.oneof(fc.integer({ min: 1, max: 12 }), fc.integer({ min: 1, max: 120 })),
      types: fc.array(
        fc.record({
          name,
          count: fc.integer({ min: 0, max: 40 }),
          also: fc.subarray(["land", "ramp", "draw"]),
        }),
        { maxLength: 4 },
      ),
      goFirst: fc.boolean(),
      draws: fc.integer({ min: 0, max: 3 }),
      lines: fc.array(
        fc.record({
          kind: fc.constantFrom(...KINDS),
          amount: fc.integer({ min: 0, max: 8 }),
          pick: fc.nat(),
          turn: fc.integer({ min: 0, max: 20 }),
        }),
        { minLength: 1, maxLength: 3 },
      ),
      combine: fc.constantFrom("all" as const, "any" as const),
    })
    .map((r): FormState => {
      const types = r.types.map((t, i) => ({
        id: `t${i}`,
        name: t.name,
        count: String(t.count),
        also: t.also.join(", "),
      }));
      const names = typeNames(types);
      return {
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
        protect: [],
        maxMulligans: "2",
        freeFirst: false,
        hmMode: "one",
        hmAim: "target",
        hmVary: [],
        hmTarget: "90",
        hmSlots: "20",
        deckSize: String(r.deckSize),
        types,
        goFirst: r.goFirst,
        drawsPerTurn: String(r.draws),
        goal: r.lines.map((l, i) => ({
          id: `g${i}`,
          kind: l.kind,
          amount: String(l.amount),
          cardType: names[l.pick % names.length] ?? ANY_CARD,
          turn: String(l.turn),
        })),
        combine: r.combine,
      };
    });

  it("gives an answer between 0 and 1 for every form it accepts", () => {
    let accepted = 0;
    fc.assert(
      fc.property(form, (f) => {
        const parsed = parseForm(f, testCore);
        if (!parsed.ok) return;
        accepted += 1;
        const reply = probability(JSON.stringify(buildRequest(parsed.setup)));
        const view = readReply(parsed.setup.goal, reply);
        expect(view.kind, reply).toBe("answer");
        if (view.kind === "answer") expect(view.probability.num <= view.probability.den).toBe(true);
      }),
      { numRuns: 400 },
    );
    expect(accepted).toBeGreaterThan(50); // the generator must exercise the happy path
  });
});
