// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnswerPanel } from "./AnswerPanel.tsx";

describe("AnswerPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("publishes its height for the phone layout, and cleans up", () => {
    let report: (() => void) | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          report = callback;
        }
        observe(): void {
          /* the test reports sizes by hand */
        }
        disconnect(): void {
          disconnect();
        }
      },
    );
    const view = render(
      <AnswerPanel
        live={{ view: null, busy: true, invalid: false, waiting: false, manual: false, run: () => undefined }}
        problem={null}
      />,
    );
    report?.();
    expect(document.documentElement.style.getPropertyValue("--answer-height")).toMatch(/^\d+px$/u);
    view.unmount();
    expect(disconnect).toHaveBeenCalled();
    expect(document.documentElement.style.getPropertyValue("--answer-height")).toBe("");
  });

  it("works without ResizeObserver", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    expect(() =>
      render(
        <AnswerPanel
          live={{
            view: null,
            busy: true,
            invalid: false,
            waiting: false,
            manual: false,
            run: () => undefined,
          }}
          problem={null}
        />,
      ),
    ).not.toThrow();
  });
});
