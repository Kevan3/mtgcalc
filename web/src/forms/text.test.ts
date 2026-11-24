import { describe, expect, it } from "vitest";

import { deckSummary } from "../components/DecklistInput.tsx";
import { testCore } from "../test/core.ts";
import { readDecklist, readRule, ruleText } from "./text.ts";

function deckProblem(text: string): string {
  const read = readDecklist(testCore, text);
  return read.ok ? "" : read.message;
}

function ruleProblem(text: string): string {
  const read = readRule(testCore, text);
  return read.ok ? "" : read.message;
}

describe("pasted decklists", () => {
  it("reads cards, tags and the commander", () => {
    const read = readDecklist(
      testCore,
      "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n36 Forest #land\n2 Bridge #land #ramp\n10 Elf #ramp\n50 Bear\n",
    );
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect(read.value.size).toBe(98);
    expect(read.value.tags).toEqual([
      ["land", 38],
      ["ramp", 12],
    ]);
    expect(read.value.commanders).toEqual(["Atraxa, Praetors' Voice"]);
    expect(deckSummary(read.value)).toBe(
      "Read 98 cards in the deck; commander: Atraxa, Praetors' Voice. Tags: land 38, ramp 12.",
    );
  });

  it("suggests tags when there are none", () => {
    const read = readDecklist(testCore, "60 Forest");
    expect(read.ok && deckSummary(read.value)).toBe(
      "Read 60 cards in the deck. No #tags yet: add some to ask about kinds of cards.",
    );
  });

  it.each([
    ["", "Paste your decklist: one card per line, like “4 Lightning Bolt”."],
    ["4 Forest\nLightning Bolt", "Line 2: start the line with how many copies, like “4 Lightning Bolt”."],
    ["0 Forest", "Line 1: the number of copies must be 1 or more."],
    ["4 #land", "Line 1: a card name is missing after the number."],
    ["Commander\n1 Atraxa", "Your decklist has no cards in the main deck (only a commander or sideboard)."],
    ["70000 Forest", "This deck has more cards than the calculator can handle."],
  ])("explains %j in plain words", (text, message) => {
    expect(deckProblem(text)).toBe(message);
  });
});

describe("typed rules", () => {
  it("reads a rule into a condition", () => {
    const read = readRule(testCore, "land >= 3 @T3");
    expect(read.ok && read.value.condition).toMatchObject({ type: "At", turn: 3 });
  });

  it.each([
    ["", "Type a rule, or untick the box to use the lines above."],
    ["land >=", "At character 8: a number should come here (the rule ended too soon)."],
    ["land ! 3", "At character 6: “!” cannot be used in a rule."],
    ["land 3", "At character 6: a comparison such as >= should come here."],
    ["(land >= 3", "At character 11: a closing bracket “)” is missing (the rule ended too soon)."],
    ["land >= 3 @x", "At character 12: write a turn after @, as in @T3."],
    ["and >= 1", 'At character 1: “and” is a special word. To use it as a card type, write tag:"and".'],
    ["land >= 3 ramp", "At character 11: “ramp” does not fit here."],
    [
      "land in 4..2",
      "At character 13: the first number of a range must not be bigger than the second (the rule ended too soon).",
    ],
    ["a >= 1 GIVEN b >= 1", "GIVEN cannot be used here: describe one good game."],
    ["assign(land 3)", "At character 13: write >= here, as in assign(land >= 3, ramp >= 1)."],
    ["atleast 2", "At character 9: an opening bracket “(” should come here."],
    ["card Sol", 'At character 6: write a colon here, as in card:"Sol Ring".'],
    ["card:Sol >= 1", 'At character 6: a name in double quotes should come here, as in card:"Sol Ring".'],
    ["land in 2 4", "At character 11: write a range as 2..4."],
    [">= 3", "At character 1: a card type should come here."],
    ["assign(land >= 0)", "At character 17: each part of assign(...) needs at least 1 card."],
    [
      "atleast(1)",
      "At character 11: atleast(...) needs at least one condition after the number (the rule ended too soon).",
    ],
    ['tag:"" >= 1', "At character 8: a card type name cannot be empty."],
    ['card:" " >= 1', "At character 10: a card name cannot be empty."],
    ["(".repeat(70) + "a >= 1" + ")".repeat(70), "At character 65: too many brackets inside each other."],
    ["x".repeat(10_001), "This rule is too long."],
  ])("explains %j in plain words", (text, message) => {
    expect(ruleProblem(text)).toBe(message);
  });

  it("writes conditions back as rules (to start the rule box from the lines)", () => {
    const condition = {
      type: "And",
      items: [
        {
          type: "At",
          turn: 3,
          item: { type: "Compare", sel: { type: "Tag", name: "land" }, op: ">=", value: 3 },
        },
        { type: "At", turn: 0, item: { type: "Compare", sel: { type: "Everything" }, op: "==", value: 7 } },
      ],
    };
    expect(ruleText(testCore, condition)).toBe("land >= 3 @T3 AND everything == 7 @T0");
    expect(ruleText(testCore, { type: "Nonsense" })).toBeNull();
  });
});
