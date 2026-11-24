/**
 * WebAssembly conformance (ADR-0013 §7): the .wasm file the browser loads answers every
 * golden request exactly as the Python reference does.
 */
import { describe, expect, it } from "vitest";

import { cases } from "../test/fixtures.ts";
import { probability } from "../test/wasm.ts";

describe("the WebAssembly build", () => {
  it.each(cases.map((c) => [c.name, c] as const))("answers like Python: %s", (_, c) => {
    expect(JSON.parse(probability(JSON.stringify(c.request)))).toEqual(c.answer);
  });

  it("never throws on bad input", () => {
    for (const text of ["", "{", "null", "[]", '{"scenario": 1}', "\u0000".repeat(10)]) {
      const reply = JSON.parse(probability(text)) as { type: string; kind: string };
      expect(reply).toMatchObject({ type: "Error", kind: "malformed" });
    }
  });
});
