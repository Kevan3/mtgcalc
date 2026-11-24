import { expect, type Locator, type Page } from "@playwright/test";

/** The answer card. */
export function answer(page: Page): Locator {
  return page.getByRole("region", { name: "Your answer" });
}

/** The current answer sentence, once it is up to date (not dimmed, not waiting). */
export async function settledHeadline(page: Page): Promise<Locator> {
  const body = answer(page).locator(".answer-body");
  await expect(body).not.toHaveClass(/stale/u);
  return answer(page).locator(".headline");
}

/** Every word on screen that only a programmer or statistician would use (FR-85). */
export const JARGON = [
  "hypergeometric",
  "probability distribution",
  "atom",
  "selector",
  "query",
  "engine",
  "webassembly",
  "wasm",
  "json",
  "null",
  "undefined",
  "nan",
  "infinity",
  "[object",
  "validation",
  "checkpoint",
  "predicate",
  "boolean",
  "exception",
  "stack trace",
  "integer",
  "parse",
];

/** Asserts no jargon is visible on the page right now. */
export async function expectNoJargon(page: Page): Promise<void> {
  const text = (await page.locator("body").innerText()).toLowerCase();
  const found = JARGON.filter((word) =>
    new RegExp(`(^|[^a-z])${word.replace(/[[\]]/gu, "\\$&")}`, "u").test(text),
  );
  expect(found, `jargon on screen: ${found.join(", ")}`).toEqual([]);
}
