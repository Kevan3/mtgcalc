import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import type { FormState } from "../forms/model.ts";
import type { FieldId } from "../forms/parse.ts";
import { HINTS, STEPS } from "../text/copy.ts";
import { TextField, type Problem } from "./Field.tsx";
import { MulliganSettings } from "./MulliganSettings.tsx";

interface Props {
  readonly form: FormState;
  readonly names: readonly string[];
  readonly labels: Readonly<Record<string, string>>;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
}

export function PlayStep({ form, names, labels, dispatch, problem, touch }: Props): ReactNode {
  return (
    <section aria-labelledby="play-title" className="step">
      <h2 id="play-title">{STEPS.play}</h2>
      <fieldset className="field">
        <legend>Do you go first?</legend>
        <p className="hint" id="go-first-hint">
          {HINTS.goFirst}
        </p>
        <div className="buttons">
          {([true, false] as const).map((value) => (
            <label key={String(value)} className="radio">
              <input
                type="radio"
                name="go-first"
                checked={form.goFirst === value}
                aria-describedby="go-first-hint"
                onChange={() => {
                  dispatch({ type: "goFirst", value });
                }}
              />
              {value ? "Yes, I go first (no draw on turn 1)" : "No, I draw on turn 1"}
            </label>
          ))}
        </div>
      </fieldset>
      <TextField
        id="draws"
        field="drawsPerTurn"
        label="Cards you draw each turn"
        hint={HINTS.draws}
        value={form.drawsPerTurn}
        numeric
        size="small"
        problem={problem("drawsPerTurn")}
        onBlur={() => {
          touch("drawsPerTurn");
        }}
        onChange={(value) => {
          dispatch({ type: "drawsPerTurn", value });
        }}
      />
      <MulliganSettings
        form={form}
        names={names}
        labels={labels}
        dispatch={dispatch}
        problem={problem}
        touch={touch}
      />
    </section>
  );
}
