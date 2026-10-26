"use client";

import { ExportPolicyPane } from "@daon2-user/ui/export-policy";

import { getExportPolicy, setExportPolicy } from "../../../lib/export-policy-api.js";

const api = { get: getExportPolicy, set: setExportPolicy };

export default function ExportPolicyPage() {
  return <main className="knowledge-connectors-page">
    <nav className="organization-settings-navigation"><a href="/notebooks">Notebook으로</a> · <a href="/settings/authoring-templates">작성 템플릿</a></nav>
    <ExportPolicyPane api={api} />
  </main>;
}
