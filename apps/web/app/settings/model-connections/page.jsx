import navigation from "@daon2-user/contracts/navigation.json";
import screens from "@daon2-user/contracts/screens.json";

import { ProviderSettingsWorkspace } from "../../../components/provider-settings-workspace.jsx";

// 내부 ASR 주소는 서버 구성(Compose 환경 변수)으로만 받는다. 코드에 주소 리터럴을 두지 않는다(보안 스캔 BROWSER_INTERNAL_ADDRESS).
const QA_ASR_BASE_URL = process.env.DAON_QA_ASR_BASE_URL || "";
const route = navigation.routes.find((item) => item.route_id === "model_connections");
const screen = screens.screens.find((item) => item.screen_id === "model_connections");

export default function ModelConnectionsPage() {
  // 내부 ASR 엔드포인트는 서버 구성에서만 정해 Browser Source에 직접 URL을 두지 않는다.
  return <ProviderSettingsWorkspace routeId={route.route_id} screenId={screen.screen_id} showNotebookLink qaAsrBaseUrl={QA_ASR_BASE_URL} />;
}
