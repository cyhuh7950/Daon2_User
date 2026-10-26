"use client";

import { TtsEnginesPane } from "@daon2-user/ui/tts-engines";

import { disconnectTtsEngine, listTtsEngines, registerTtsEngine, updateTtsEngine, verifyTtsEngine } from "../../../lib/tts-engines-api.js";

// 서버 주소·키는 관리자가 입력하며 이 코드에는 주소 리터럴·기본값을 두지 않는다(보안 스캔 BROWSER_INTERNAL_ADDRESS).
const api = {
  list: listTtsEngines,
  register: registerTtsEngine,
  verify: verifyTtsEngine,
  update: updateTtsEngine,
  disconnect: disconnectTtsEngine,
};

export default function TtsEnginesPage() {
  return <main className="knowledge-connectors-page">
    <nav className="organization-settings-navigation"><a href="/notebooks">Notebook으로</a> · <a href="/settings/model-connections">모델 연결</a> · <a href="/settings/knowledge-connectors">지식 연결</a> · <a href="/settings/authoring-templates">작성 템플릿</a></nav>
    <TtsEnginesPane api={api} />
  </main>;
}
