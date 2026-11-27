// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "./App.tsx";
import { STATUS } from "./text/copy.ts";
import { testCore } from "./test/core.ts";
import { inProcessWorkers } from "./test/inProcessWorker.ts";

function setup(delayMs = 0) {
  const { factory, traffic } = inProcessWorkers(delayMs);
  const user = userEvent.setup();
  const view = render(<App core={testCore} makeWorker={factory} remember={false} />);
  const answer = () => screen.getByRole("region", { name: "Your answer" });
  return { user, view, traffic, answer };
}

const FIRST =
  "You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 47.7% of games (about 5 games in 10).";

describe("App", () => {
  it("opens with the example answered, without the player doing anything", async () => {
    const { answer } = setup();
    expect(within(answer()).getByRole("status")).toHaveTextContent(STATUS.first);
    expect(await within(answer()).findByText(FIRST)).toBeInTheDocument();
    expect(within(answer()).getByRole("status")).toHaveTextContent("");
  });

  it("updates the answer as the player types, with one calculation per pause", async () => {
    const { user, answer, traffic } = setup();
    await within(answer()).findByText(FIRST);
    const before = traffic.requests.length;
    const lands = screen.getByLabelText("How many land");
    await user.clear(lands);
    await user.type(lands, "17");
    await waitFor(() => {
      expect(
        within(answer()).getByText(/at least 3 land by turn 3 and at least 1 removal/u),
      ).not.toHaveTextContent("47.7%");
    });
    // "", "1" and "17" were typed faster than the pause: only the last one was computed.
    expect(traffic.requests.length - before).toBe(1);
  });

  it("keeps the last answer, marked out of date, while the form has a problem", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    const size = screen.getByLabelText("Cards in your deck");
    await user.clear(size);
    expect(within(answer()).getByText(FIRST)).toBeInTheDocument();
    // While typing: no complaint, just "finish typing"; the old answer is labelled.
    expect(within(answer()).getByRole("status")).toHaveTextContent(STATUS.finishTyping);
    expect(within(answer()).getByText(STATUS.outOfDate)).toBeInTheDocument();
    // Not flagged while still typing in the field...
    expect(size).not.toHaveAttribute("aria-invalid");
    // ...but once the player stops typing, the field says what to do.
    await waitFor(
      () => {
        expect(size).toHaveAttribute("aria-invalid", "true");
      },
      { timeout: 3000 },
    );
    expect(screen.getByText("Enter how many cards are in your deck.")).toBeInTheDocument();
    // The answer card says the same thing, so it is never just "fix something".
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "To update the answer: Enter how many cards are in your deck.",
    );
    await user.type(size, "40");
    expect(within(answer()).getByRole("status")).toHaveTextContent(""); // valid again
    // A 40-card deck with the same 24 lands: a new, higher chance replaces the old one.
    expect(await within(answer()).findByText(/by turn 3 in 7\d\.\d% of games/u)).toBeInTheDocument();
    expect(within(answer()).queryByText(FIRST)).not.toBeInTheDocument();
  });

  it("shows a problem right away when the player leaves the field", async () => {
    const { user } = setup();
    const draws = screen.getByLabelText("Cards you draw each turn");
    await user.clear(draws);
    await user.type(draws, "lots");
    await user.tab();
    expect(draws).toHaveAttribute("aria-invalid", "true");
    expect(draws).toHaveAccessibleDescription(/Use a whole number from 0 to 10/u);
  });

  it("follows a renamed card type in the goal lines", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    const name = screen.getByLabelText("Name of card type 1");
    await user.clear(name);
    await user.type(name, "Forest");
    expect(screen.getByLabelText("Line 1: card type")).toHaveValue("forest");
    expect(await within(answer()).findByText(/at least 3 Forest by turn 3/u)).toBeInTheDocument();
  });

  it("loads an example with one click", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("button", { name: "Commander: ramp on turn 2" }));
    expect(screen.getByLabelText("Cards in your deck")).toHaveValue("99");
    expect(screen.getByRole("radio", { name: "No, I draw on turn 1" })).toBeChecked();
    expect(
      await within(answer()).findByText(/at least 2 land by turn 2 and at least 1 ramp by turn 2/u),
    ).toBeInTheDocument();
  });

  it("adds and removes goal lines, and offers 'all' or 'any' only when it matters", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    expect(screen.getByRole("group", { name: "Which lines must happen?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove line 2" }));
    expect(screen.queryByRole("group", { name: "Which lines must happen?" })).not.toBeInTheDocument();
    expect(await within(answer()).findByText(/^You have at least 3 land by turn 3 in /u)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove line 1" }));
    await waitFor(
      () => {
        expect(screen.getByText("Add a line to say what a good game looks like.")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
    await user.click(screen.getByRole("button", { name: "+ Add a line" }));
    expect(await within(answer()).findByText(/at least 1 land in your opening hand/u)).toBeInTheDocument();
  });

  it("never shows an answer that belongs to an older form, even with a slow worker", async () => {
    const { user, answer, traffic } = setup(400);
    await within(answer()).findByText(FIRST, {}, { timeout: 3000 });
    const amount = screen.getByLabelText("Line 1: number of cards");
    await user.clear(amount);
    await user.type(amount, "2"); // computes "at least 2 land" (slowly)
    await act(() => new Promise((r) => setTimeout(r, 200))); // the request is now in flight
    await user.clear(amount);
    await user.type(amount, "4"); // the form moves on before the reply
    const headline = await within(answer()).findByText(/at least 4 land by turn 3/u, {}, { timeout: 4000 });
    expect(headline).toBeInTheDocument();
    expect(screen.queryByText(/at least 2 land by turn 3/u)).not.toBeInTheDocument();
    expect(traffic.requests.length).toBeGreaterThanOrEqual(2);
  });

  it("explains a question that is too big instead of failing", async () => {
    const tooBig = JSON.stringify({ type: "Error", kind: "too_large", field: "", message: "3000000 states" });
    const { factory } = inProcessWorkers(0, () => tooBig);
    render(<App core={testCore} makeWorker={factory} remember={false} />);
    const answer = screen.getByRole("region", { name: "Your answer" });
    expect(
      await within(answer).findByText("This question is too big to work out exactly."),
    ).toBeInTheDocument();
    expect(within(answer).getByText(/Try fewer card types or fewer lines/u)).toBeInTheDocument();
    expect(within(answer).getByText("Details for a bug report")).toBeInTheDocument();
  });

  it("every control does what it says", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);

    // Format buttons set the size and who draws first, and show which one is chosen.
    await user.click(screen.getByRole("button", { name: "40-card Limited" }));
    expect(screen.getByLabelText("Cards in your deck")).toHaveValue("40");
    expect(screen.getByRole("button", { name: "40-card Limited" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("radio", { name: "No, I draw on turn 1" }));
    expect(screen.getByRole("button", { name: "40-card Limited" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("radio", { name: "Yes, I go first (no draw on turn 1)" }));

    // A new card type, with "also counts as", appears in the goal's card-type lists.
    await user.click(screen.getByRole("button", { name: "+ Add a card type" }));
    await user.type(screen.getByLabelText("Name of card type 3"), "MDFC");
    await user.type(screen.getByLabelText("How many mdfc"), "2");
    await user.type(screen.getByLabelText("Other types mdfc also counts as"), "land, ramp");
    const typeList = screen.getByLabelText("Line 1: card type");
    expect(
      within(typeList)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["land", "removal", "MDFC", "ramp", "cards of any type"]);
    expect(screen.getByText("The other 8 cards in your deck count as “other cards”.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove mdfc" }));
    expect(screen.queryByLabelText("How many mdfc")).not.toBeInTheDocument();

    // "no" needs no number; "any" combines lines with "or"; the turn list names turns.
    await user.selectOptions(screen.getByLabelText("Line 2: how many"), "none");
    expect(screen.queryByLabelText("Line 2: number of cards")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Any of them (at least one)" }));
    await user.selectOptions(screen.getByLabelText("Line 1: when"), "in your opening hand");
    expect(
      await within(answer()).findByText(
        /^You have at least 3 land in your opening hand or no removal by turn 3 in /u,
      ),
    ).toBeInTheDocument();

    // Draws per turn: 0 is allowed, and every turn stays available.
    const draws = screen.getByLabelText("Cards you draw each turn");
    await user.clear(draws);
    await user.type(draws, "0");
    expect(within(screen.getByLabelText("Line 1: when")).getAllByRole("option")).toHaveLength(21);
  });

  it("offers only turns the deck has cards for, and flags a line that is now too late", async () => {
    const { user } = setup();
    const size = screen.getByLabelText("Cards in your deck");
    await user.clear(size);
    await user.type(size, "10");
    expect(
      within(screen.getByLabelText("Line 2: when"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["in your opening hand", "by turn 1", "by turn 2", "by turn 3", "by turn 4"]);
    await user.clear(size);
    await user.type(size, "8");
    await user.tab();
    await waitFor(() => {
      expect(
        screen.getAllByText("Your deck runs out of cards after turn 2. Pick turn 2 or earlier."),
      ).toHaveLength(2);
    });
    const steps = screen.getByRole("form", { name: "Your deck and goal" });
    expect(
      within(steps).getByText(/Your card types add up to 30 cards, but your deck has 8/u),
    ).toBeInTheDocument();
  });

  it("asks for a card type at once when a line's type was removed (no typing involved)", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("button", { name: "Remove removal" }));
    const list = screen.getByLabelText("Line 2: card type");
    expect(list).toHaveValue("");
    expect(within(list).getAllByRole("option")[0]).toHaveTextContent("choose a card type");
    // Pressing a button is not typing: the real problem shows right away, never "finish typing".
    expect(screen.getByText("Pick a card type from the list.")).toBeInTheDocument();
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "To update the answer: Pick a card type from the list.",
    );
  });

  it("says a section's problem as soon as the player leaves the section", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    const lands = screen.getByLabelText("How many land");
    await user.clear(lands);
    await user.type(lands, "60");
    await user.click(screen.getByRole("heading", { name: "2. How you play" }));
    const message =
      "Your card types add up to 66 cards, but your deck has 60. Lower a number or raise the deck size.";
    expect(screen.getByText(message)).toBeInTheDocument(); // no waiting
    expect(within(answer()).getByRole("status")).toHaveTextContent(`To update the answer: ${message}`);
  });

  it("points out an 'also counts as' name that is not a card type, without blocking", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    const also = screen.getByLabelText("Other types land also counts as");
    await user.type(also, "land ramp");
    await user.tab();
    expect(
      screen.getByText(
        "“land ramp” is not in your list of card types, so it becomes a new type. To use several types, separate them with commas.",
      ),
    ).toBeInTheDocument();
    expect(also).toHaveAccessibleDescription(/separate them with commas/u);
    expect(within(answer()).getByRole("status")).toHaveTextContent(""); // still answered
  });

  it("keeps the capitals the player typed in lists and answers", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    const name = screen.getByLabelText("Name of card type 2");
    await user.clear(name);
    await user.type(name, "Lightning Bolt");
    expect(
      within(screen.getByLabelText("Line 2: card type")).getByRole("option", { selected: true }),
    ).toHaveTextContent("Lightning Bolt");
    expect(await within(answer()).findByText(/at least 1 Lightning Bolt by turn 3/u)).toBeInTheDocument();
  });

  it("moves keyboard focus into new rows and back to the add button after removing one", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "+ Add a card type" }));
    expect(screen.getByLabelText("Name of card type 3")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove card type 3" }));
    expect(screen.getByRole("button", { name: "+ Add a card type" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "+ Add a line" }));
    expect(screen.getByLabelText("Line 3: how many")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove line 3" }));
    expect(screen.getByRole("button", { name: "+ Add a line" })).toHaveFocus();
  });

  it("shows the exact numbers in a way a beginner can use", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(within(answer()).getByText("Show the exact numbers"));
    expect(within(answer()).getByText(/^More precisely: 47\.\d{4}%\.$/u)).toBeInTheDocument();
    expect(within(answer()).getByText(/counts every possible order of your deck/u)).toBeInTheDocument();
  });

  it("remembers the setup across reloads, in this browser only", async () => {
    localStorage.clear();
    const { factory } = inProcessWorkers();
    const user = userEvent.setup();
    const first = render(<App core={testCore} makeWorker={factory} />);
    const size = screen.getByLabelText("Cards in your deck");
    await user.clear(size);
    await user.type(size, "41");
    first.unmount();
    render(<App core={testCore} makeWorker={factory} />);
    expect(screen.getByLabelText("Cards in your deck")).toHaveValue("41");
    localStorage.clear();
  });

  it("answers about a pasted decklist, with its #tags as card types", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("radio", { name: "Paste a decklist" }));
    expect(screen.queryByLabelText("Cards in your deck")).not.toBeInTheDocument();
    const box = screen.getByLabelText("Your decklist");
    await user.click(box);
    await user.paste("36 Forest #land\n2 Bridge #land #ramp\n10 Elf #ramp\n50 Bear\n");
    expect(screen.getByText("Read 98 cards in the deck. Tags: land 38, ramp 12.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Line 2: card type"), "ramp");
    expect(
      await within(answer()).findByText(
        /^You have at least 3 land by turn 3 and at least 1 ramp by turn 3 in /u,
      ),
    ).toBeInTheDocument();
  });

  it("says which line of a decklist is wrong", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: "Paste a decklist" }));
    const box = screen.getByLabelText("Your decklist");
    await user.click(box);
    await user.paste("36 Forest #land\nSol Ring\n");
    await user.tab();
    const message = "Line 2: start the line with how many copies, like “4 Lightning Bolt”.";
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(within(answer()).getByRole("status")).toHaveTextContent(`To update the answer: ${message}`);
  });

  it("lets an experienced player write a rule, starting from the lines", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(
      screen.getByRole("checkbox", { name: "Write my own rule instead (for experienced players)" }),
    );
    const rule = screen.getByLabelText("Your rule");
    expect(rule).toHaveValue("land >= 3 @T3 AND removal >= 1 @T3");
    expect(screen.queryByLabelText("Line 1: how many")).not.toBeInTheDocument();
    await user.clear(rule);
    await user.type(rule, "land >= 3 @T3 OR removal >= 2 @T4");
    expect(
      await within(answer()).findByText(/^You have your rule \(land >= 3 @T3 OR removal >= 2 @T4\) in /u),
    ).toBeInTheDocument();
    await user.clear(rule);
    await user.type(rule, "land >=");
    await user.tab();
    expect(
      screen.getByText("At character 8: a number should come here (the rule ended too soon)."),
    ).toBeInTheDocument();
  });

  it("explains a rule that names a card the deck does not have", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(
      screen.getByRole("checkbox", { name: "Write my own rule instead (for experienced players)" }),
    );
    const rule = screen.getByLabelText("Your rule");
    await user.clear(rule);
    await user.type(rule, 'card:"Black Lotus" >= 1');
    expect(
      await within(answer()).findByText("Your rule names a card that is not in your deck: 'Black Lotus'."),
    ).toBeInTheDocument();
  });

  it("answers 'How many will I draw?' with an average and a table", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("radio", { name: /How many will I draw\?/u }));
    expect(screen.getByLabelText("Which card type?")).toHaveValue("land");
    await user.selectOptions(screen.getByLabelText("Show every turn up to"), "3");
    // 24 lands in 60, going first: 7 + 2 cards by turn 3, so 9 x 24/60 = 3.60 on average.
    expect(
      await within(answer()).findByText("On average you will have seen 3.60 land by turn 3."),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Chance of having seen at least this many land" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(5); // header + opening hand + turns 1-3
    const [, opening] = rows;
    if (opening === undefined) throw new Error("no opening-hand row");
    expect(within(opening).getByRole("rowheader")).toHaveTextContent("Opening hand");
    expect(within(opening).getAllByRole("cell")[0]).toHaveTextContent("2.80");
  });

  it("answers 'Turn by turn' using the lines without their turns", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("radio", { name: /Turn by turn/u }));
    expect(screen.queryByLabelText("Line 1: when")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Show every turn up to"), "4");
    expect(
      await within(answer()).findByText(
        "The chance of having at least 3 land and at least 1 removal, turn by turn.",
      ),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Your chance, turn by turn" });
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(within(table).getByRole("rowheader", { name: "Turn 4" })).toBeInTheDocument();
  });

  it("asks for a card type when 'How many will I draw?' has none", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("button", { name: "Remove land" }));
    await user.click(screen.getByRole("radio", { name: /How many will I draw\?/u }));
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "To update the answer: Pick a card type from the list.",
    );
  });

  it("includes mulligans when they are on, and says so", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    expect(
      await within(answer()).findByText("This includes the games where you mulligan, following your plan."),
    ).toBeInTheDocument();
    expect(within(answer()).queryByText(FIRST)).not.toBeInTheDocument();
    // The defaults: keep 2 to 5 land, keep up to 3 land first, at most 2 mulligans.
    expect(screen.getByLabelText("Kind of hand 1, line 1: card type")).toHaveValue("land");
    expect(screen.getByLabelText("Keep first 1: up to how many")).toHaveValue("3");
    expect(screen.getByLabelText("Most mulligans you will take")).toHaveValue("2");
    expect(screen.getByText("So: keep a hand with 2 to 5 land.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove kind of hand 1, line 1" }));
    expect(screen.getByText("So: always keep your first hand.")).toBeInTheDocument();
    expect(screen.getByText("You keep every hand (you never mulligan).")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Add a kind of hand to keep" })).toHaveFocus();
  });

  it("keeps a hand that fits any kind of hand, each with all of its lines", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    const status = (): string => within(answer()).getByText(/in \d+\.\d% of games/u).textContent;
    await within(answer()).findByText("This includes the games where you mulligan, following your plan.");
    // "And also": a second line in kind 1, starting at 1 to 7 removal; focus goes to it.
    await user.click(screen.getByRole("button", { name: "And also, in kind of hand 1: add a card type" }));
    const type2 = screen.getByLabelText("Kind of hand 1, line 2: card type");
    expect(type2).toHaveFocus();
    expect(type2).toHaveValue("removal");
    expect(screen.getByText("So: keep a hand with 2 to 5 land and 1 to 7 removal.")).toBeInTheDocument();
    await waitFor(() => {
      expect(within(answer()).queryByText("Out of date")).not.toBeInTheDocument();
    });
    const strict = status();
    // "Or": another kind of hand, which keeps more hands and changes the answer.
    await user.click(screen.getByRole("button", { name: "+ Or keep another kind of hand" }));
    expect(screen.getByLabelText("Kind of hand 2, line 1: card type")).toHaveFocus();
    expect(screen.getByText("Or keep a hand that has")).toBeInTheDocument();
    const max = screen.getByLabelText("Kind of hand 2, line 1: at most this many");
    await user.clear(max);
    await user.type(max, "2");
    expect(
      screen.getByText("So: keep a hand with 2 to 5 land and 1 to 7 removal, or with 2 land."),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(status()).not.toBe(strict);
    });
    // A wrong range is explained next to its line once the player leaves it.
    const min = screen.getByLabelText("Kind of hand 2, line 1: at least this many");
    await user.clear(min);
    await user.type(min, "3");
    await user.tab(); // into the same line's other box: still the same setting, so no problem yet
    expect(screen.queryByText("The first number is bigger than the second.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("heading", { name: "2. How you play" }));
    expect(screen.getByText("The first number is bigger than the second.")).toBeInTheDocument();
    // Removing a line moves focus to its kind's "and also"; the kind's last line, to "or".
    await user.click(screen.getByRole("button", { name: "Remove kind of hand 1, line 2" }));
    expect(
      screen.getByRole("button", { name: "And also, in kind of hand 1: add a card type" }),
    ).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove kind of hand 2, line 1" }));
    expect(screen.getByRole("button", { name: "+ Or keep another kind of hand" })).toHaveFocus();
    expect(screen.getByText("So: keep a hand with 2 to 5 land.")).toBeInTheDocument();
  });

  it("answers 'Should I mulligan?' with your plan, never mulliganing and the best plan", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("radio", { name: /Should I mulligan\?/u }));
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "To update the answer: Turn on mulligans in step 2 first.",
    );
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    expect(
      await within(answer()).findByText(
        /^With your mulligan plan you get a good game \d+\.\d% of the time\. Never mulliganing: 47\.7%\. The best possible plan: \d+\.\d%\.$/u,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Your plan" })).toBeInTheDocument();
    expect(screen.getByText(/^First 7 cards: keep if its chance is at least/u)).toBeInTheDocument();
  });

  it("checks the mulligan settings and explains each problem", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    const min = screen.getByLabelText("Kind of hand 1, line 1: at least this many");
    await user.clear(min);
    await user.type(min, "6");
    // The keep rule's boxes are one setting: its problem shows once the player leaves them.
    await user.click(screen.getByRole("heading", { name: "2. How you play" }));
    expect(screen.getByText("The first number is bigger than the second.")).toBeInTheDocument();
    await user.clear(min);
    await user.type(min, "2");
    await user.click(screen.getByRole("button", { name: "Remove keep-first line 1" }));
    expect(screen.getByRole("button", { name: "+ Add a card type to keep first" })).toHaveFocus();
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "To update the answer: Add a card type to keep first when putting cards on the bottom.",
    );
    await user.click(screen.getByRole("button", { name: "+ Add a card type to keep first" }));
    expect(screen.getByLabelText("Keep first 1: card type")).toHaveFocus();
    const most = screen.getByLabelText("Most mulligans you will take");
    await user.clear(most);
    await user.type(most, "9");
    await user.tab();
    expect(screen.getByText("Use a whole number from 0 to 6.")).toBeInTheDocument();
  });

  it("sets the free first mulligan with the Commander format", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    expect(screen.getByRole("checkbox", { name: "My first mulligan is free" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Commander" }));
    expect(screen.getByRole("checkbox", { name: "My first mulligan is free" })).toBeChecked();
  });

  it("lets the player edit every mulligan setting", async () => {
    const { user, answer } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("checkbox", { name: "Mulligan bad opening hands" }));
    const max = screen.getByLabelText("Kind of hand 1, line 1: at most this many");
    await user.clear(max);
    await user.type(max, "4");
    expect(screen.getByText("So: keep a hand with 2 to 4 land.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "+ Add a card type to keep first" }));
    await user.selectOptions(screen.getByLabelText("Keep first 2: card type"), "removal");
    const upTo = screen.getByLabelText("Keep first 2: up to how many");
    await user.clear(upTo);
    await user.type(upTo, "x");
    await user.tab();
    expect(screen.getByText("Use a whole number, 0 or more.")).toBeInTheDocument();
    await user.clear(upTo);
    await user.type(upTo, "1");
    await user.selectOptions(screen.getByLabelText("Keep first 2: card type"), "land");
    await user.tab();
    expect(screen.getByText("This card type is already in the list.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Keep first 2: card type"), "removal");
    await user.click(screen.getByRole("checkbox", { name: "My first mulligan is free" }));
    expect(screen.getByRole("checkbox", { name: "My first mulligan is free" })).toBeChecked();
    expect(
      await within(answer()).findByText("This includes the games where you mulligan, following your plan."),
    ).toBeInTheDocument();
    // A keep rule on a type that no longer exists asks for another.
    await user.click(screen.getByRole("button", { name: "Remove land" }));
    await waitFor(
      () => {
        expect(screen.getByText("Pick a card type for the hands you keep.")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("answers 'How many should I play?' only when asked, since it can take a while", async () => {
    const { user, answer, traffic } = setup();
    await within(answer()).findByText(FIRST);
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    expect(within(answer()).getByRole("status")).toHaveTextContent(STATUS.pressRun);
    const before = traffic.requests.length;
    await user.clear(screen.getByLabelText("Target: in what percent of games?"));
    await user.type(screen.getByLabelText("Target: in what percent of games?"), "40");
    expect(traffic.requests.length).toBe(before);
    await user.click(within(answer()).getByRole("button", { name: "Find the best counts" }));
    expect(await within(answer()).findByText(/^Play \d+ land: you then have /u)).toBeInTheDocument();
    expect(within(answer()).getByText(/^With \d+ land it would be \d+\.\d%\.$/u)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Options tried, highest chance first" })).toBeInTheDocument();
  });

  it("explains a target that cannot be reached", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.clear(screen.getByLabelText("Try 1: to"));
    await user.type(screen.getByLabelText("Try 1: to"), "15");
    await user.click(within(answer()).getByRole("button", { name: "Find the best counts" }));
    expect(
      await within(answer()).findByText(/^60\.0% cannot be reached even with 15 land\./u),
    ).toBeInTheDocument();
  });

  it("shares cards between card types, with focus following added and removed rows", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(screen.getByRole("radio", { name: /share cards between card types/u }));
    await user.click(screen.getByRole("radio", { name: "The best chance I can get" }));
    expect(screen.queryByLabelText("Target: in what percent of games?")).not.toBeInTheDocument();
    // Filled in from the good game: both card types, sharing the 30 cards they use now.
    expect(screen.getByLabelText("Try 2: card type")).toHaveValue("removal");
    expect(screen.getByLabelText("Cards allowed between them")).toHaveValue("30");
    await user.click(screen.getByRole("button", { name: "+ Add a card type to try" }));
    expect(screen.getByLabelText("Try 3: card type")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove card type to try 3" }));
    expect(screen.getByRole("button", { name: "+ Add a card type to try" })).toHaveFocus();
    await user.clear(screen.getByLabelText("Cards allowed between them"));
    await user.type(screen.getByLabelText("Cards allowed between them"), "26");
    // The button at the end of step 3 keeps focus, so keyboard players stay in place.
    const steps = screen.getAllByRole("button", { name: "Find the best counts" });
    const inForm = steps.find((b) => !answer().contains(b));
    expect(inForm).toBeDefined();
    if (inForm === undefined) return;
    await user.click(inForm);
    expect(inForm).toHaveFocus();
    expect(
      await within(answer()).findByText(/^Best use of 26 cards: \d+ land, \d+ removal\./u),
    ).toBeInTheDocument();
    expect(within(answer()).getByText("This is guaranteed to be the best answer.")).toBeInTheDocument();
  });

  it("offers to switch a pasted decklist to card types, and checks counts against the deck", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(screen.getByRole("radio", { name: /Paste a decklist/u }));
    await user.click(screen.getByRole("button", { name: "Describe my deck as card types" }));
    expect(screen.getByLabelText("Try 1: to")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Try 1: to"));
    await user.type(screen.getByLabelText("Try 1: to"), "70");
    await user.click(document.body);
    expect(within(answer()).getByRole("status")).toHaveTextContent(
      "This can't be more than the 60 cards in your deck.",
    );
    // An old answer about another question is not shown while waiting for the press.
    expect(within(answer()).queryByText(FIRST)).not.toBeInTheDocument();
  });

  it("finds the best count of one card type with no target at all", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(screen.getByRole("radio", { name: "The best chance I can get" }));
    expect(screen.queryByLabelText("Target: in what percent of games?")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Cards allowed between them")).not.toBeInTheDocument();
    await user.click(within(answer()).getByRole("button", { name: "Find the best counts" }));
    expect(
      await within(answer()).findByText(
        /^Play 40 land: you then have .*, the best chance from 14 to 40 land\.$/u,
      ),
    ).toBeInTheDocument();
    expect(
      within(answer()).getByText("40 is your 'to' number: a higher 'to' number might give a better chance."),
    ).toBeInTheDocument();
  });

  it("asks for the fewest cards in total that reach a target, within the cards allowed", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(screen.getByRole("radio", { name: /share cards between card types/u }));
    expect(screen.getByRole("radio", { name: /A target chance I choose/u })).toBeChecked();
    expect(screen.getByLabelText("Cards allowed between them")).toHaveValue("30");
    await user.clear(screen.getByLabelText("Target: in what percent of games?"));
    await user.type(screen.getByLabelText("Target: in what percent of games?"), "30");
    await user.click(within(answer()).getByRole("button", { name: "Find the best counts" }));
    expect(
      await within(answer()).findByText(/^The fewest cards that reach 30\.0%: \d+ /u),
    ).toBeInTheDocument();
  });

  it("checks the how-many inputs and explains each problem", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.clear(screen.getByLabelText("Try 1: from"));
    await user.type(screen.getByLabelText("Try 1: from"), "50");
    await user.click(document.body);
    expect(within(answer()).getByRole("status")).toHaveTextContent(/^To update the answer:/u);
    expect(within(answer()).queryByRole("button", { name: "Find the best counts" })).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Try 1: from"));
    await user.type(screen.getByLabelText("Try 1: from"), "14");
    await user.clear(screen.getByLabelText("Target: in what percent of games?"));
    await user.type(screen.getByLabelText("Target: in what percent of games?"), "150");
    await user.tab();
    expect(within(answer()).getByRole("status")).toHaveTextContent(/^To update the answer:/u);
  });

  it("never shows how-many results for a setup that has changed, and marks the answer", async () => {
    const { user, answer } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(within(answer()).getByRole("button", { name: "Find the best counts" }));
    const headline = await within(answer()).findByText(/^Play (\d+) land:/u);
    const count = /^Play (\d+) land/u.exec(headline.textContent)?.[1] ?? "";
    const table = screen.getByRole("table", { name: "Options tried, highest chance first" });
    expect(within(table).getByRole("rowheader", { name: `${count} land (your answer)` })).toBeInTheDocument();
    // A change: the old result and its table go, until the button is pressed again.
    await user.clear(screen.getByLabelText("Target: in what percent of games?"));
    await user.type(screen.getByLabelText("Target: in what percent of games?"), "50");
    expect(within(answer()).queryByText(/^Play \d+ land:/u)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: "Options tried, highest chance first" }),
    ).not.toBeInTheDocument();
    // A problem: still nothing old on screen, only what to fix.
    await user.clear(screen.getByLabelText("Target: in what percent of games?"));
    await user.type(screen.getByLabelText("Target: in what percent of games?"), "x");
    await user.click(document.body);
    expect(within(answer()).queryByText(STATUS.outOfDate)).not.toBeInTheDocument();
    expect(within(answer()).getByRole("status")).toHaveTextContent(/^To update the answer:/u);
  });

  it("asks for a second card type when sharing cards between only one", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: /How many should I play\?/u }));
    await user.click(screen.getByRole("radio", { name: /share cards between card types/u }));
    expect(screen.queryByText(/Add a second card type to try/u)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove card type to try 2" }));
    expect(screen.getByText(/Add a second card type to try/u)).toBeInTheDocument();
  });
});
