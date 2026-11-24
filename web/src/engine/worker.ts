/// <reference lib="webworker" />
/**
 * The calculation worker: loads the Rust core (WebAssembly) once and answers requests,
 * so the page never waits on a calculation (ADR-0013 §5).
 */
import init, { probability } from "../wasm-pkg/mtgcalc_wasm.js";
import wasmUrl from "../wasm-pkg/mtgcalc_wasm_bg.wasm?url";

import type { FromWorker, ToWorker } from "./protocol.ts";

declare const self: DedicatedWorkerGlobalScope;

const ready = init({ module_or_path: wasmUrl });

function post(message: FromWorker): void {
  self.postMessage(message);
}

self.addEventListener("message", (event: MessageEvent<ToWorker>) => {
  const { id, request } = event.data;
  ready
    .then(() => {
      post({ id, reply: probability(request) });
    })
    .catch((error: unknown) => {
      post({ id, crash: String(error) });
    });
});
