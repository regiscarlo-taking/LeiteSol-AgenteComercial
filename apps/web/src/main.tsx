import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";

console.info("[web] Aplicacao inicializada.");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
