import type { Dispatch, ReactNode } from "react";

import type { Action } from "../app/state.ts";
import { ANY_CARD, MAX_MULLIGANS, type FormState } from "../forms/model.ts";
import { parseWhole, type FieldId } from "../forms/parse.ts";
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

/** A keep line's amount in words: "2 to 5", or "2" when both numbers are the same. */
function amountWords(min: string, max: string): string {
  const [lo, hi] = [parseWhole(min), parseWhole(max)];
  return lo !== null && lo === hi ? String(lo) : `${min.trim()} to ${max.trim()}`;
}

/**
 * The keep rule in words (Python's `keep_rule_words`), e.g. "keep a hand with 3 to 4 land,
 * or with 2 land and 1 to 7 ramp".
 */
export function keepRuleWords(form: FormState, labels: Readonly<Record<string, string>>): string {
  if (form.keep.length === 0) return "always keep your first hand";
  const kinds = form.keep.map((group) =>
    group.rules
      .map((r) => {
        const what = r.cardType === ANY_CARD ? "cards" : (labels[r.cardType] ?? r.cardType);
        return `${amountWords(r.min, r.max)} ${what}`;
      })
      .join(" and "),
  );
  return `keep a hand with ${kinds.join(", or with ")}`;
}

/** Card types a keep line may count ("any card" would count the whole hand). */
function KeepOptions({
  names,
  labels,
  current,
}: Pick<Props, "names" | "labels"> & { current: string }): ReactNode {
  const typed = names.filter((n) => n !== ANY_CARD);
  const options = typed.includes(current) ? typed : ["", ...typed];
  return options.map((name) => (
    <option key={name} value={name}>
      {name === "" ? "choose a card type" : (labels[name] ?? name)}
    </option>
  ));
}

/** "Which hands do you keep?": kinds of hand (any one will do), each with lines that must all hold. */
function KeepKinds({ form, names, labels, dispatch, problem, touch }: Props): ReactNode {
  return (
    <div className="field">
      <span className="label" id="keep-label">
        Which hands do you keep?
      </span>
      <p className="hint" id="keep-hint">
        {HINTS.keep}
      </p>
      {form.keep.length === 0 ? (
        <p className="note">You keep every hand (you never mulligan).</p>
      ) : (
        <ol className="keep-kinds" aria-labelledby="keep-label" aria-describedby="keep-hint">
          {form.keep.map((group, g) => {
            const kind = g + 1;
            const titleId = `keep-kind-${group.id}`;
            return (
              <li key={group.id} className="keep-kind" data-group={group.id}>
                <span className="kind-title" id={titleId}>
                  {g === 0 ? "Keep a hand that has" : "Or keep a hand that has"}
                </span>
                <ol className="goal" aria-labelledby={titleId}>
                  {group.rules.map((row, i) => {
                    const typeP = problem(`keep:${row.id}:cardType`);
                    const rangeP = problem(`keep:${row.id}:range`);
                    const where = `Kind of hand ${String(kind)}, line ${String(i + 1)}`;
                    return (
                      <li key={row.id} className="goal-line" data-row={row.id}>
                        <div
                          className={`line ${typeP || rangeP ? "has-problem" : ""}`}
                          role="group"
                          aria-label={where}
                        >
                          {i > 0 && <span>and</span>}
                          <select
                            aria-label={`${where}: card type`}
                            data-field={`keep:${row.id}:cardType`}
                            value={row.cardType}
                            aria-invalid={typeP ? true : undefined}
                            aria-describedby={typeP?.id}
                            onChange={(e) => {
                              touch(`keep:${row.id}:cardType`);
                              dispatch({
                                type: "keepRuleChanged",
                                id: row.id,
                                patch: { cardType: e.target.value },
                              });
                            }}
                          >
                            <KeepOptions names={names} labels={labels} current={row.cardType} />
                          </select>
                          <span>between</span>
                          <input
                            type="text"
                            inputMode="numeric"
                            className="small"
                            aria-label={`${where}: at least this many`}
                            data-field={`keep:${row.id}:range`}
                            value={row.min}
                            aria-invalid={rangeP ? true : undefined}
                            aria-describedby={rangeP?.id}
                            onBlur={() => {
                              touch(`keep:${row.id}:range`);
                            }}
                            onChange={(e) => {
                              dispatch({
                                type: "keepRuleChanged",
                                id: row.id,
                                patch: { min: e.target.value },
                              });
                            }}
                          />
                          <span>and</span>
                          <input
                            type="text"
                            inputMode="numeric"
                            className="small"
                            aria-label={`${where}: at most this many`}
                            data-field={`keep:${row.id}:range`}
                            value={row.max}
                            aria-invalid={rangeP ? true : undefined}
                            aria-describedby={rangeP?.id}
                            onBlur={() => {
                              touch(`keep:${row.id}:range`);
                            }}
                            onChange={(e) => {
                              dispatch({
                                type: "keepRuleChanged",
                                id: row.id,
                                patch: { max: e.target.value },
                              });
                            }}
                          />
                          <button
                            type="button"
                            className="remove"
                            aria-label={`Remove ${where.toLowerCase()}`}
                            onClick={() => {
                              dispatch({ type: "keepRuleRemoved", id: row.id });
                            }}
                          >
                            ×
                          </button>
                        </div>
                        <ProblemText problem={typeP} />
                        <ProblemText problem={rangeP} />
                      </li>
                    );
                  })}
                </ol>
                <button
                  type="button"
                  id={`add-keep-line-${group.id}`}
                  className="add"
                  aria-label={`And also, in kind of hand ${String(kind)}: add a card type`}
                  onClick={() => {
                    dispatch({ type: "keepRuleAdded", group: group.id });
                  }}
                >
                  + And also…
                </button>
              </li>
            );
          })}
        </ol>
      )}
      <button
        type="button"
        id="add-keep-kind"
        className="add"
        onClick={() => {
          dispatch({ type: "keepGroupAdded" });
        }}
      >
        {form.keep.length === 0 ? "+ Add a kind of hand to keep" : "+ Or keep another kind of hand"}
      </button>
      <p className="note">So: {keepRuleWords(form, labels)}.</p>
    </div>
  );
}

/** Step 2, mulligans: the London mulligan, described the way players think of it. */
export function MulliganSettings(props: Props): ReactNode {
  const { form, names, labels, dispatch, problem, touch } = props;
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
          <KeepKinds {...props} />

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
