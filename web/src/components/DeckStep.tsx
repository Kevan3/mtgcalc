import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import { FORMATS, type Decklist, type FormatName, type FormState } from "../forms/model.ts";
import { cleanName, parseWhole, type FieldId } from "../forms/parse.ts";
import { HINTS, STEPS } from "../text/copy.ts";
import { DecklistInput } from "./DecklistInput.tsx";
import { describedBy, NoteText, ProblemText, TextField, type Problem } from "./Field.tsx";

interface Props {
  readonly form: FormState;
  /** What the core read from a pasted decklist (when it could). */
  readonly decklist: Decklist | undefined;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly note: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
}

function otherCards(form: FormState): number | null {
  const size = parseWhole(form.deckSize);
  if (size === null) return null;
  const listed = form.types.reduce((sum, t) => sum + (parseWhole(t.count) ?? 0), 0);
  return size - listed;
}

export function DeckStep({ form, decklist, dispatch, problem, note, touch }: Props): ReactNode {
  const size = parseWhole(form.deckSize);
  const other = otherCards(form);
  const tableProblem = problem("types");
  return (
    <section aria-labelledby="deck-title" className="step c1">
      <h2 id="deck-title">{STEPS.deck}</h2>

      <fieldset className="field">
        <legend>How do you want to describe your deck?</legend>
        <div className="buttons">
          {(["types", "list"] as const).map((mode) => (
            <label key={mode} className="radio">
              <input
                type="radio"
                name="deck-mode"
                checked={form.deckMode === mode}
                onChange={() => {
                  dispatch({ type: "deckMode", value: mode });
                }}
              />
              {mode === "types" ? "List card types (best for “what if” questions)" : "Paste a decklist"}
            </label>
          ))}
        </div>
      </fieldset>

      {form.deckMode === "list" ? (
        <DecklistInput form={form} decklist={decklist} dispatch={dispatch} problem={problem} touch={touch} />
      ) : (
        <>
          <div className="field">
            <span className="label" id="format-label">
              Format
            </span>
            <p className="hint" id="format-hint">
              {HINTS.format}
            </p>
            <div
              className="buttons"
              role="group"
              aria-labelledby="format-label"
              aria-describedby="format-hint"
            >
              {(Object.keys(FORMATS) as FormatName[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  className="choice"
                  aria-pressed={size === FORMATS[name].size && form.goFirst === FORMATS[name].goFirst}
                  onClick={() => {
                    dispatch({ type: "format", name });
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>

          <TextField
            id="deck-size"
            field="deckSize"
            label="Cards in your deck"
            hint={HINTS.deckSize}
            value={form.deckSize}
            numeric
            size="small"
            problem={problem("deckSize")}
            onBlur={() => {
              touch("deckSize");
            }}
            onChange={(value) => {
              dispatch({ type: "deckSize", value });
            }}
          />

          <div className={`field ${tableProblem ? "has-problem" : ""}`}>
            <span className="label" id="types-label">
              Card types
            </span>
            <p className="hint" id="types-hint">
              {HINTS.types}
            </p>
            <table
              className="types"
              aria-labelledby="types-label"
              aria-describedby={describedBy("types-hint", tableProblem?.id)}
            >
              <thead>
                <tr>
                  <th scope="col">Card type</th>
                  <th scope="col">How many</th>
                  <th scope="col">Also counts as</th>
                  <th scope="col">
                    <span className="visually-hidden">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {form.types.map((row, i) => {
                  const nameP = problem(`type:${row.id}:name`);
                  const countP = problem(`type:${row.id}:count`);
                  const alsoP = problem(`type:${row.id}:also`);
                  const alsoN = alsoP === undefined ? note(`type:${row.id}:also`) : undefined;
                  const label = cleanName(row.name) || `card type ${i + 1}`;
                  return (
                    <tr key={row.id}>
                      <td>
                        <input
                          type="text"
                          autoComplete="off"
                          aria-label={`Name of card type ${i + 1}`}
                          value={row.name}
                          aria-invalid={nameP ? true : undefined}
                          aria-describedby={nameP?.id}
                          data-field={`type:${row.id}:name`}
                          onBlur={() => {
                            touch(`type:${row.id}:name`);
                          }}
                          onChange={(e) => {
                            dispatch({ type: "typeChanged", id: row.id, patch: { name: e.target.value } });
                          }}
                        />
                        <ProblemText problem={nameP} />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="numeric"
                          autoComplete="off"
                          className="small"
                          aria-label={`How many ${label}`}
                          value={row.count}
                          aria-invalid={countP ? true : undefined}
                          aria-describedby={countP?.id}
                          data-field={`type:${row.id}:count`}
                          onBlur={() => {
                            touch(`type:${row.id}:count`);
                          }}
                          onChange={(e) => {
                            dispatch({ type: "typeChanged", id: row.id, patch: { count: e.target.value } });
                          }}
                        />
                        <ProblemText problem={countP} />
                      </td>
                      <td>
                        <input
                          type="text"
                          autoComplete="off"
                          aria-label={`Other types ${label} also counts as`}
                          placeholder="also counts as (optional)"
                          value={row.also}
                          aria-invalid={alsoP ? true : undefined}
                          aria-describedby={describedBy(alsoP?.id, alsoN?.id)}
                          data-field={`type:${row.id}:also`}
                          onBlur={() => {
                            touch(`type:${row.id}:also`);
                          }}
                          onChange={(e) => {
                            dispatch({ type: "typeChanged", id: row.id, patch: { also: e.target.value } });
                          }}
                        />
                        <ProblemText problem={alsoP} />
                        <NoteText note={alsoN} />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="remove"
                          aria-label={`Remove ${label}`}
                          onClick={() => {
                            dispatch({ type: "typeRemoved", id: row.id });
                          }}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <ProblemText problem={tableProblem} />
            <p className="aside">{HINTS.typeAlsoLong}</p>
            <button
              type="button"
              id="add-type"
              className="add"
              onClick={() => {
                dispatch({ type: "typeAdded" });
              }}
            >
              + Add a card type
            </button>
            {other !== null && other >= 0 && (
              <p className="note">
                {other === 0
                  ? "Every card in your deck has a type."
                  : `The other ${other} card${other === 1 ? "" : "s"} in your deck count${other === 1 ? "s" : ""} as “other cards”.`}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
