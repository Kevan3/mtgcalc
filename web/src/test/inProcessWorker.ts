/**
 * A stand-in for the calculation worker that runs the real WebAssembly in-process and
 * replies asynchronously, like a worker would. Records traffic for assertions.
 */
import type { FromWorker, ToWorker } from "../engine/protocol.ts";
import type { WorkerLike } from "../engine/transport.ts";
import { probability } from "./wasm.ts";

export interface Traffic {
  requests: ToWorker[];
  workers: number;
}

export function inProcessWorkers(
  delayMs = 0,
  answer: (request: string) => string = probability,
): { factory: () => WorkerLike; traffic: Traffic } {
  const traffic: Traffic = { requests: [], workers: 0 };
  const factory = (): WorkerLike => {
    traffic.workers += 1;
    let alive = true;
    const worker: WorkerLike = {
      onmessage: null,
      onerror: null,
      postMessage(message: ToWorker) {
        traffic.requests.push(message);
        setTimeout(() => {
          if (!alive) return;
          const reply: FromWorker = { id: message.id, reply: answer(message.request) };
          worker.onmessage?.({ data: reply } as MessageEvent<FromWorker>);
        }, delayMs);
      },
      terminate() {
        alive = false;
      },
    };
    return worker;
  };
  return { factory, traffic };
}
