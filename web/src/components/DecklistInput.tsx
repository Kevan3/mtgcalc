import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import type { Decklist, FormState } from "../forms/model.ts";
import type { FieldId } from "../forms/parse.ts";
import { HINTS } from "../text/copy.ts";
import { describedBy, ProblemText, type Problem } from "./Field.tsx";

interface Props {
  readonly form: FormState;
  readonly decklist: Decklist | undefined;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
}

/** What the page read from the decklist, so the player can check it at a glance. */
export function deckSummary(d: Decklist): string {
  const parts = [`${String(d.size)} cards in the deck`];
  if (d.commanders.length > 0) parts.push(`commander: ${d.commanders.join(", ")}`);
  const tags = d.tags.map(([t, n]) => `${t} ${String(n)}`);
  const tagText =
    tags.length > 0 ? `Tags: ${tags.join(", ")}.` : "No #tags yet: add some to ask about kinds of cards.";
  return `Read ${parts.join("; ")}. ${tagText}`;
}

/** Step 1 with a pasted decklist (FR-60 – FR-62). */
export function DecklistInput({ form, decklist, dispatch, problem, touch }: Props): ReactNode {
  const p = problem("decklist");
  return (
    <div className={`field ${p ? "has-problem" : ""}`}>
      <label htmlFor="decklist">Your decklist</label>
      <p className="hint" id="decklist-hint">
        {HINTS.decklist}
      </p>
      <textarea
        id="decklist"
        data-field="decklist"
        rows={10}
        spellCheck={false}
        placeholder={"Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n36 Forest #land\n1 Sol Ring #ramp\n..."}
        value={form.decklist}
        aria-invalid={p ? true : undefined}
        aria-describedby={describedBy("decklist-hint", p?.id, decklist ? "decklist-summary" : undefined)}
        onBlur={() => {
          touch("decklist");
        }}
        onChange={(e) => {
          dispatch({ type: "decklist", value: e.target.value });
        }}
      />
      <ProblemText problem={p} />
      {decklist !== undefined && (
        <p className="note" id="decklist-summary">
          {deckSummary(decklist)}
        </p>
      )}
    </div>
  );
}
