import { describe, expect, it } from "vitest";

import { KIND_COLORS, kindColor } from "./LineGroups.tsx";

describe("kindColor", () => {
  it("gives neighbouring kinds different colours, cycling through the palette", () => {
    const colors = Array.from({ length: 14 }, (_, i) => kindColor(i));
    expect(colors.slice(0, KIND_COLORS)).toEqual(["c1", "c2", "c3", "c4", "c5", "c6"]);
    expect(colors.every((c, i) => i === 0 || c !== colors[i - 1])).toBe(true);
    expect(kindColor(KIND_COLORS)).toBe("c1");
  });
});
