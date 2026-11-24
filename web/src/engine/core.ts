/**
 * The Rust core on the page itself, for instant, synchronous checks while typing:
 * reading a pasted decklist and a typed rule (each well under a millisecond).
 * Calculations never run here: they go to the worker (ADR-0013 §5).
 */
import init, { format_rule, parse_deck, parse_rule } from "../wasm-pkg/mtgcalc_wasm.js";
import wasmUrl from "../wasm-pkg/mtgcalc_wasm_bg.wasm?url";

/** The three text functions of the core, each returning the JSON text it produced. */
export interface Core {
  parseDeck(text: string): string;
  parseRule(text: string, turn: number): string;
  formatRule(query: string): string;
}

/** Wraps already-initialized core functions (tests pass the Node build). */
export function coreFrom(fns: {
  parse_deck: (text: string) => string;
  parse_rule: (text: string, turn: number) => string;
  format_rule: (query: string) => string;
}): Core {
  return {
    parseDeck: (text) => fns.parse_deck(text),
    parseRule: (text, turn) => fns.parse_rule(text, turn),
    formatRule: (query) => fns.format_rule(query),
  };
}

/** Loads the core in the page (the browser reuses the worker's download). */
export async function loadCore(): Promise<Core> {
  await init({ module_or_path: wasmUrl });
  return coreFrom({ parse_deck, parse_rule, format_rule });
}
