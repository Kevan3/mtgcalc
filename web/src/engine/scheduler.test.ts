import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { LiveScheduler, type Clock, type Listener, type Transport } from "./scheduler.ts";

/** A clock whose time only moves when the test says so. */
class FakeClock implements Clock {
  time = 0;
  private timers: { at: number; fn: () => void; handle: number }[] = [];
  private next = 0;

  now(): number {
    return this.time;
  }

  setTimeout(fn: () => void, ms: number): unknown {
    this.next += 1;
    this.timers.push({ at: this.time + ms, fn, handle: this.next });
    return this.next;
  }

  clearTimeout(handle: unknown): void {
    this.timers = this.timers.filter((t) => t.handle !== handle);
  }

  advance(ms: number): void {
    const end = this.time + ms;
    for (let fired = 0; ; fired += 1) {
      // A timer that keeps re-arming itself at or before now would spin forever.
      if (fired > 10_000) throw new Error("timers keep firing without time passing");
      this.timers.sort((a, b) => a.at - b.at);
      const due = this.timers[0];
      if (due === undefined || due.at > end) break;
      this.timers.shift();
      this.time = due.at;
      due.fn();
    }
    this.time = end;
  }
}

class Recorder implements Transport, Listener {
  sent: { id: number; request: string }[] = [];
  restarts = 0;
  results: { id: number; reply: string }[] = [];
  busy: boolean[] = [];

  send(id: number, request: string): void {
    this.sent.push({ id, request });
  }
  restart(): void {
    this.restarts += 1;
  }
  onResult(id: number, reply: string): void {
    this.results.push({ id, reply });
  }
  onBusy(busy: boolean): void {
    this.busy.push(busy);
  }
}

function setup(): { s: LiveScheduler; clock: FakeClock; rec: Recorder } {
  const clock = new FakeClock();
  const rec = new Recorder();
  const s = new LiveScheduler(rec, rec, clock, { debounceMs: 150, restartAfterMs: 1000 });
  return { s, clock, rec };
}

describe("LiveScheduler", () => {
  it("waits for a pause in typing and sends only the last value", () => {
    const { s, clock, rec } = setup();
    s.submit("4");
    clock.advance(100);
    const id = s.submit("40");
    clock.advance(149);
    expect(rec.sent).toEqual([]);
    clock.advance(1);
    expect(rec.sent).toEqual([{ id, request: "40" }]);
  });

  it("delivers the reply to the newest request", () => {
    const { s, clock, rec } = setup();
    const id = s.submit("a");
    clock.advance(150);
    s.receive(id, "answer a");
    expect(rec.results).toEqual([{ id, reply: "answer a" }]);
  });

  it("drops the reply to a request the form has moved past, then runs the newest", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("a");
    clock.advance(150); // a is computing
    s.submit("b");
    clock.advance(150);
    const c = s.submit("c");
    clock.advance(150); // c is ready but waits for a
    expect(rec.sent.map((j) => j.request)).toEqual(["a"]);
    s.receive(a, "answer a");
    expect(rec.results).toEqual([]); // a is stale
    expect(rec.sent.map((j) => j.request)).toEqual(["a", "c"]); // b was never sent
    s.receive(c, "answer c");
    expect(rec.results).toEqual([{ id: c, reply: "answer c" }]);
  });

  it("does not send a newer request before its pause is over, even when idle", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("a");
    clock.advance(150);
    s.submit("b");
    clock.advance(10);
    s.receive(a, "answer a");
    expect(rec.sent.map((j) => j.request)).toEqual(["a"]);
    clock.advance(140);
    expect(rec.sent.map((j) => j.request)).toEqual(["a", "b"]);
  });

  it("cancel() drops waiting work and any reply still on its way", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("a");
    clock.advance(150);
    s.submit("b");
    s.cancel();
    clock.advance(1000);
    s.receive(a, "answer a");
    expect(rec.sent.map((j) => j.request)).toEqual(["a"]);
    expect(rec.results).toEqual([]);
  });

  it("restarts a long calculation when a newer request is waiting", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("slow");
    clock.advance(150);
    const b = s.submit("fast");
    clock.advance(150); // b ready; a has run 150 ms
    expect(rec.restarts).toBe(0);
    clock.advance(849);
    expect(rec.restarts).toBe(0);
    clock.advance(1); // a has run 1000 ms
    expect(rec.restarts).toBe(1);
    expect(rec.sent.map((j) => j.request)).toEqual(["slow", "fast"]);
    s.receive(a, "late answer"); // from the old worker, if it ever arrives
    s.receive(b, "answer b");
    expect(rec.results).toEqual([{ id: b, reply: "answer b" }]);
  });

  it("never restarts a long calculation that is still the newest", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("slow");
    clock.advance(10_000);
    s.receive(a, "answer");
    expect(rec.restarts).toBe(0);
    expect(rec.results).toHaveLength(1);
  });

  it("answers the newest request with an error when the worker crashes", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("a");
    clock.advance(150);
    s.crashed("oops");
    expect(rec.restarts).toBe(1);
    expect(rec.results).toEqual([{ id: a, reply: "oops" }]);
    const b = s.submit("b");
    clock.advance(150);
    expect(rec.sent.at(-1)).toEqual({ id: b, request: "b" });
  });

  it("does not report a crash for a request the form has moved past", () => {
    const { s, clock, rec } = setup();
    s.submit("a");
    clock.advance(150);
    const b = s.submit("b");
    s.crashed("oops");
    expect(rec.results).toEqual([]);
    clock.advance(150);
    expect(rec.sent.at(-1)).toEqual({ id: b, request: "b" });
  });

  it("reports busy from the first change until the newest answer", () => {
    const { s, clock, rec } = setup();
    const a = s.submit("a");
    expect(rec.busy).toEqual([true]);
    clock.advance(150); // sent: still busy while it computes
    expect(rec.busy).toEqual([true]);
    clock.advance(5000);
    expect(rec.busy).toEqual([true]);
    s.receive(a, "x");
    expect(rec.busy).toEqual([true, false]);
    s.submit("b");
    s.cancel();
    expect(rec.busy).toEqual([true, false, true, false]);
  });

  it("ignores replies it did not ask for, and everything after dispose", () => {
    const { s, clock, rec } = setup();
    s.receive(7, "unknown");
    const a = s.submit("a");
    clock.advance(150);
    s.dispose();
    s.receive(a, "late");
    s.crashed("late");
    s.submit("b");
    clock.advance(1000);
    expect(rec.results).toEqual([]);
    expect(rec.sent).toHaveLength(1);
  });

  it("keeps its promises under any interleaving of typing, time and replies", () => {
    type Step =
      { op: "submit" } | { op: "cancel" } | { op: "advance"; ms: number } | { op: "reply" } | { op: "crash" };
    const step = fc.oneof(
      fc.constant<Step>({ op: "submit" }),
      fc.constant<Step>({ op: "cancel" }),
      fc.integer({ min: 0, max: 1200 }).map((ms): Step => ({ op: "advance", ms })),
      fc.constant<Step>({ op: "reply" }),
      fc.constant<Step>({ op: "crash" }),
    );
    fc.assert(
      fc.property(fc.array(step, { maxLength: 60 }), (steps) => {
        const { s, clock, rec } = setup();
        let latest = 0;
        let cancelled = false;
        let outstanding: number | null = null; // the job the "worker" holds
        for (const st of steps) {
          const sentBefore = rec.sent.length;
          const resultsBefore = rec.results.length;
          if (st.op === "submit") {
            latest = s.submit(`r${latest + 1}`);
            cancelled = false;
          } else if (st.op === "cancel") {
            s.cancel();
            cancelled = true;
          } else if (st.op === "advance") {
            clock.advance(st.ms);
          } else if (st.op === "reply" && outstanding !== null) {
            s.receive(outstanding, `answer ${outstanding}`);
            outstanding = null;
          } else if (st.op === "crash" && outstanding !== null) {
            s.crashed("crash");
            outstanding = null;
          }
          // A restart abandons the job the old worker held.
          if (rec.sent.length > sentBefore) {
            const job = rec.sent.at(-1);
            if (job !== undefined) outstanding = job.id;
          }
          // Only the newest, un-cancelled request is ever answered.
          for (const r of rec.results.slice(resultsBefore)) {
            expect(r.id).toBe(latest);
            expect(cancelled).toBe(false);
          }
        }
        // No job is sent twice, and jobs go out in increasing order.
        const ids = rec.sent.map((j) => j.id);
        expect(ids).toEqual([...ids].sort((a, b) => a - b));
        expect(new Set(ids).size).toBe(ids.length);
        // Liveness: with time and a responsive worker, the newest request gets its answer.
        if (latest > 0 && !cancelled) {
          for (let i = 0; i < 5; i += 1) {
            clock.advance(2000);
            const job = rec.sent.at(-1);
            if (job?.id === latest) s.receive(job.id, "final");
          }
          expect(rec.results.at(-1)?.id).toBe(latest);
        }
      }),
      { numRuns: 500 },
    );
  });
});
