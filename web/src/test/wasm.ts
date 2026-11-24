/**
 * The real WebAssembly build, loaded synchronously in Node for tests: the same bytes
 * the browser runs (ADR-0013 §7), without a worker.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { initSync, probability } from "../wasm-pkg/mtgcalc_wasm.js";

// Tests run from web/ (jsdom gives import.meta.url an http: scheme, so it is not used).
initSync({ module: readFileSync(join(process.cwd(), "src", "wasm-pkg", "mtgcalc_wasm_bg.wasm")) });

export { probability };
