import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import type { LiveAnswer } from "../app/useLiveAnswer.ts";
import type { View } from "../forms/answer.ts";
import { STATUS } from "../text/copy.ts";
import { RunButton } from "./GoalStep.tsx";

interface Props {
  readonly live: LiveAnswer;
  /** The first problem the player can see now, said in the card too (FR-94). */
  readonly problem: string | null;
}

/**
 * Publishes the card's height as `--answer-height`, so that on phones (where the card is
 * pinned to the top) the browser scrolls fields into view below it, not under it.
 */
function usePublishedHeight(): RefObject<HTMLElement | null> {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el === null || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() => {
      root.style.setProperty("--answer-height", `${String(Math.ceil(el.getBoundingClientRect().height))}px`);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--answer-height");
    };
  }, []);
  return ref;
}

/** The last row of a turn table in words: "By turn 5: 74.3% of games (about 7 games in 10)." */
function turnsSummary(view: View & { kind: "turns" }): string {
  const last = view.rows.at(-1);
  if (last === undefined) return "";
  const when = last.turn === 0 ? "In your opening hand" : `By turn ${String(last.turn)}`;
  return `${when}: ${last.chance} of games (${last.words}).`;
}

/**
 * The answer: one sentence first (FR-95), the exact numbers on request, and a status
 * line saying whether the sentence is up to date and, if not, what to change. Screen
 * readers hear each new answer once, politely (FR-96). The status line keeps its height,
 * so the card does not jump while typing.
 */
export function AnswerPanel({ live, problem }: Props): ReactNode {
  const { busy, invalid } = live;
  // A search not yet run for this form: the old answer is about something else, so the
  // card only says what to press.
  const view = live.waiting ? null : live.view;
  const ref = usePublishedHeight();
  const stale = invalid || busy || live.waiting;
  // Announced: only messages that need the player. "Updating" is visual only (and fades
  // in after a short delay), so fast answers never flicker or chatter.
  const status = invalid
    ? problem === null
      ? STATUS.finishTyping
      : `${STATUS.toUpdate} ${problem}`
    : live.waiting
      ? STATUS.pressRun
      : live.manual && busy
        ? STATUS.searching
        : view === null
          ? STATUS.first
          : "";
  return (
    <section className="answer c5" aria-labelledby="answer-title" ref={ref}>
      <h2 id="answer-title">Your answer</h2>
      <div className={`answer-body ${stale ? "stale" : ""} ${invalid ? "invalid" : ""}`} aria-busy={busy}>
        {(invalid || live.waiting) && view !== null && <p className="out-of-date">{STATUS.outOfDate}</p>}
        <div aria-live="polite" aria-atomic="true">
          {(view?.kind === "answer" ||
            view?.kind === "draws" ||
            view?.kind === "turns" ||
            view?.kind === "mulligan" ||
            view?.kind === "howmany") && <p className="headline">{view.headline}</p>}
          {(view?.kind === "answer" || view?.kind === "mulligan" || view?.kind === "howmany") &&
            view.details.map((d) => (
              <p key={d} className="detail">
                {d}
              </p>
            ))}
          {view?.kind === "turns" && <p>{turnsSummary(view)}</p>}
          {view?.kind === "problem" && (
            <div className="trouble">
              <p className="headline">{view.headline}</p>
              <p>{view.advice}</p>
            </div>
          )}
        </div>
        {view?.kind === "answer" && (
          <details>
            <summary>Show the exact numbers</summary>
            <p>More precisely: {view.precise}.</p>
            <p className="aside">
              Every answer is exact. As a fraction it is {view.fraction}: the calculator counts every possible
              order of your deck, which is why the numbers can be so large.
            </p>
          </details>
        )}
        {(view?.kind === "draws" ||
          view?.kind === "turns" ||
          view?.kind === "mulligan" ||
          view?.kind === "howmany") && (
          <p className="see-table">
            <a href="#answer-details">See the table</a>
          </p>
        )}
        {view?.kind === "problem" && view.details !== "" && (
          <details>
            <summary>Details for a bug report</summary>
            <p className="mono">{view.details}</p>
          </details>
        )}
      </div>
      {live.manual && !invalid && <RunButton onRun={live.run} running={busy} />}
      <div className="status-line">
        <p className={`status ${invalid ? "status-invalid" : ""}`} role="status">
          {status}
        </p>
        {busy && view !== null && !invalid && (
          <p className="updating" aria-hidden="true">
            {STATUS.updating}
          </p>
        )}
      </div>
    </section>
  );
}
