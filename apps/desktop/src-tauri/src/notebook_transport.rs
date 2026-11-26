use crate::native_session::NativeSessionRuntime;
use serde::Deserialize;

const JSON_LIMIT: usize = 1024 * 1024;
const BINARY_LIMIT: usize = 32 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NotebookRequest {
    pub(crate) method: String,
    pub(crate) path: String,
    pub(crate) headers: Vec<(String, String)>,
    pub(crate) body: Option<String>,
}

fn safe_segment(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 && value.bytes().enumerate().all(|(index, byte)| {
        byte.is_ascii_alphanumeric() || (index > 0 && matches!(byte, b'.' | b'_' | b':' | b'-'))
    })
}

impl NotebookRequest {
    fn valid(&self, workspace: &str, notebook: &str) -> bool {
        if !safe_segment(workspace) || !safe_segment(notebook)
            || !matches!(self.method.as_str(), "GET" | "POST" | "PUT" | "PATCH" | "DELETE")
            || (self.method == "GET" && self.body.is_some())
            || self.body.as_ref().is_some_and(|body| body.len() > JSON_LIMIT)
            || self.path.len() > 4096 || self.path.contains(['\\', '#', '\r', '\n'])
            || self.headers.len() > 3
            || self.headers.iter().enumerate().any(|(index, (name, value))| {
                !matches!(name.as_str(), "idempotency-key" | "if-match" | "x-daon-step-up-authorization")
                    || value.is_empty() || value.len() > 1024
                    || value.bytes().any(|byte| !(b' '..=b'~').contains(&byte))
                    || self.headers[..index].iter().any(|(earlier, _)| earlier == name)
            })
        {
            return false;
        }

        let (path, query) = self.path.split_once('?').unwrap_or((&self.path, ""));
        let Some(path) = path.strip_prefix("/api/v1/") else { return false };
        let decoded = path.replace("%3A", ":");
        let parts: Vec<_> = decoded.split('/').collect();
        if !parts.iter().all(|part| safe_segment(part)) {
            return false;
        }
        match parts.as_slice() {
            ["workspaces", ws, "notebooks", nb, "studio" | "model-selection" | "question-tools" |
                "source-groups" | "source-discovery" | "overview" | "copies" | "chat-history", ..] => {
                *ws == workspace && *nb == notebook
            }
            ["workspaces", ws, "questions"] | ["workspaces", ws, "questions", "authorization"] => {
                *ws == workspace && self.method == "POST" && query.is_empty()
                    && self.body.as_ref().and_then(|body| serde_json::from_str::<serde_json::Value>(body).ok())
                        .as_ref().and_then(|value| value.get("notebook_id")).and_then(serde_json::Value::as_str) == Some(notebook)
            }
            ["workspaces", ws, "citations", _, "content"] => {
                let url = reqwest::Url::parse(&format!("https://localhost/?{query}"));
                *ws == workspace && self.method == "GET" && url.is_ok_and(|url| {
                    url.query_pairs().filter(|(key, _)| key == "notebook_id")
                        .map(|(_, value)| value.into_owned()).eq([notebook.to_owned()])
                })
            }
            ["workspaces", ws, "notebooks", nb, "source-preview", _, _, "content"] => {
                *ws == workspace && *nb == notebook && query.is_empty() && self.method == "GET"
            }
            ["session"] => self.method == "GET" && query.is_empty(),
            ["workspaces", ws, "model-defaults"] => *ws == workspace && query.is_empty()
                && matches!(self.method.as_str(), "GET" | "PATCH"),
            ["provider-credentials"] => self.method == "GET" && query.is_empty(),
            ["admin", "provider-connections", "test" | "model-preview"] if self.method == "POST" => query.is_empty(),
            ["provider-credentials", _] | ["admin", "provider-connections", _] => query.is_empty()
                && matches!(self.method.as_str(), "PUT" | "DELETE"),
            ["admin", "provider-connections"] => query.is_empty() && matches!(self.method.as_str(), "GET" | "POST"),
            ["admin", "provider-health-settings"] => query.is_empty() && matches!(self.method.as_str(), "GET" | "PATCH"),
            ["admin", "provider-connections", _, "credential"] => query.is_empty()
                && matches!(self.method.as_str(), "POST" | "DELETE"),
            ["admin", "provider-catalog", _, "refresh"] | ["admin", "model-reasoning", "probe"] =>
                query.is_empty() && self.method == "POST",
            ["admin", "provider-models", _, _, "capabilities"] => query.is_empty() && self.method == "PATCH",
            ["knowledge-connectors"] | ["knowledge-connectors", _, "documents"] => self.method == "GET",
            ["session", "step-up"] => self.method == "POST" && query.is_empty()
                && self.body.as_ref().and_then(|body| serde_json::from_str::<serde_json::Value>(body).ok())
                    .as_ref().and_then(|value| value.get("action_group")).and_then(serde_json::Value::as_str) == Some("studio_export_download"),
            _ => false,
        }
    }

    fn permits_binary(&self) -> bool {
        let path = self.path.split('?').next().unwrap_or("");
        self.method == "GET" && (path.contains("/citations/") || path.contains("/exports/")
            || path.ends_with("/audio") || path.ends_with("/video") || path.ends_with("/content"))
    }

    pub(crate) fn response_limit(&self) -> usize {
        if self.permits_binary() { BINARY_LIMIT } else { JSON_LIMIT }
    }

    pub(crate) fn allows_response(&self, status: u16, media: &str) -> bool {
        status == 204 || media == "application/json" || (status < 300 && self.permits_binary() && matches!(media,
            "application/pdf" | "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            | "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            | "text/plain" | "text/markdown" | "text/csv" | "text/html" | "text/vtt"
            | "image/svg+xml" | "image/png" | "image/jpeg" | "audio/mpeg" | "audio/wav" | "video/mp4"
            | "application/octet-stream"))
    }
}

fn ipc_response(status: u16, headers: Vec<(String, String)>, body: &[u8]) -> Result<tauri::ipc::Response, &'static str> {
    let metadata = serde_json::to_vec(&(status, headers)).map_err(|_| "WORKSPACE_RESPONSE_REJECTED")?;
    let mut bytes = Vec::with_capacity(4 + metadata.len() + body.len());
    bytes.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&metadata);
    bytes.extend_from_slice(body);
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
pub(crate) async fn native_notebook_request(
    workspace_id: String, notebook_id: String, request: NotebookRequest,
    session: tauri::State<'_, NativeSessionRuntime>,
) -> Result<tauri::ipc::Response, &'static str> {
    if !request.valid(&workspace_id, &notebook_id) {
        return Err("INVALID_REQUEST");
    }
    let result = session.execute_workspace_once(crate::native_session::NativeWorkspaceOperation::NotebookRequest {
        workspace_id, request,
    }).await?;
    ipc_response(result.status, result.headers, &result.body)
}

#[tauri::command]
pub(crate) fn native_read_manual(asset: &str) -> Result<tauri::ipc::Response, &'static str> {
    let (mime, bytes): (&str, &[u8]) = match asset {
        "manifest.json" => ("application/json", include_bytes!("../../../web/public/manual/manifest.json")),
        "daon-user-manual.md" => ("text/markdown; charset=utf-8", include_bytes!("../../../web/public/manual/daon-user-manual.md")),
        "daon-user-manual.pdf" => ("application/pdf", include_bytes!("../../../web/public/manual/daon-user-manual.pdf")),
        "daon-user-manual.docx" => ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", include_bytes!("../../../web/public/manual/daon-user-manual.docx")),
        _ => return Err("MANUAL_DOCUMENT_NOT_FOUND"),
    };
    ipc_response(200, vec![("content-type".to_owned(), mime.to_owned())], bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settings_defaults_and_source_previews_remain_scoped() {
        let mut request = NotebookRequest {
            method: "PATCH".into(), path: "/api/v1/workspaces/ws/model-defaults".into(),
            headers: Vec::new(), body: Some("{}".into()),
        };
        assert!(request.valid("ws", "settings"));
        assert!(!request.valid("other", "settings"));
        request.method = "GET".into();
        request.body = None;
        request.path = "/api/v1/workspaces/ws/notebooks/nb/source-preview/source-1/version-1/content".into();
        assert!(request.valid("ws", "nb"));
        assert!(!request.valid("ws", "other"));
        assert!(request.allows_response(200, "application/pdf"));
        request.path = "/api/v1/admin/users".into();
        assert!(!request.valid("ws", "settings"));
    }

    #[test]
    fn notebook_request_checks_the_path_and_workspace_scope() {
        let mut request = NotebookRequest {
            method: "GET".into(), path: "/api/v1/workspaces/ws/notebooks/nb/studio/types".into(),
            headers: Vec::new(), body: None,
        };
        assert!(request.valid("ws", "nb"));
        assert!(!request.valid("other", "nb"));
        assert!(!request.valid("ws", "other"));
        request.headers.push(("authorization".into(), "untrusted".into()));
        assert!(!request.valid("ws", "nb"));
        request.headers.clear();
        request.path = "/api/v1/workspaces/ws/notebooks/nb/studio/%2f".into();
        assert!(!request.valid("ws", "nb"));
        request.path = "/api/v1/session/refresh".into();
        assert!(!request.valid("ws", "nb"));
    }
}
