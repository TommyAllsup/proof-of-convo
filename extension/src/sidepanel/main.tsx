import React from "react";
import { createRoot } from "react-dom/client";

import "../styles.css";
import { ControlPanel } from "../shared/ControlPanel";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ControlPanel surface="sidepanel" />
  </React.StrictMode>
);

