/**
 * Connects the scheduler to a Web Worker: sends requests, routes replies and crashes,
 * and replaces the worker when the scheduler asks for a restart.
 */
import { internalError, type FromWorker, type ToWorker } from "./protocol.ts";
import { LiveScheduler, type Clock, type Listener, type Transport } from "./scheduler.ts";

/** The parts of `Worker` this module uses (tests pass a fake). */
export interface WorkerLike {
  postMessage(message: ToWorker): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<FromWorker>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}

export type WorkerFactory = () => WorkerLike;

export interface LiveEngine {
  submit(request: string): number;
  cancel(): void;
  dispose(): void;
}

class WorkerTransport implements Transport {
  private worker: WorkerLike;

  constructor(
    private readonly factory: WorkerFactory,
    private readonly scheduler: () => LiveScheduler,
  ) {
    this.worker = this.spawn();
  }

  send(id: number, request: string): void {
    this.worker.postMessage({ id, request });
  }

  restart(): void {
    this.worker.terminate();
    this.worker = this.spawn();
  }

  dispose(): void {
    this.worker.terminate();
  }

  private spawn(): WorkerLike {
    const worker = this.factory();
    worker.onmessage = (event) => {
      if (worker !== this.worker) return; // a replaced worker's last words
      const data = event.data;
      if ("reply" in data) this.scheduler().receive(data.id, data.reply);
      else this.scheduler().crashed(internalError(data.crash));
    };
    worker.onerror = (event) => {
      if (worker !== this.worker) return;
      event.preventDefault();
      this.scheduler().crashed(internalError(event.message || "the calculation stopped"));
    };
    return worker;
  }
}

/** A live engine on top of workers made by `factory`. */
export function createLiveEngine(factory: WorkerFactory, listener: Listener, clock?: Clock): LiveEngine {
  let scheduler: LiveScheduler | null = null;
  const transport = new WorkerTransport(factory, () => {
    if (scheduler === null) throw new Error("scheduler not ready");
    return scheduler;
  });
  scheduler = new LiveScheduler(transport, listener, clock);
  const s = scheduler;
  return {
    submit: (request) => s.submit(request),
    cancel: () => {
      s.cancel();
    },
    dispose: () => {
      s.dispose();
      transport.dispose();
    },
  };
}

/** The browser's calculation worker. */
export function browserWorker(): WorkerLike {
  return new Worker(new URL("./worker.ts", import.meta.url), { type: "module", name: "mtgcalc" });
}
