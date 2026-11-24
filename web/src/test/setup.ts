// Adds DOM matchers (toBeInTheDocument, ...) and unmounts rendered components after
// each test (Testing Library only does that by itself when Vitest globals are on).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
