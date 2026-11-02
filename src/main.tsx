import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { initPwa } from "./lib/pwa";
import "./styles.css";

// 埋め込みプレビュー（VITE_EMBED=1）ではURLを使わないルーターにし、Service Workerも登録しない
const embed = import.meta.env.VITE_EMBED === "1";
const Router = embed ? MemoryRouter : BrowserRouter;
if (!embed) initPwa();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Router>
      <App />
    </Router>
  </StrictMode>,
);
