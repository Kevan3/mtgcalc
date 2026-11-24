/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// BASE_PATH is set by the GitHub Pages workflow (the site lives under /<repo>/).
export default defineConfig({
  base: process.env["BASE_PATH"] ?? "/",
  plugins: [react()],
  worker: { format: "es" },
  build: { target: "es2022", sourcemap: true },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    environment: "node",
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/wasm-pkg/**",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        "src/main.tsx",
        "src/engine/worker.ts",
      ],
      thresholds: { lines: 95, branches: 90, functions: 95, statements: 95 },
    },
  },
});
