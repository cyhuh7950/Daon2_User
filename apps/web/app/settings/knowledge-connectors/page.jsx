"use client";

import { KnowledgeConnectorsPane } from "@daon2-user/ui/knowledge-connectors";

import {
  disconnectKnowledgeConnector, listKnowledgeConnectors, registerKnowledgeConnector, updateKnowledgeConnectorLimits, verifyKnowledgeConnector,
} from "../../../lib/knowledge-connectors-api.js";

// 서버 주소·토큰은 관리자가 입력하며 이 코드에는 주소 리터럴·기본값을 두지 않는다(보안 스캔 BROWSER_INTERNAL_ADDRESS).
const api = {
  list: listKnowledgeConnectors,
  register: registerKnowledgeConnector,
  verify: verifyKnowledgeConnector,
  disconnect: disconnectKnowledgeConnector,
  updateLimits: updateKnowledgeConnectorLimits,
};

export default function KnowledgeConnectorsPage() {
  return <main className="knowledge-connectors-page">
    <nav className="organization-settings-navigation"><a href="/notebooks">Notebook으로</a> · <a href="/settings/model-connections">모델 연결</a> · <a href="/settings/authoring-templates">작성 템플릿</a> · <a href="/settings/tts-engines">TTS 엔진</a></nav>
    <KnowledgeConnectorsPane api={api} />
  </main>;
}
