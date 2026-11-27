/**
 * Parity with the Python reference (tests/web/make_fixtures.py): the same request JSON
 * as `mtgcalc_gui.forms.build_scenario` / `goal_condition`, the same sentence as
 * `chances`, and the same percentage texts as `pct` / `in_words`.
 */
import { describe, expect, it } from "vitest";

import { testCore } from "../test/core.ts";
import {
  cases,
  formCases,
  howManyCases,
  mulliganCases,
  percentages,
  questionCases,
} from "../test/fixtures.ts";
import { probability } from "../test/wasm.ts";
import { parseForm } from "./parse.ts";
import { readReply } from "./answer.ts";
import { buildRequest } from "./request.ts";
import { inWords, parseFraction, pct } from "./words.ts";
import { keepRuleWords } from "../components/MulliganSettings.tsx";

describe("parity with mtgcalc_gui.forms", () => {
  it("has golden cases", () => {
    expect(cases.length).toBeGreaterThan(50);
    expect(percentages.length).toBeGreaterThan(300);
  });

  it.each(cases.map((c) => [c.name, c] as const))("builds Python's request: %s", (_, c) => {
    expect(buildRequest(c.setup)).toEqual(c.request);
  });

  it.each(cases.map((c) => [c.name, c] as const))("says Python's sentence: %s", (_, c) => {
    const view = readReply(c.setup.goal, JSON.stringify(c.answer));
    expect(view.kind).toBe("answer");
    expect(view.headline).toBe(c.headline);
  });

  it.each(formCases.map((c) => [c.name, c] as const))(
    "reads, asks and answers like Python, end to end: %s",
    (_, c) => {
      const parsed = parseForm(c.form, testCore);
      expect(parsed.ok, JSON.stringify(parsed)).toBe(true);
      if (!parsed.ok) return;
      const reply = probability(JSON.stringify(buildRequest(parsed.setup)));
      expect(JSON.parse(reply)).toEqual(c.answer);
      expect(readReply(parsed.setup.goal, reply).headline).toBe(c.headline);
    },
  );

  it.each(questionCases.map((c) => [c.name, c] as const))("shows Python's tables: %s", (_, c) => {
    const parsed = parseForm(c.form, testCore);
    expect(parsed.ok, JSON.stringify(parsed)).toBe(true);
    if (!parsed.ok) return;
    const view = readReply(
      { goal: parsed.setup.goal, ...(parsed.setup.question ? { question: parsed.setup.question } : {}) },
      probability(JSON.stringify(buildRequest(parsed.setup))),
    );
    expect(view.headline).toBe(c.headline);
    if (view.kind === "draws") {
      // The desktop app: "Opening hand  (average 0.47)" with rows "k what" / exactly / at least / at most.
      const rows = view.rows.map((r) => [
        `${r.turn === 0 ? "Opening hand" : `By turn ${String(r.turn)}`}  (average ${r.average})`,
        r.counts.map((k) => [`${String(k.k)} ${view.what}`, k.exactly, k.atLeast, k.atMost]),
      ]);
      expect(rows).toEqual(c.rows);
    } else if (view.kind === "turns") {
      const rows = view.rows.map((r) => [
        r.turn === 0 ? "Opening hand" : `Turn ${String(r.turn)}`,
        String(r.cardsSeen),
        r.chance,
        r.words,
      ]);
      expect(rows).toEqual(c.rows);
    } else {
      expect.fail(`unexpected view ${view.kind}`);
    }
  });

  it("has how-many cases, answered and out of reach", () => {
    expect(howManyCases.filter((c) => c.error === undefined).length).toBeGreaterThanOrEqual(4);
    expect(howManyCases.filter((c) => c.error !== undefined).length).toBeGreaterThanOrEqual(2);
  });

  it.each(howManyCases.map((c) => [c.name, c] as const))("chooses card counts like Python: %s", (_, c) => {
    const parsed = parseForm(c.form, testCore);
    expect(parsed.ok, JSON.stringify(parsed)).toBe(true);
    if (!parsed.ok) return;
    const { question } = parsed.setup;
    expect(question?.kind).toBe("howmany");
    const view = readReply(
      { goal: parsed.setup.goal, ...(question ? { question } : {}) },
      probability(JSON.stringify(buildRequest(parsed.setup))),
    );
    if (c.error !== undefined) {
      expect(view.kind).toBe("problem");
      expect(view.kind === "problem" ? view.advice : "").toBe(c.error);
      return;
    }
    expect(view.kind).toBe("howmany");
    if (view.kind !== "howmany") return;
    expect(view.headline).toBe(c.headline);
    expect(view.details).toEqual(c.details);
    expect(view.rows.map((r) => [r.option, r.chance, r.words])).toEqual(c.rows);
  });

  it.each(mulliganCases.map((c) => [c.name, c] as const))(
    "builds Python's mulligan scenario and keep-rule words: %s",
    (_, c) => {
      const parsed = parseForm(c.form, testCore);
      expect(parsed.ok, JSON.stringify(parsed)).toBe(true);
      if (!parsed.ok) return;
      expect(buildRequest(parsed.setup)["scenario"]).toEqual(c.scenario);
      expect(keepRuleWords(c.form, {})).toBe(c.keepWords);
    },
  );

  it("covers every shape of keep rule", () => {
    const shapes = new Set(
      mulliganCases.map(
        (c) => (c.scenario as { mulligan: { keep_rule: { type: string } } }).mulligan.keep_rule.type,
      ),
    );
    expect([...shapes].sort()).toEqual(["And", "Between", "Const", "Or"]);
  });

  it.each(mulliganCases.map((c) => [c.name, c] as const))("explains mulligans like Python: %s", (_, c) => {
    const parsed = parseForm(c.form, testCore);
    expect(parsed.ok, JSON.stringify(parsed)).toBe(true);
    if (!parsed.ok) return;
    const view = readReply(
      {
        goal: parsed.setup.goal,
        mulligans: parsed.setup.mulligan !== undefined,
        ...(parsed.setup.question ? { question: parsed.setup.question } : {}),
      },
      probability(JSON.stringify(buildRequest(parsed.setup))),
    );
    expect(view.headline).toBe(c.headline);
    if (view.kind === "answer") {
      expect(view.details).toEqual(c.details);
    } else if (view.kind === "mulligan") {
      expect(view.details).toEqual(c.details);
      // The desktop app's rows: "Your plan" then "Best possible plan", each with children.
      const rows = [
        [
          ["Your plan", "", "", ""],
          view.yourPlan.map((r) => [[r.step, r.getHere, r.keepIt, r.goodGame], []]),
        ],
        [
          ["Best possible plan", "", "", view.best.value],
          view.best.steps.map((st) => [
            [st.title, "", st.keepIt, ""],
            st.hands.map((h) => [h.text, "", h.chance, h.goodGame]),
          ]),
        ],
      ];
      expect(rows).toEqual(c.rows);
    } else {
      expect.fail(`unexpected view ${view.kind}`);
    }
  });

  it.each(percentages.map((p) => [p.value, p] as const))("formats %s like Python", (_, p) => {
    const exact = parseFraction(p.value);
    expect(pct(exact)).toBe(p.pct);
    expect(inWords(exact)).toBe(p.inWords);
  });
});
