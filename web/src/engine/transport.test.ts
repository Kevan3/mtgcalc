import { describe, expect, it } from "vitest";

import type { FromWorker, ToWorker } from "./protocol.ts";
import type { Clock } from "./scheduler.ts";
import { createLiveEngine, type WorkerLike } from "./transport.ts";

class FakeWorker implements WorkerLike {
  onmessage: ((event: MessageEvent<FromWorker>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  received: ToWorker[] = [];
  terminated = false;
  postMessage(message: ToWorker): void {
    this.received.push(message);
  }
  terminate(): void {
    this.terminated = true;
  }
  reply(message: FromWorker): void {
    this.onmessage?.({ data: message } as MessageEvent<FromWorker>);
  }
  fail(message: string, handled = true): void {
    let prevented = false;
    const preventDefault = (): void => {
      prevented = true;
    };
    this.onerror?.({ message, preventDefault } as unknown as ErrorEvent);
    expect(prevented).toBe(handled); // a handled error stays out of the browser console
  }
}

/** Timers run immediately: these tests are about routing, not timing. */
const instant: Clock = {
  now: () => 0,
  setTimeout: (fn) => {
    fn();
    return 0;
  },
  clearTimeout: () => undefined,
};

function setup() {
  const workers: FakeWorker[] = [];
  const results: { id: number; reply: string }[] = [];
  const engine = createLiveEngine(
    () => {
      const w = new FakeWorker();
      workers.push(w);
      return w;
    },
    { onResult: (id, reply) => results.push({ id, reply }), onBusy: () => undefined },
    instant,
  );
  const current = (): FakeWorker => {
    const w = workers.at(-1);
    if (w === undefined) throw new Error("no worker");
    return w;
  };
  return { engine, workers, results, current };
}

describe("worker transport", () => {
  it("sends requests to the worker and routes replies back", () => {
    const { engine, current, results } = setup();
    const id = engine.submit("question");
    expect(current().received).toEqual([{ id, request: "question" }]);
    current().reply({ id, reply: "answer" });
    expect(results).toEqual([{ id, reply: "answer" }]);
  });

  it("turns a crash inside the worker into an error answer and replaces the worker", () => {
    const { engine, workers, current, results } = setup();
    const id = engine.submit("question");
    const first = current();
    first.reply({ id, crash: "RuntimeError: unreachable" });
    expect(first.terminated).toBe(true);
    expect(workers).toHaveLength(2);
    expect(JSON.parse(results[0]?.reply ?? "{}")).toMatchObject({ type: "Error", kind: "internal" });
  });

  it("handles a worker that fails to load", () => {
    const { engine, current, results, workers } = setup();
    engine.submit("question");
    current().fail("");
    expect(workers).toHaveLength(2);
    expect(JSON.parse(results[0]?.reply ?? "{}")).toMatchObject({
      kind: "internal",
      message: "the calculation stopped",
    });
  });

  it("ignores anything a replaced worker still says", () => {
    const { engine, current, results } = setup();
    const id = engine.submit("question");
    const old = current();
    old.reply({ id, crash: "boom" }); // replaced
    const next = engine.submit("again");
    old.reply({ id: next, reply: "from the old worker" });
    old.fail("late error", false);
    expect(results).toHaveLength(1);
    current().reply({ id: next, reply: "fresh" });
    expect(results.at(-1)).toEqual({ id: next, reply: "fresh" });
  });

  it("terminates its worker when disposed", () => {
    const { engine, current } = setup();
    const w = current();
    engine.dispose();
    expect(w.terminated).toBe(true);
  });
});
