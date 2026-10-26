import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import navigation from "@daon2-user/contracts/navigation.json";
import screens from "@daon2-user/contracts/screens.json";
import "@daon2-user/design-tokens/tokens.css";

import { EvidenceHubApp } from "./evidence-hub.jsx";

const homeRoute = navigation.routes.find((route) => route.route_id === "home");
const homeScreen = screens.screens.find((screen) => screen.screen_id === "home");

if (!homeRoute || !homeScreen) throw new Error("EVIDENCE_HOME_CONTRACT_MISSING");

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <EvidenceHubApp route={homeRoute} screen={homeScreen} />
  </StrictMode>
);
