import { useEffect, useState } from "react";

/**
 * False while `value` keeps changing, true once it has stayed the same for `ms`.
 * Used so a half-typed number is not flagged while the player is still typing (FR-94).
 */
export function useSettled(value: unknown, ms: number): boolean {
  const [settledValue, setSettledValue] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettledValue(value);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [value, ms]);
  return Object.is(settledValue, value);
}

/** The `data-field` of the focused element (inputs name the form field they edit). */
export function useFocusedField(): string | null {
  const [field, setField] = useState<string | null>(null);
  useEffect(() => {
    const onFocus = (event: FocusEvent): void => {
      const target = event.target;
      setField(target instanceof HTMLElement ? (target.dataset["field"] ?? null) : null);
    };
    const onBlur = (): void => {
      setField(null);
    };
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onBlur);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onBlur);
    };
  }, []);
  return field;
}
