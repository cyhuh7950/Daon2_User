"use client";

import { AuthoringTemplatesPane } from "@daon2-user/ui/authoring-templates";

import {
  exportAuthoringTemplate, listAuthoringTemplates, registerAuthoringTemplate, setAuthoringTemplateStatus, updateAuthoringTemplate,
} from "../../../lib/authoring-templates-api.js";

const api = {
  list: listAuthoringTemplates,
  register: registerAuthoringTemplate,
  export: exportAuthoringTemplate,
  update: updateAuthoringTemplate,
  setStatus: setAuthoringTemplateStatus,
};

export default function AuthoringTemplatesPage() {
  return <main className="knowledge-connectors-page">
    <nav className="organization-settings-navigation"><a href="/notebooks">Notebook으로</a> · <a href="/settings/knowledge-connectors">지식 연결</a> · <a href="/settings/export-policy">내려받기 정책</a></nav>
    <AuthoringTemplatesPane api={api} />
  </main>;
}
