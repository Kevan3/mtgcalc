/**
 * First-time users (ADR-0013 §7): each test follows someone who has never used a tool
 * like this, doing what they would naturally do, and checks that the page explains
 * itself at every step, in plain words, with the right answer.
 *
 * Expected answers come from the Python reference (mtgcalc_gui.forms.chances).
 */
import { expect, test } from "@playwright/test";

import { answer, expectNoJargon, settledHeadline } from "./helpers.ts";

test.describe("a brand-new player", () => {
  test("understands what the page does before touching anything", async ({ page }) => {
    await page.goto("/");
    // The purpose, in one sentence, at the top.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Card draw odds");
    await expect(page.getByText("How often will a game go the way you want?")).toBeVisible();
    // A real answer is already there: they see what kind of thing the tool tells them.
    await expect(await settledHeadline(page)).toHaveText(
      "You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 47.7% of games (about 5 games in 10).",
    );
    // The three steps are labelled in order, and the words they might not know are explained.
    for (const step of ["1. Your deck", "2. How you play", "3. Your question"]) {
      await expect(page.getByRole("heading", { name: step })).toBeVisible();
    }
    await expect(page.getByText("“By turn 3” means after you draw your card for turn 3.")).toBeVisible();
    await expect(page.getByText("Going first, you skip your first draw.")).toBeVisible();
    await expectNoJargon(page);
  });

  test("asks their own first question: 2 lands in the opening hand?", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    // "I only care about lands in my opening hand."
    await page.getByRole("button", { name: "Remove line 2" }).click();
    const amount = page.getByLabel("Line 1: number of cards");
    await amount.fill("2");
    await page.getByLabel("Line 1: when").selectOption({ label: "in your opening hand" });
    await expect(await settledHeadline(page)).toHaveText(
      "You have at least 2 land in your opening hand in 85.7% of games (all but about 1 game in 7).",
    );
    // "Is that exact?"
    await answer(page).getByText("Show the exact numbers").click();
    await expect(answer(page).getByText(/^More precisely: 85\.\d{4}%\.$/u)).toBeVisible();
    await expectNoJargon(page);
  });

  test("a Commander player sets up their own deck from scratch", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Commander", exact: true }).click();
    await expect(page.getByLabel("Cards in your deck")).toHaveValue("99");
    await expect(page.getByRole("radio", { name: "No, I draw on turn 1" })).toBeChecked();
    // Their deck has 24 lands (they type over the example), and 10 ramp cards.
    await page.getByRole("button", { name: "+ Add a card type" }).click();
    await page.getByLabel("Name of card type 3").fill("Ramp");
    await page.getByLabel("How many ramp").fill("10");
    // They want a ramp card by turn 2 and nothing else.
    await page.getByRole("button", { name: "Remove line 2" }).click();
    await page.getByLabel("Line 1: number of cards").fill("1");
    await page.getByLabel("Line 1: card type").selectOption("ramp");
    await page.getByLabel("Line 1: when").selectOption({ label: "by turn 2" });
    await expect(await settledHeadline(page)).toHaveText(
      "You have at least 1 Ramp by turn 2 in 63.3% of games (about 6 games in 10).",
    );
    await expect(page.getByText("The other 59 cards in your deck count as “other cards”.")).toBeVisible();
  });

  test("makes every usual mistake and is told how to fix each one, where it happened", async ({ page }) => {
    await page.goto("/");
    const first = await settledHeadline(page);
    const firstText = await first.innerText();
    const status = answer(page).getByRole("status");
    // Problems are said next to the field (and repeated in the answer card).
    const steps = page.getByRole("form", { name: "Your deck and goal" });

    // Letters in a number.
    const size = page.getByLabel("Cards in your deck");
    await size.fill("sixty");
    await size.blur();
    await expect(steps.getByText("Use a whole number, like 60.")).toBeVisible();
    await expect(size).toHaveAttribute("aria-invalid", "true");
    // The old answer stays, clearly marked as out of date.
    // The card says what to change, and labels the old answer as out of date.
    await expect(status).toHaveText("To update the answer: Use a whole number, like 60.");
    await expect(answer(page).getByText(/^Out of date:/u)).toBeVisible();
    await expect(answer(page).locator(".headline")).toHaveText(firstText);
    await expectNoJargon(page);

    // A deck too small for the card types.
    await size.fill("20");
    await size.blur();
    await expect(
      steps.getByText(
        "Your card types add up to 30 cards, but your deck has 20. Lower a number or raise the deck size.",
      ),
    ).toBeVisible();

    // Fixed: the answer comes back by itself and the messages disappear.
    await size.fill("60");
    await expect(status).toHaveText("");
    await expect(await settledHeadline(page)).toHaveText(firstText);
    await expect(page.locator(".problem")).toHaveCount(0);

    // A card type with no name, and the same name twice.
    await page.getByRole("button", { name: "+ Add a card type" }).click();
    await page.getByLabel("Name of card type 3").fill("Land");
    await page.getByLabel("Name of card type 3").blur();
    await expect(steps.getByText("You already have a card type called “land”.")).toBeVisible();
    await page.getByLabel("Name of card type 3").fill("");
    await page.getByLabel("Name of card type 3").blur();
    await expect(steps.getByText("Give this card type a name, like “land”.")).toBeVisible();
    await page.getByRole("button", { name: "Remove card type 3" }).click();

    // Removing every line of the goal.
    await page.getByRole("button", { name: "Remove line 2" }).click();
    await page.getByRole("button", { name: "Remove line 1" }).click();
    await expect(steps.getByText("Add a line to say what a good game looks like.")).toBeVisible({
      timeout: 3000,
    });
    await expectNoJargon(page);
  });

  test("is never told off while still typing", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    const size = page.getByLabel("Cards in your deck");
    await size.fill("");
    // Mid-typing: the field is empty for a moment, which is not a mistake yet.
    await expect(page.locator(".problem")).toHaveCount(0);
    await size.pressSequentially("4");
    await size.pressSequentially("0");
    await expect(page.locator(".problem")).toHaveCount(0);
    await expect(await settledHeadline(page)).toHaveText(
      "You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 79.6% of games (about 8 games in 10).",
    );
  });

  test("tries every example and always gets an answer in plain words", async ({ page }) => {
    await page.goto("/");
    for (const name of [
      "40-card Limited: lands and your key card",
      "Commander: ramp on turn 2",
      "60-card deck: lands and removal by turn 3",
    ]) {
      await page.getByRole("button", { name }).click();
      await expect(await settledHeadline(page)).toHaveText(/^You have .+ in \d+\.\d% of games \(.+\)\.$/u);
      await expectNoJargon(page);
    }
  });
});

// From the Python reference (mtgcalc_gui.forms.chances / mulligan_advice), default plan.
const HEADLINE_WITH_MULLIGANS =
  "You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 54.0% of games (about 5 games in 10).";
const ADVICE =
  "With your mulligan plan you get a good game 54.0% of the time. Never mulliganing: 47.7%. The best possible plan: 74.2%.";

const MOXFIELD_EXPORT = `1 Atraxa, Praetors' Voice (ONE) 196 *F*

1 Sol Ring (C21) 263 #ramp
1 Arcane Signet (M3C) 283 #ramp
1 Llanowar Elves (DOM) 168 #ramp
32 Forest (UNF) 239 #land
2 Command Tower (CMM) 1027 #land
10 Divination (M19) 51 #draw
51 Grizzly Bears (M21) 1
`;

test.describe("a player with a real deck", () => {
  test("pastes a Moxfield export and asks about it", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByRole("radio", { name: "Paste a decklist" }).check();
    await page.getByLabel("Your decklist").fill(MOXFIELD_EXPORT);
    // The page says what it read, so the player can check it.
    await expect(page.getByText("Read 99 cards in the deck. Tags: draw 10, land 34, ramp 3.")).toBeVisible();
    await page.getByRole("radio", { name: "No, I draw on turn 1" }).check();
    await page.getByRole("button", { name: "Remove line 2" }).click();
    await page.getByLabel("Line 1: number of cards").fill("1");
    await page.getByLabel("Line 1: card type").selectOption("ramp");
    await page.getByLabel("Line 1: when").selectOption({ label: "by turn 2" });
    await expect(await settledHeadline(page)).toHaveText(
      "You have at least 1 ramp by turn 2 in 25.1% of games (about 3 games in 10).",
    );
    await expectNoJargon(page);
  });

  test("is told which line of a pasted list is wrong", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("radio", { name: "Paste a decklist" }).check();
    const box = page.getByLabel("Your decklist");
    await box.fill("32 Forest #land\nSol Ring #ramp\n");
    await box.blur();
    const steps = page.getByRole("form", { name: "Your deck and goal" });
    await expect(
      steps.getByText("Line 2: start the line with how many copies, like “4 Lightning Bolt”."),
    ).toBeVisible();
    await expectNoJargon(page);
  });

  test("an experienced player writes a rule, starting from the lines", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Pasted decklist with #tags" }).click();
    await page.getByLabel("Your decklist").fill(MOXFIELD_EXPORT);
    await settledHeadline(page);
    await page.getByRole("checkbox", { name: "Write my own rule instead (for experienced players)" }).check();
    const rule = page.getByLabel("Your rule");
    await expect(rule).toHaveValue("ramp >= 1 @T2");
    await rule.fill("ramp >= 1 @T2 OR draw >= 2 @T4");
    await expect(await settledHeadline(page)).toHaveText(
      "You have your rule (ramp >= 1 @T2 OR draw >= 2 @T4) in 48.9% of games (about 5 games in 10).",
    );
    await rule.fill("ramp >= 1 @T2 OR");
    await rule.blur();
    await expect(answer(page).getByRole("status")).toHaveText(
      "To update the answer: At character 17: a card type should come here (the rule ended too soon).",
    );
    // The guide is there when they need it.
    await page.getByText("How to write rules").click();
    await expect(page.getByText("3 land and 1 ramp from different cards")).toBeVisible();
  });
});

test.describe("a player curious about their draws", () => {
  test("asks how many lands they will see, turn by turn", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByRole("radio", { name: /How many will I draw\?/u }).check();
    await page.getByLabel("Show every turn up to").selectOption({ label: "turn 4" });
    // 24 of 60, going first: 7 + 3 cards by turn 4, 10 x 0.4 = 4.00 on average.
    await expect(await settledHeadline(page)).toHaveText(
      "On average you will have seen 4.00 land by turn 4.",
    );
    const table = page.getByRole("table", { name: "Chance of having seen at least this many land" });
    await expect(table.getByRole("row")).toHaveCount(6);
    await page.getByText("All the numbers").click();
    await expect(page.getByRole("table", { name: "By turn 4 (average 4.00)" })).toBeVisible();
    await expectNoJargon(page);
  });

  test("watches a chance grow turn by turn", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByRole("radio", { name: /Turn by turn/u }).check();
    await expect(await settledHeadline(page)).toHaveText(
      "The chance of having at least 3 land and at least 1 removal, turn by turn.",
    );
    const table = page.getByRole("table", { name: "Your chance, turn by turn" });
    await expect(table.getByRole("row")).toHaveCount(7); // header + opening hand + 5 turns
    // The card says the final number too, and points to the table (it is not pinned on phones).
    await expect(answer(page).getByText(/^By turn 5: \d+\.\d% of games \(.+\)\.$/u)).toBeVisible();
    await expect(answer(page).getByRole("link", { name: "See the table" })).toBeVisible();
    await expectNoJargon(page);
  });
});

test.describe("a player who mulligans", () => {
  test("turns mulligans on and asks whether their plan is good", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByRole("checkbox", { name: "Mulligan bad opening hands" }).check();
    await expect(
      answer(page).getByText("This includes the games where you mulligan, following your plan."),
    ).toBeVisible();
    await expect(await settledHeadline(page)).toHaveText(HEADLINE_WITH_MULLIGANS);
    await page.getByRole("radio", { name: /Should I mulligan\?/u }).check();
    await expect(await settledHeadline(page)).toHaveText(ADVICE);
    await expect(page.getByRole("table", { name: "Your plan" })).toBeVisible();
    await page.getByText(/^First 7 cards: keep if its chance is at least/u).click();
    await expect(page.getByRole("table", { name: /^Hands at this step: First 7 cards/u })).toBeVisible();
    await expectNoJargon(page);
  });
});

test.describe("a player building a deck", () => {
  test("asks how many lands to play, then what one fewer would do", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByRole("radio", { name: /How many should I play\?/u }).check();
    // Nothing is calculated until they ask: the page says what to press.
    await expect(answer(page).getByRole("status")).toHaveText(/Find the best counts/u);
    // The values already there work: pressing straight away gives an answer.
    await answer(page).getByRole("button", { name: "Find the best counts" }).click();
    await expect(await settledHeadline(page)).toHaveText(
      /^Play \d+ land: you then have .* in \d+\.\d% of games, which reaches your 60\.0% target\.$/u,
    );
    await expect(answer(page).getByText(/^With \d+ land it would be \d+\.\d%\.$/u)).toBeVisible();
    await expect(answer(page).getByText("This is guaranteed to be the best answer.")).toBeVisible();
    await expect(page.getByRole("table", { name: "Options tried, highest chance first" })).toBeVisible();
    await expectNoJargon(page);
  });

  test("is told what to change when a target cannot be reached", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("radio", { name: /How many should I play\?/u }).check();
    await page.getByLabel("Try 1: to").fill("15");
    await answer(page).getByRole("button", { name: "Find the best counts" }).click();
    await expect(
      answer(page).getByText(/cannot be reached even with 15 land\. Raise the 'to' numbers/u),
    ).toBeVisible();
    await expectNoJargon(page);
  });

  test("shares 26 cards between lands and removal", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("radio", { name: /How many should I play\?/u }).check();
    await page.getByRole("radio", { name: /share cards between card types/u }).check();
    await page.getByRole("radio", { name: "The best chance I can get" }).check();
    // No target is asked for: the best chance needs none.
    await expect(page.getByLabel("Target: in what percent of games?")).toHaveCount(0);
    // Filled in from the good game: lands and removal, sharing the 30 cards they use now.
    await expect(page.getByLabel("Try 2: card type")).toHaveValue("removal");
    await page.getByLabel("Cards allowed between them").fill("26");
    await answer(page).getByRole("button", { name: "Find the best counts" }).click();
    await expect(await settledHeadline(page)).toHaveText(/^Best use of 26 cards: \d+ land, \d+ removal\./u);
    await expectNoJargon(page);
  });

  test("asks for the best number of lands without choosing a target", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("radio", { name: /How many should I play\?/u }).check();
    await page.getByRole("radio", { name: "The best chance I can get" }).check();
    await answer(page).getByRole("button", { name: "Find the best counts" }).click();
    await expect(await settledHeadline(page)).toHaveText(
      /^Play \d+ land: you then have .* in \d+\.\d% of games, the best chance from 14 to 40 land\.$/u,
    );
    await expectNoJargon(page);
  });
});

test.describe("a player on a phone", () => {
  test.skip(({ isMobile }) => !isMobile, "phone layout only");

  test("can see the answer change while editing the last step", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    const amount = page.getByLabel("Line 2: number of cards");
    await amount.scrollIntoViewIfNeeded();
    await amount.fill("2");
    const headline = await settledHeadline(page);
    await expect(headline).toContainText("at least 2 removal");
    await expect(headline).toBeInViewport();
    // Nothing is wider than the screen.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("the pinned answer never covers the field being fixed", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    // The tester's situation: the field sits just below the pinned card, then a mistake
    // makes the card say what to fix. The card must not grow over the field.
    const draws = page.getByLabel("Cards you draw each turn");
    await draws.scrollIntoViewIfNeeded();
    const cardBefore = await answer(page).boundingBox();
    const fieldBefore = await draws.boundingBox();
    if (cardBefore === null || fieldBefore === null) throw new Error("not on screen");
    await page.mouse.wheel(0, fieldBefore.y - (cardBefore.y + cardBefore.height) - 4);
    await draws.fill("lots");
    await draws.blur();
    await expect(answer(page).getByRole("status")).toHaveText(/^To update the answer: Use a whole number/u);
    const card = await answer(page).boundingBox();
    const field = await draws.boundingBox();
    if (card === null || field === null) throw new Error("not on screen");
    expect(field.y).toBeGreaterThanOrEqual(card.y + card.height);
  });
});
