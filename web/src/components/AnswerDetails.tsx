import type { ReactNode } from "react";

import type { DrawsRow, View } from "../forms/answer.ts";

/**
 * A table that may scroll sideways in the narrow answer column. Keyboard users must be
 * able to scroll it too (WCAG 2.1.1), so the scrolling box is focusable and named.
 */
function Scroll({
  id,
  title,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
}): ReactNode {
  return (
    <>
      <h3 className="table-title" id={id}>
        {title}
      </h3>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region must be focusable (WCAG 2.1.1) */}
      <div className="table-scroll" role="region" aria-labelledby={id} tabIndex={0}>
        {children}
      </div>
    </>
  );
}

/** "Opening hand" / "By turn 3" for table rows. */
function when(turn: number): string {
  return turn === 0 ? "Opening hand" : `By turn ${String(turn)}`;
}

/** How many "at least" columns to show: up to the last one any turn reaches 0.5%. */
function columns(rows: readonly DrawsRow[]): number[] {
  let last = 1;
  for (const row of rows) {
    for (const c of row.counts) {
      if (c.k >= 1 && parseFloat(c.atLeast) >= 0.5) last = Math.max(last, c.k);
    }
  }
  return Array.from({ length: Math.min(last, 8) }, (_, i) => i + 1);
}

function DrawsTables({ view }: { readonly view: View & { kind: "draws" } }): ReactNode {
  const ks = columns(view.rows);
  return (
    <>
      <Scroll id="draws-table" title={`Chance of having seen at least this many ${view.what}`}>
        <table className="results" aria-labelledby="draws-table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Average</th>
              {ks.map((k) => (
                <th key={k} scope="col">
                  {k}+
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.rows.map((row) => (
              <tr key={row.turn}>
                <th scope="row">{when(row.turn)}</th>
                <td>{row.average}</td>
                {ks.map((k) => (
                  <td key={k}>{row.counts[k]?.atLeast ?? "0.0%"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="aside">“3+” means 3 or more. The average is how many you see in a typical game.</p>
      <details>
        <summary>All the numbers</summary>
        {view.rows.map((row) => (
          <Scroll
            key={row.turn}
            id={`draws-turn-${String(row.turn)}`}
            title={`${when(row.turn)} (average ${row.average})`}
          >
            <table className="results" aria-labelledby={`draws-turn-${String(row.turn)}`}>
              <thead>
                <tr>
                  <th scope="col">How many</th>
                  <th scope="col">Exactly</th>
                  <th scope="col">This many or more</th>
                  <th scope="col">This many or fewer</th>
                </tr>
              </thead>
              <tbody>
                {row.counts.map((c) => (
                  <tr key={c.k}>
                    <th scope="row">
                      {c.k} {view.what}
                    </th>
                    <td>{c.exactly}</td>
                    <td>{c.atLeast}</td>
                    <td>{c.atMost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        ))}
      </details>
    </>
  );
}

function TurnsTable({ view }: { readonly view: View & { kind: "turns" } }): ReactNode {
  return (
    <Scroll id="turns-table" title="Your chance, turn by turn">
      <table className="results" aria-labelledby="turns-table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Cards seen</th>
            <th scope="col">Chance</th>
            <th scope="col">In words</th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row) => (
            <tr key={row.turn}>
              <th scope="row">{row.turn === 0 ? "Opening hand" : `Turn ${String(row.turn)}`}</th>
              <td>{row.cardsSeen}</td>
              <td>{row.chance}</td>
              <td>{row.words}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="aside">“Cards seen” is your opening hand plus every card drawn so far.</p>
    </Scroll>
  );
}

function AdviceTables({ view }: { readonly view: View & { kind: "mulligan" } }): ReactNode {
  return (
    <>
      <Scroll id="your-plan" title="Your plan">
        <table className="results" aria-labelledby="your-plan">
          <thead>
            <tr>
              <th scope="col">Step</th>
              <th scope="col">Get here</th>
              <th scope="col">Keep it</th>
              <th scope="col">Good game if kept</th>
            </tr>
          </thead>
          <tbody>
            {view.yourPlan.map((r) => (
              <tr key={r.step}>
                <th scope="row">{r.step}</th>
                <td>{r.getHere}</td>
                <td>{r.keepIt}</td>
                <td>{r.goodGame}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="aside">
        “Get here”: how often you mulligan this far. “Keep it”: how often you keep the hand at this step.
        “Good game if kept”: your chance of a good game if you keep it.
      </p>
      <h3 className="table-title">The best possible plan ({view.best.value})</h3>
      {view.best.steps.map((step, i) => (
        <details key={step.title}>
          <summary>
            {step.title} (keeps {step.keepIt} of hands)
          </summary>
          <Scroll id={`best-step-${String(i)}`} title={`Hands at this step: ${step.title}`}>
            <table className="results" aria-labelledby={`best-step-${String(i)}`}>
              <thead>
                <tr>
                  <th scope="col">Hand drawn</th>
                  <th scope="col">How often</th>
                  <th scope="col">Good game if kept</th>
                </tr>
              </thead>
              <tbody>
                {step.hands.map((h) => (
                  <tr key={h.text}>
                    <th scope="row">{h.text.replace("  ->  ", " → ")}</th>
                    <td>{h.chance}</td>
                    <td>{h.goodGame}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
        </details>
      ))}
      <p className="aside">
        Hands are grouped by the card types this question uses; “other” is everything else.
      </p>
    </>
  );
}

function OptionsTable({ view }: { readonly view: View & { kind: "howmany" } }): ReactNode {
  return (
    <Scroll id="options-table" title="Options tried, highest chance first">
      <table className="results" aria-labelledby="options-table">
        <thead>
          <tr>
            <th scope="col">Option tried</th>
            <th scope="col">Chance</th>
            <th scope="col">In words</th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((r) => (
            <tr key={r.option}>
              <th scope="row">
                {r.option}
                {r.chosen && (
                  <>
                    {" "}
                    <span className="chosen">(your answer)</span>
                  </>
                )}
              </th>
              <td>{r.chance}</td>
              <td>{r.words}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

/**
 * The tables of "How many will I draw?", "Turn by turn" and "Should I mulligan?", under the answer card.
 * Not announced as a whole to screen readers (the headline is); they are ordinary tables
 * with titles and header cells to explore.
 */
export function AnswerDetails({
  view,
  stale,
}: {
  readonly view: View | null;
  readonly stale: boolean;
}): ReactNode {
  if (view === null || view.kind === "answer" || view.kind === "problem") return null;
  return (
    <section
      className={`answer-details ${stale ? "stale" : ""}`}
      aria-label="The details"
      id="answer-details"
    >
      {view.kind === "draws" ? (
        <DrawsTables view={view} />
      ) : view.kind === "turns" ? (
        <TurnsTable view={view} />
      ) : view.kind === "howmany" ? (
        <OptionsTable view={view} />
      ) : (
        <AdviceTables view={view} />
      )}
    </section>
  );
}
