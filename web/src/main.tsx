import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import { loadCore } from "./engine/core.ts";
import "./styles.css";

const element = document.getElementById("root");
if (element === null) throw new Error("index.html has no #root element");
const root = createRoot(element);

// The core reads decklists and rules on the page; it loads in a few milliseconds (the
// worker shares the download). The page renders once it is ready.
loadCore().then(
  (core) => {
    root.render(
      <StrictMode>
        <App core={core} />
      </StrictMode>,
    );
  },
  () => {
    root.render(
      <p className="page">
        Sorry, this browser could not start the calculator. Please try an up-to-date version of Firefox,
        Chrome, Edge or Safari.
      </p>,
    );
  },
);
