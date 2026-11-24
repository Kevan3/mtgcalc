/**
 * Live updates without stale answers (FR-93, ADR-0013 §5).
 *
 * The form submits a request on every change; the scheduler decides what actually runs:
 *
 * - **Debounce.** A request waits `debounceMs` after the last change, so typing "40"
 *   never computes "4" first.
 * - **Latest wins.** At most one request waits, always the newest; older waiting
 *   requests are dropped.
 * - **No stale answers.** Every request is numbered; a reply is delivered only if it
 *   belongs to the newest request. `cancel()` (an invalid form) invalidates them all.
 * - **No long stalls.** WebAssembly calls cannot be interrupted, so when a newer
 *   request is waiting behind a calculation that has run for `restartAfterMs`, the
 *   worker is restarted and the newer request sent at once.
 *
 * Pure logic: the worker and the clock are injected, so tests drive time directly.
 */

/** Sends requests to whatever computes them (a Web Worker in the browser). */
export interface Transport {
  send(id: number, request: string): void;
  /** Stops the current calculation by replacing the worker. */
  restart(): void;
}

export interface Clock {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface SchedulerOptions {
  readonly debounceMs?: number;
  readonly restartAfterMs?: number;
}

export interface Listener {
  /** The reply to the newest request. */
  onResult(id: number, reply: string): void;
  /** True while the newest request is waiting or being computed. */
  onBusy(busy: boolean): void;
}

export const DEBOUNCE_MS = 250;
export const RESTART_AFTER_MS = 1000;

export const browserClock: Clock = {
  now: () => performance.now(),
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => {
    globalThis.clearTimeout(h as ReturnType<typeof globalThis.setTimeout>);
  },
};

interface Job {
  readonly id: number;
  readonly request: string;
}

export class LiveScheduler {
  private readonly debounceMs: number;
  private readonly restartAfterMs: number;
  private latest = 0;
  private pending: Job | null = null;
  private ready = false; // the pending job's debounce has elapsed
  private inFlight: { readonly id: number; readonly started: number } | null = null;
  private debounceTimer: unknown = null;
  private watchdog: unknown = null;
  private busy = false;
  private disposed = false;

  constructor(
    private readonly transport: Transport,
    private readonly listener: Listener,
    private readonly clock: Clock = browserClock,
    options: SchedulerOptions = {},
  ) {
    this.debounceMs = options.debounceMs ?? DEBOUNCE_MS;
    this.restartAfterMs = options.restartAfterMs ?? RESTART_AFTER_MS;
  }

  /** Queues `request` as the newest; returns its number. */
  submit(request: string): number {
    this.latest += 1;
    this.pending = { id: this.latest, request };
    this.ready = false;
    this.clearTimer("debounceTimer");
    this.debounceTimer = this.clock.setTimeout(() => {
      this.debounceTimer = null;
      this.ready = true;
      this.flush();
      this.updateBusy();
    }, this.debounceMs);
    this.updateBusy();
    return this.latest;
  }

  /** Drops everything: no reply to any earlier request will be delivered. */
  cancel(): void {
    this.latest += 1;
    this.pending = null;
    this.ready = false;
    this.clearTimer("debounceTimer");
    this.clearTimer("watchdog");
    this.updateBusy();
  }

  /** A reply from the transport. Replies to anything but the newest request are dropped. */
  receive(id: number, reply: string): void {
    if (this.disposed || this.inFlight?.id !== id) return;
    this.inFlight = null;
    this.clearTimer("watchdog");
    if (id === this.latest) this.listener.onResult(id, reply);
    this.flush();
    this.updateBusy();
  }

  /** The worker died (it is restarted); the request it held is answered with `reply`. */
  crashed(reply: string): void {
    if (this.disposed) return;
    const lost = this.inFlight;
    this.transport.restart();
    if (lost !== null) {
      this.inFlight = null;
      this.clearTimer("watchdog");
      if (lost.id === this.latest) this.listener.onResult(lost.id, reply);
    }
    this.flush();
    this.updateBusy();
  }

  dispose(): void {
    this.disposed = true;
    this.clearTimer("debounceTimer");
    this.clearTimer("watchdog");
  }

  private flush(): void {
    if (this.disposed || this.pending === null || !this.ready) return;
    if (this.inFlight !== null) {
      const ran = this.clock.now() - this.inFlight.started;
      if (ran < this.restartAfterMs) {
        this.armWatchdog(this.restartAfterMs - ran);
        return;
      }
      this.transport.restart();
      this.inFlight = null;
    }
    const job = this.pending;
    this.pending = null;
    this.ready = false;
    this.inFlight = { id: job.id, started: this.clock.now() };
    this.transport.send(job.id, job.request);
  }

  private armWatchdog(ms: number): void {
    if (this.watchdog !== null) return;
    this.watchdog = this.clock.setTimeout(() => {
      this.watchdog = null;
      this.flush();
      this.updateBusy();
    }, ms);
  }

  private clearTimer(which: "debounceTimer" | "watchdog"): void {
    if (this[which] !== null) {
      this.clock.clearTimeout(this[which]);
      this[which] = null;
    }
  }

  private updateBusy(): void {
    const busy = this.pending !== null || this.inFlight?.id === this.latest;
    if (busy !== this.busy) {
      this.busy = busy;
      this.listener.onBusy(busy);
    }
  }
}
