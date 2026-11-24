/**
 * Small accessible building blocks: every input has a label, an optional hint and an
 * optional problem, both tied to the input with aria-describedby (FR-96).
 */
import type { ReactNode } from "react";

export interface Problem {
  readonly id: string;
  readonly message: string;
}

/** A problem message; `role="alert"` is avoided on purpose (it would interrupt typing). */
export function ProblemText({ problem }: { readonly problem: Problem | undefined }): ReactNode {
  if (problem === undefined) return null;
  return (
    <p className="problem" id={problem.id}>
      {problem.message}
    </p>
  );
}

/** A friendly heads-up that does not stop the answer (e.g. a likely typo). */
export function NoteText({ note }: { readonly note: Problem | undefined }): ReactNode {
  if (note === undefined) return null;
  return (
    <p className="field-note" id={note.id}>
      {note.message}
    </p>
  );
}

export function describedBy(...ids: (string | undefined)[]): string | undefined {
  const list = ids.filter((x): x is string => x !== undefined);
  return list.length > 0 ? list.join(" ") : undefined;
}

interface TextFieldProps {
  readonly id: string;
  /** The form field this input edits (see App: problems wait until typing pauses). */
  readonly field: string;
  readonly label: string;
  readonly hint?: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly onBlur?: () => void;
  readonly problem?: Problem | undefined;
  readonly numeric?: boolean;
  readonly size?: "small" | "wide";
}

export function TextField(props: TextFieldProps): ReactNode {
  const { id, field, label, hint, value, onChange, onBlur, problem, numeric = false, size = "wide" } = props;
  const hintId = hint === undefined ? undefined : `${id}-hint`;
  return (
    <div className={`field ${problem ? "has-problem" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {hint !== undefined && (
        <p className="hint" id={hintId}>
          {hint}
        </p>
      )}
      <input
        id={id}
        data-field={field}
        className={size}
        type="text"
        inputMode={numeric ? "numeric" : "text"}
        autoComplete="off"
        value={value}
        aria-invalid={problem ? true : undefined}
        aria-describedby={describedBy(hintId, problem?.id)}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        onBlur={onBlur}
      />
      <ProblemText problem={problem} />
    </div>
  );
}
