/**
 * Accessibility (NFR-17), keyboard use (FR-96), privacy (NFR-18), speed (NFR-16) and
 * live behaviour (FR-93) of the real page with the real worker and WebAssembly.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { answer, settledHeadline } from "./helpers.ts";

async function axe(page: Page): Promise<void> {
  test.skip(
    page.context().browser()?.browserType().name() === "firefox",
    "axe-core crashes Playwright's Firefox build ('Page crashed' inside axe's frame evaluation); " +
      "the scan runs on Chromium, desktop and phone",
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(summary).toEqual([]);
}

test.describe("accessibility", () => {
  test("no WCAG 2.2 AA violations: answered page, light and dark", async ({ page }) => {
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await page.goto("/");
      await settledHeadline(page);
      await axe(page);
    }
  });

  test("no violations while showing problems", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    await page.getByLabel("Cards in your deck").fill("x");
    await page.getByLabel("Cards you draw each turn").fill("");
    await page.getByRole("button", { name: "Remove good game 1, line 2" }).click();
    await page.getByRole("button", { name: "Remove good game 1, line 1" }).click();
    await expect(page.locator(".problem").first()).toBeVisible({ timeout: 3000 });
    await axe(page);
  });

  test("no violations with the result tables", async ({ page }) => {
    for (const question of [/How many will I draw\?/u, /Turn by turn/u]) {
      await page.goto("/");
      await page.getByRole("radio", { name: question }).check();
      await settledHeadline(page);
      // Only "How many will I draw?" has the full tables; open them when they are there.
      const more = page.getByText("All the numbers");
      if ((await more.count()) > 0) await more.click();
      await axe(page);
    }
  });

  test("no violations with mulligan settings and advice", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("checkbox", { name: "Mulligan bad opening hands" }).check();
    // Two kinds of hand, the first with two lines.
    await page.getByRole("button", { name: "And also, in kind of hand 1: add a line" }).click();
    await page.getByRole("button", { name: "+ Or keep another kind of hand" }).click();
    // Two kinds of good game too (the same layout).
    await page.getByRole("button", { name: "+ Or another kind of good game" }).click();
    await page.getByRole("radio", { name: /Should I mulligan\?/u }).check();
    await settledHeadline(page);
    await page.getByText(/^First 7 cards: keep if its chance/u).click();
    await axe(page);
  });

  test("no violations with 'How many should I play?', before and after running it", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("radio", { name: /How many should I play\?/u }).check();
    await axe(page);
    await page.getByLabel("Target: in what percent of games?").fill("60");
    await answer(page).getByRole("button", { name: "Find the best counts" }).click();
    await settledHeadline(page);
    await expect(page.getByRole("table", { name: "Options tried, highest chance first" })).toBeVisible();
    await axe(page);
  });

  test("no violations with a pasted decklist and a typed rule", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Pasted decklist with #tags" }).click();
    await settledHeadline(page);
    await page.getByRole("checkbox", { name: "Write my own rule instead (for experienced players)" }).check();
    await page.getByText("How to write rules").click();
    await axe(page);
    await page.getByLabel("Your rule").fill("ramp >=");
    await page.getByLabel("Your decklist").fill("x");
    await page.getByLabel("Your rule").focus();
    await expect(page.locator(".problem").first()).toBeVisible({ timeout: 3000 });
    await axe(page);
  });

  test("problems are tied to their fields for screen readers", async ({ page }) => {
    await page.goto("/");
    const draws = page.getByLabel("Cards you draw each turn");
    await draws.fill("many");
    await draws.blur();
    await expect(draws).toHaveAccessibleDescription(
      /Normally 1\. Use 2 if something lets you draw an extra card every turn\..*Use a whole number/u,
    );
  });

  test("answers are announced politely and the region says when it is busy", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    const live = answer(page).locator("[aria-live=polite]");
    await expect(live).toHaveAttribute("aria-atomic", "true");
    await expect(live.locator(".headline")).toBeVisible();
    await expect(answer(page).locator(".answer-body")).toHaveAttribute("aria-busy", "false");
  });
});

test.describe("keyboard only", () => {
  test.skip(({ isMobile }) => isMobile, "no physical keyboard on phones");

  test("asks a new question without a mouse", async ({ page }) => {
    await page.goto("/");
    await settledHeadline(page);
    // Reach the deck size from the top of the page with Tab alone.
    for (let i = 0; i < 30; i += 1) {
      await page.keyboard.press("Tab");
      if (await page.getByLabel("Cards in your deck").evaluate((el) => el === document.activeElement)) break;
    }
    await expect(page.getByLabel("Cards in your deck")).toBeFocused();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("40");
    // Shift+Tab back to the format buttons, then forwards past them again: nothing traps focus.
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Commander", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    // A select works with the keyboard too.
    await page.getByLabel("Good game 1, line 1: when").focus();
    await page.keyboard.press("ArrowUp");
    await expect(await settledHeadline(page)).toContainText("at least 3 land by turn 2 and");
    // Focus is always visible.
    const outline = await page
      .getByLabel("Good game 1, line 1: when")
      .evaluate((el) => getComputedStyle(el).outlineStyle + " " + getComputedStyle(el).outlineWidth);
    expect(outline).not.toMatch(/^none|0px$/u);
  });
});

test("makes no network requests after loading (nothing leaves the browser)", async ({ page }) => {
  await page.goto("/");
  await settledHeadline(page);
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await page.getByRole("button", { name: "Commander: ramp on turn 2" }).click();
  await page.getByLabel("Cards in your deck").fill("100");
  await page.getByRole("button", { name: "+ Or another kind of good game" }).click();
  await settledHeadline(page);
  expect(requests).toEqual([]);
});

test("first answer within 2 seconds, later answers right after typing pauses", async ({ page }) => {
  const start = Date.now();
  await page.goto("/");
  await expect(answer(page).locator(".headline")).toBeVisible({ timeout: 2000 });
  expect(Date.now() - start).toBeLessThan(2000);
  // A 99-card deck, 4 lines, turn 10: well within the pause plus 100 ms (NFR-16).
  await page.getByRole("button", { name: "Commander: ramp on turn 2" }).click();
  await settledHeadline(page);
  for (const line of [1, 2]) {
    await page.getByLabel(`Line ${line}: when`).selectOption({ label: "by turn 10" });
  }
  const t0 = Date.now();
  await expect(await settledHeadline(page)).toContainText("by turn 10");
  expect(Date.now() - t0).toBeLessThan(250 + 100 + 400); // pause + budget + browser slack
});

test("typing never waits on a calculation", async ({ page }) => {
  await page.goto("/");
  await settledHeadline(page);
  // Each keystroke changes the question; the page must keep up with fast typing.
  const name = page.getByLabel("Name of card type 1");
  await name.fill("");
  const t0 = Date.now();
  await name.pressSequentially("forest and other lands", { delay: 10 });
  expect(Date.now() - t0).toBeLessThan(2000);
  await expect(name).toHaveValue("forest and other lands");
  await expect(await settledHeadline(page)).toContainText("at least 3 forest and other lands by turn 3");
});
