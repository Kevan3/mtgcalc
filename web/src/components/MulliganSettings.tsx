import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import { ANY_CARD, MAX_MULLIGANS, type FormState } from "../forms/model.ts";
import type { FieldId } from "../forms/parse.ts";
import { HINTS } from "../text/copy.ts";
import { describedBy, ProblemText, type Problem } from "./Field.tsx";

interface Props {
  readonly form: FormState;
  /** The card types a list may pick, then "any card". */
  readonly names: readonly string[];
  readonly labels: Readonly<Record<string, string>>;
  readonly dispatch: Dispatch<Action>;
  readonly problem: (field: FieldId) => Problem | undefined;
  readonly touch: (field: FieldId) => void;
}

function TypeOptions({
  names,
  labels,
  current,
}: Pick<Props, "names" | "labels"> & { current: string }): ReactNode {
  const options = names.includes(current) ? names : ["", ...names];
  return options.map((name) => (
    <option key={name} value={name}>
      {name === "" ? "choose a card type" : name === ANY_CARD ? "cards of any type" : (labels[name] ?? name)}
    </option>
  ));
}

/** The keep rule in words (Python's `keep_rule_words`), e.g. "keep a hand with 2 to 5 land". */
export function keepRuleWords(form: FormState, labels: Readonly<Record<string, string>>): string {
  if (form.keepType === "") return "always keep your first hand";
  const what = form.keepType === ANY_CARD ? "cards" : (labels[form.keepType] ?? form.keepType);
  return `keep a hand with ${form.keepMin.trim()} to ${form.keepMax.trim()} ${what}`;
}

/** Step 2, mulligans: the London mulligan, described the way players think of it. */
export function MulliganSettings({ form, names, labels, dispatch, problem, touch }: Props): ReactNode {
  const keepP = problem("keepRule");
  const protectP = problem("protect");
  const maxP = problem("maxMulligans");
  return (
    <fieldset className="field">
      <legend>Mulligans</legend>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.mulligans}
          aria-describedby="mull-hint"
          onChange={(e) => {
            dispatch({ type: "mulligans", value: e.target.checked });
          }}
        />
        Mulligan bad opening hands
      </label>
      <p className="hint" id="mull-hint">
        {HINTS.mulligans}
      </p>
      {form.mulligans && (
        <div className="mulligan">
          <div className={`field ${keepP ? "has-problem" : ""}`}>
            <span className="label" id="keep-label">
              Which hands do you keep?
            </span>
            <div className="line" role="group" aria-labelledby="keep-label">
              <select
                aria-label="Keep: which card type to count"
                value={form.keepType}
                data-field="keepRule"
                aria-invalid={keepP ? true : undefined}
                aria-describedby={keepP?.id}
                onChange={(e) => {
                  dispatch({ type: "mulliganChanged", patch: { keepType: e.target.value } });
                }}
              >
                <option value="">any hand (never mulligan)</option>
                {names
                  .filter((n) => n !== ANY_CARD)
                  .map((n) => (
                    <option key={n} value={n}>
                      by its number of {labels[n] ?? n}
                    </option>
                  ))}
              </select>
              {form.keepType !== "" && (
                <>
                  <span>between</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="small"
                    aria-label="Keep: at least this many"
                    data-field="keepRule"
                    value={form.keepMin}
                    onBlur={() => {
                      touch("keepRule");
                    }}
                    onChange={(e) => {
                      dispatch({ type: "mulliganChanged", patch: { keepMin: e.target.value } });
                    }}
                  />
                  <span>and</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    className="small"
                    aria-label="Keep: at most this many"
                    data-field="keepRule"
                    value={form.keepMax}
                    onBlur={() => {
                      touch("keepRule");
                    }}
                    onChange={(e) => {
                      dispatch({ type: "mulliganChanged", patch: { keepMax: e.target.value } });
                    }}
                  />
                </>
              )}
            </div>
            <p className="note">So: {keepRuleWords(form, labels)}.</p>
            <p className="hint">{HINTS.keep}</p>
            <ProblemText problem={keepP} />
          </div>

          <div className={`field ${protectP ? "has-problem" : ""}`}>
            <span className="label" id="protect-label">
              When you put cards on the bottom, keep these first
            </span>
            <p className="hint" id="protect-hint">
              {HINTS.protect}
            </p>
            <ol
              className="goal"
              aria-labelledby="protect-label"
              aria-describedby={describedBy("protect-hint", protectP?.id)}
            >
              {form.protect.map((row, i) => {
                const typeP = problem(`protect:${row.id}:cardType`);
                const upP = problem(`protect:${row.id}:upTo`);
                const n = i + 1;
                return (
                  <li key={row.id} className="goal-line" data-row={row.id}>
                    <div className="line" role="group" aria-label={`Keep first, line ${String(n)}`}>
                      <select
                        aria-label={`Keep first ${String(n)}: card type`}
                        data-field={`protect:${row.id}:cardType`}
                        value={row.cardType}
                        aria-invalid={typeP ? true : undefined}
                        aria-describedby={typeP?.id}
                        onChange={(e) => {
                          // Choosing from a list is not typing: its problem may show at once.
                          touch(`protect:${row.id}:cardType`);
                          dispatch({
                            type: "protectChanged",
                            id: row.id,
                            patch: { cardType: e.target.value },
                          });
                        }}
                      >
                        <TypeOptions names={names} labels={labels} current={row.cardType} />
                      </select>
                      <span>up to</span>
                      <input
                        type="text"
                        inputMode="numeric"
                        className="small"
                        aria-label={`Keep first ${String(n)}: up to how many`}
                        data-field={`protect:${row.id}:upTo`}
                        value={row.upTo}
                        aria-invalid={upP ? true : undefined}
                        aria-describedby={upP?.id}
                        onBlur={() => {
                          touch(`protect:${row.id}:upTo`);
                        }}
                        onChange={(e) => {
                          dispatch({ type: "protectChanged", id: row.id, patch: { upTo: e.target.value } });
                        }}
                      />
                      <button
                        type="button"
                        className="remove"
                        aria-label={`Remove keep-first line ${String(n)}`}
                        onClick={() => {
                          dispatch({ type: "protectRemoved", id: row.id });
                        }}
                      >
                        ×
                      </button>
                    </div>
                    <ProblemText problem={typeP} />
                    <ProblemText problem={upP} />
                  </li>
                );
              })}
            </ol>
            <ProblemText problem={protectP} />
            <button
              type="button"
              id="add-protect"
              className="add"
              onClick={() => {
                dispatch({ type: "protectAdded" });
              }}
            >
              + Add a card type to keep first
            </button>
          </div>

          <div className={`field ${maxP ? "has-problem" : ""}`}>
            <label htmlFor="max-mulligans">Most mulligans you will take</label>
            <p className="hint" id="max-mulligans-hint">
              {HINTS.maxMulligans}
            </p>
            <input
              id="max-mulligans"
              type="text"
              inputMode="numeric"
              className="small"
              data-field="maxMulligans"
              value={form.maxMulligans}
              aria-invalid={maxP ? true : undefined}
              aria-describedby={describedBy("max-mulligans-hint", maxP?.id)}
              onBlur={() => {
                touch("maxMulligans");
              }}
              onChange={(e) => {
                dispatch({ type: "mulliganChanged", patch: { maxMulligans: e.target.value } });
              }}
            />
            <ProblemText problem={maxP} />
            <p className="hint">{`Up to ${String(MAX_MULLIGANS)}.`}</p>
          </div>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.freeFirst}
              aria-describedby="free-hint"
              onChange={(e) => {
                dispatch({ type: "mulliganChanged", patch: { freeFirst: e.target.checked } });
              }}
            />
            My first mulligan is free
          </label>
          <p className="hint" id="free-hint">
            {HINTS.free}
          </p>
        </div>
      )}
    </fieldset>
  );
}
