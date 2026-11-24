/**
 * Keeps the answer in step with the form (FR-93, FR-94).
 *
 * Valid form → its request goes to the live engine; the reply is put into words with
 * the goal *that request was built from* (never the current one, which may have moved
 * on). Invalid form → everything in flight is cancelled and the last good answer stays,
 * marked out of date.
 *
 * "How many should I play?" can take seconds, so it runs only when the player asks
 * (`run`, ADR-0013 §5); until then the form is `waiting` and nothing is computed.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { readReply, type View, type Wording } from "../forms/answer.ts";
import { typeLabels, type Parsed } from "../forms/parse.ts";
import type { FormState } from "../forms/model.ts";
import { buildRequest } from "../forms/request.ts";
import { browserWorker, createLiveEngine, type LiveEngine, type WorkerFactory } from "../engine/transport.ts";

export interface LiveAnswer {
  /** The last answer (or problem) the engine gave, if any. */
  readonly view: View | null;
  /** A newer answer is on its way. */
  readonly busy: boolean;
  /** The form has problems, so `view` belongs to an earlier version of it. */
  readonly invalid: boolean;
  /** A question that runs on request has not been run for the form as it is now. */
  readonly waiting: boolean;
  /** Runs a question that runs on request (no-op otherwise). */
  readonly run: () => void;
  /** The question runs on request ("How many should I play?"). */
  readonly manual: boolean;
}

export function useLiveAnswer(
  parsed: Parsed,
  types: FormState["types"],
  makeWorker: WorkerFactory = browserWorker,
): LiveAnswer {
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(true);
  const engine = useRef<LiveEngine | null>(null);
  const goals = useRef(new Map<number, Wording>());

  useEffect(() => {
    const live = createLiveEngine(makeWorker, {
      onResult(id, reply) {
        const wording = goals.current.get(id);
        if (wording !== undefined) setView(readReply(wording, reply));
      },
      onBusy: setBusy,
    });
    engine.current = live;
    return () => {
      live.dispose();
      engine.current = null;
    };
  }, [makeWorker]);

  // One string holds the request and the goal it answers: equal forms never trigger a
  // recalculation, and the reply is always worded with the goal of its own request.
  const labels = useMemo(() => typeLabels(types), [types]);
  const job = useMemo(
    () =>
      parsed.ok
        ? JSON.stringify({
            request: buildRequest(parsed.setup),
            goal: parsed.setup.goal,
            labels,
            question: parsed.setup.question,
            mulligans: parsed.setup.mulligan !== undefined,
          })
        : null,
    [parsed, labels],
  );

  const manual = parsed.ok && parsed.setup.question?.kind === "howmany";
  const [ranJob, setRanJob] = useState<string | null>(null);
  const waiting = manual && job !== ranJob;

  useEffect(() => {
    const live = engine.current;
    if (live === null) return;
    if (job === null || waiting) {
      live.cancel();
      return;
    }
    const {
      request,
      goal,
      labels: names,
      question,
      mulligans,
    } = JSON.parse(job) as { request: unknown } & Wording;
    const id = live.submit(JSON.stringify(request));
    // Only the newest request can be answered, so it is the only goal worth keeping.
    goals.current.clear();
    goals.current.set(id, {
      goal,
      ...(names === undefined ? {} : { labels: names }),
      ...(question === undefined ? {} : { question }),
      ...(mulligans === undefined ? {} : { mulligans }),
    });
  }, [job, waiting, makeWorker]);

  const run = useCallback(() => {
    setRanJob(job);
  }, [job]);
  return { view, busy: busy && parsed.ok && !waiting, invalid: !parsed.ok, waiting, run, manual };
}
