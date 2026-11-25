import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import type { FormState, HowManyAim, HowManyMode } from "../forms/model.ts";
import { cleanName, type FieldId } from "../forms/parse.ts";
import { HINTS } from "../text/copy.ts";
import { ProblemText, TextField, type Problem } from "./Field.tsx";

interface Props {
  readonly form: FormState;
  readonly labels: Readonly<Record<string, string>>;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
}

const MODES: readonly (readonly [HowManyMode, string])[] = [
  ["one", "How many of one card type should I play?"],
  ["share", "How should I share cards between card types?"],
];

const AIMS: readonly (readonly [HowManyAim, string])[] = [
  ["best", "The best chance I can get"],
  ["target", "A target chance I choose, with as few cards as possible"],
];

/** "How many should I play?" (FR-50 – FR-54): what to try, and what counts as success. */
export function HowManyInputs({ form, labels, dispatch, problem, touch }: Props): ReactNode {
  const names = form.types.map((t) => cleanName(t.name)).filter((n) => n !== "");
  const rows = form.hmMode === "one" ? form.hmVary.slice(0, 1) : form.hmVary;
  const sectionP = problem("howmany");
  if (form.deckMode !== "types") {
    return (
      <div className="field">
        <p>
          This question changes how many cards of each type you play, so it needs your deck described as card
          types.
        </p>
        <button
          type="button"
          onClick={() => {
            dispatch({ type: "deckMode", value: "types" });
          }}
        >
          Describe my deck as card types
        </button>
      </div>
    );
  }
  return (
    <>
      <fieldset className="field">
        <legend>What should the calculator work out?</legend>
        <div className="buttons stacked">
          {MODES.map(([mode, text]) => (
            <label key={mode} className="radio">
              <input
                type="radio"
                name="hm-mode"
                checked={form.hmMode === mode}
                onChange={() => {
                  dispatch({ type: "howManyChanged", patch: { hmMode: mode } });
                }}
              />
              {text}
            </label>
          ))}
        </div>
      </fieldset>
      <div className={`field ${sectionP ? "has-problem" : ""}`}>
        <span className="label" id="vary-label">
          {form.hmMode === "one"
            ? "Which card type, and from how many to how many?"
            : "Which card types to try, and their ranges"}
        </span>
        <p className="hint">{HINTS.vary}</p>
        <ol className="goal" aria-labelledby="vary-label">
          {rows.map((row, i) => {
            const typeP = problem(`vary:${row.id}:cardType`);
            const rangeP = problem(`vary:${row.id}:range`);
            const n = String(i + 1);
            const options = names.includes(row.cardType) ? names : ["", ...names];
            return (
              <li key={row.id} className="goal-line" data-row={row.id}>
                <div className="line" role="group" aria-label={`Card type to try ${n}`}>
                  <select
                    aria-label={`Try ${n}: card type`}
                    data-field={`vary:${row.id}:cardType`}
                    value={row.cardType}
                    aria-invalid={typeP ? true : undefined}
                    aria-describedby={typeP?.id}
                    onChange={(e) => {
                      touch(`vary:${row.id}:cardType`);
                      dispatch({ type: "varyChanged", id: row.id, patch: { cardType: e.target.value } });
                    }}
                  >
                    {options.map((name) => (
                      <option key={name} value={name}>
                        {name === "" ? "choose a card type" : (labels[name] ?? name)}
                      </option>
                    ))}
                  </select>
                  <span>from</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="small"
                    aria-label={`Try ${n}: from`}
                    data-field={`vary:${row.id}:range`}
                    value={row.low}
                    aria-invalid={rangeP ? true : undefined}
                    aria-describedby={rangeP?.id}
                    onBlur={() => {
                      touch(`vary:${row.id}:range`);
                    }}
                    onChange={(e) => {
                      dispatch({ type: "varyChanged", id: row.id, patch: { low: e.target.value } });
                    }}
                  />
                  <span>to</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="small"
                    aria-label={`Try ${n}: to`}
                    data-field={`vary:${row.id}:range`}
                    value={row.high}
                    aria-invalid={rangeP ? true : undefined}
                    aria-describedby={rangeP?.id}
                    onBlur={() => {
                      touch(`vary:${row.id}:range`);
                    }}
                    onChange={(e) => {
                      dispatch({ type: "varyChanged", id: row.id, patch: { high: e.target.value } });
                    }}
                  />
                  {form.hmMode === "share" && (
                    <button
                      type="button"
                      className="remove"
                      aria-label={`Remove card type to try ${n}`}
                      onClick={() => {
                        dispatch({ type: "varyRemoved", id: row.id });
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
                <ProblemText problem={typeP} />
                <ProblemText problem={rangeP} />
              </li>
            );
          })}
        </ol>
        <ProblemText problem={sectionP} />
        {form.hmMode === "share" && rows.length < 2 && (
          <p className="note">Add a second card type to try, so the cards can be shared between them.</p>
        )}
        {form.hmMode === "share" && (
          <button
            type="button"
            id="add-vary"
            className="add"
            onClick={() => {
              dispatch({ type: "varyAdded" });
            }}
          >
            + Add a card type to try
          </button>
        )}
      </div>
      {form.hmMode === "share" && (
        <TextField
          id="hm-slots"
          field="hmSlots"
          label="Cards allowed between them"
          hint={HINTS.slots}
          value={form.hmSlots}
          numeric
          size="small"
          problem={problem("hmSlots")}
          onBlur={() => {
            touch("hmSlots");
          }}
          onChange={(value) => {
            dispatch({ type: "howManyChanged", patch: { hmSlots: value } });
          }}
        />
      )}
      <fieldset className="field">
        <legend>Aim for</legend>
        <p className="hint">{HINTS.aim}</p>
        <div className="buttons stacked">
          {AIMS.map(([aim, text]) => (
            <label key={aim} className="radio">
              <input
                type="radio"
                name="hm-aim"
                checked={form.hmAim === aim}
                onChange={() => {
                  dispatch({ type: "howManyChanged", patch: { hmAim: aim } });
                }}
              />
              {text}
            </label>
          ))}
        </div>
      </fieldset>
      {form.hmAim === "target" && (
        <TextField
          id="hm-target"
          field="hmTarget"
          label="Target: in what percent of games?"
          hint={HINTS.target}
          value={form.hmTarget}
          size="small"
          problem={problem("hmTarget")}
          onBlur={() => {
            touch("hmTarget");
          }}
          onChange={(value) => {
            dispatch({ type: "howManyChanged", patch: { hmTarget: value } });
          }}
        />
      )}
    </>
  );
}
