import { describe, expect, it } from "vitest";

import { readReply } from "./answer.ts";
import type { Goal } from "./model.ts";
import { exactWords, parseFraction, pct, roundHalfEven } from "./words.ts";

const goal: Goal = {
  groups: [[{ kind: "at least", amount: 1, cardType: "any card", turn: 0 }]],
};

describe("readReply", () => {
  it("puts an answer into words", () => {
    const view = readReply(
      goal,
      JSON.stringify({ type: "Probability", exact: { type: "Fraction", value: "1/1" } }),
    );
    expect(view).toMatchObject({
      kind: "answer",
      headline: "You have at least 1 card in your opening hand in 100.0% of games (every game).",
    });
  });

  it.each([
    ["too_large", "This question is too big to work out exactly."],
    ["unsupported", "This question goes beyond what the calculator can do yet."],
    ["validation", "The calculator could not use this setup."],
    ["internal", "Something went wrong inside the calculator."],
    ["malformed", "Something went wrong inside the calculator."],
  ])("explains a %s error in plain words, keeping details apart", (kind, headline) => {
    const view = readReply(
      goal,
      JSON.stringify({ type: "Error", kind, field: "game", message: "technical text" }),
    );
    expect(view.kind).toBe("problem");
    expect(view.headline).toBe(headline);
    if (view.kind === "problem") {
      expect(view.advice).not.toContain("technical");
      expect(view.details).toBe(`${kind}: game: technical text`);
    }
  });

  it.each([
    "not json",
    "[]",
    "{}",
    '{"type": "Probability"}',
    '{"type": "Probability", "exact": {"value": "1/0"}}',
  ])("never breaks on an odd reply: %s", (reply) => {
    expect(readReply(goal, reply).kind).toBe("problem");
  });
});

describe("exact arithmetic", () => {
  it("rounds ties to even", () => {
    expect([
      roundHalfEven(5n, 2n),
      roundHalfEven(7n, 2n),
      roundHalfEven(1n, 3n),
      roundHalfEven(2n, 3n),
    ]).toEqual([2n, 4n, 0n, 1n]);
  });

  it("never loses precision on huge fractions", () => {
    const den = 10n ** 40n;
    expect(pct({ num: den / 2n, den })).toBe("50.0%");
    expect(pct({ num: den - 1n, den })).toBe("100.000%");
  });

  it("writes exact numbers to four decimals and as a fraction", () => {
    expect(exactWords(parseFraction("38962/97527"))).toEqual({
      precise: "39.9500%",
      fraction: "38,962 / 97,527",
    });
    expect(() => parseFraction("1/0")).toThrow();
    expect(() => parseFraction("-1/2")).toThrow();
  });
});

describe("odd replies to table and mulligan questions", () => {
  const draws = { goal, question: { kind: "draws" as const, cardType: "any card", lastTurn: 1 } };
  const turns = { goal, question: { kind: "turns" as const, lastTurn: 1 } };
  const advice = { goal, question: { kind: "mulligan" as const } };
  const f = (value: string) => ({ type: "Fraction", value });

  it.each([
    [draws, { type: "Probability", exact: f("1/2") }],
    [draws, { type: "Distributions" }],
    [draws, { type: "Distributions", items: [{ turn: "x", pmf: [] }] }],
    [draws, { type: "Distributions", items: [{ turn: 0, pmf: [{ value: "1/0" }] }] }],
    [draws, { type: "Distributions", items: [] }],
    [turns, { type: "TurnTable" }],
    [turns, { type: "TurnTable", rows: [{ turn: 0, cards_seen: 7, probability: { value: "x" } }] }],
    [turns, { type: "TurnTable", rows: [7] }],
    [advice, { type: "MulliganAdvice" }],
    [advice, { type: "MulliganAdvice", report: { rows: [] }, best: { rows: [] } }],
    [
      advice,
      {
        type: "MulliganAdvice",
        report: {
          rows: [{ depth: 0, hand_size: 7 }],
          p_success: f("1/2"),
          expected_mulligans: f("0/1"),
          expected_hand_size: f("7/1"),
        },
        best: { rows: [], value: f("1/2"), atoms: [] },
      },
    ],
    [
      advice,
      {
        type: "MulliganAdvice",
        report: { rows: [], p_success: f("1/2"), expected_mulligans: f("0/1"), expected_hand_size: f("7/1") },
        best: { rows: [], value: f("1/2"), atoms: [] },
      },
    ],
    [
      advice,
      {
        type: "MulliganAdvice",
        report: {
          rows: [
            {
              depth: 0,
              hand_size: 7,
              p_reach: f("1/1"),
              p_keep_given_reach: f("1/1"),
              p_success_forced: f("1/2"),
            },
          ],
          p_success: f("1/2"),
          expected_mulligans: f("0/1"),
          expected_hand_size: f("7/1"),
        },
        best: { rows: [{ depth: "0" }], value: f("1/2"), atoms: [] },
      },
    ],
  ])("never breaks on a malformed reply (%#)", (wording, reply) => {
    expect(readReply(wording, JSON.stringify(reply)).kind).toBe("problem");
  });

  it("names several cards in one group with slashes, and counts the rest as other", () => {
    const reply = {
      type: "MulliganAdvice",
      report: {
        rows: [
          {
            depth: 0,
            hand_size: 7,
            p_reach: f("1/1"),
            p_keep_given_reach: f("1/1"),
            p_success_forced: f("1/2"),
          },
        ],
        p_success: f("1/2"),
        expected_mulligans: f("0/1"),
        expected_hand_size: f("7/1"),
      },
      best: {
        value: f("1/2"),
        atoms: [["Forest", "Swamp"]],
        rows: [
          {
            depth: 0,
            hand_size: 7,
            continuation_value: f("0/1"),
            p_keep_given_reach: f("1/1"),
            hands: [{ atom_counts: [3], probability: f("1/1"), success: f("1/2"), keep: true }],
          },
        ],
      },
    };
    const view = readReply(advice, JSON.stringify(reply));
    expect(view.kind === "mulligan" && view.best.steps[0]?.hands[0]?.text).toBe(
      "3 Forest / Swamp, 4 other  ->  keep",
    );
  });
});
