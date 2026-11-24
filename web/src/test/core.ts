/** The real core for tests, loaded synchronously from the built WebAssembly. */
import { format_rule, parse_deck, parse_rule } from "../wasm-pkg/mtgcalc_wasm.js";
import { coreFrom } from "../engine/core.ts";
import "./wasm.ts"; // initializes the module

export const testCore = coreFrom({ parse_deck, parse_rule, format_rule });
