/** Messages between the page and the calculation worker. */

export interface ToWorker {
  readonly id: number;
  readonly request: string;
}

export type FromWorker =
  { readonly id: number; readonly reply: string } | { readonly id: number; readonly crash: string };

/** The engine's error format (ADR-0013 §3) for failures outside the engine itself. */
export function internalError(message: string): string {
  return JSON.stringify({ type: "Error", kind: "internal", field: "", message });
}
