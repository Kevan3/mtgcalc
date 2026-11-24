import { describe, expect, it } from "vitest";

import { buildRequest, type Json } from "./request.ts";

describe("buildRequest", () => {
  it("orders tags exactly like Python's frozenset serialization (sorted by repr)", () => {
    const req = buildRequest({
      deck: {
        size: 10,
        types: [{ name: "x", count: 1, also: ["mana", "mana rock", "urza's", "a\\b", "zed"] }],
      },
      play: { goFirst: true, drawsPerTurn: 1 },
      goal: { combine: "all", requirements: [{ kind: "at least", amount: 1, cardType: "x", turn: 0 }] },
    });
    const deck = ((req as { scenario: Json }).scenario as { deck: { cards: { tags: { items: Json[] } }[] } })
      .deck;
    // Expected value printed by Python's mtgcalc.model.serialization.to_dict.
    expect(deck.cards[0]?.tags.items).toEqual(["urza's", "a\\b", "mana rock", "mana", "x", "zed"]);
  });

  it("leaves out types with no cards, and adds no filler when the types fill the deck", () => {
    const req = buildRequest({
      deck: {
        size: 5,
        types: [
          { name: "a", count: 5, also: [] },
          { name: "b", count: 0, also: [] },
        ],
      },
      play: { goFirst: false, drawsPerTurn: 2 },
      goal: { combine: "any", requirements: [{ kind: "none", amount: 9, cardType: "b", turn: 1 }] },
    });
    expect((req as { scenario: Json }).scenario).toMatchObject({
      deck: { cards: [{ name: "a", quantity: 5 }] },
      game: { on_play: false, draws_per_turn: 2 },
    });
    expect(req["query"]).toMatchObject({
      condition: { type: "At", turn: 1, item: { type: "Compare", op: "==", value: 0 } },
    });
  });
});
