# 프로젝트·업무 패키지 목록 기능 요청 (Daon2-User → Daon2, Daon2-RAG)

| 항목 | 내용 |
| --- | --- |
| 작성 | 2026-11-09, Daon2-User |
| 요청 근거 | `daon2-mcp-provider-request.md`의 R-RAG-02(`list_knowledge_scopes`), R-D2-09 |
| 상태 | 전달 전 |

## 왜 필요한가

Daon2-User 노트북에서 `Daon 승인 지식`을 누르면 팝업으로 전체 목록을 보여주고, 사용자가 **업무 패키지를 여러 개 선택**하면 그 패키지의 지식을 소스로 씁니다. 업무 패키지에는 Daon2 승인 지식과 Daon2-RAG 문서 지식이 함께 들어갑니다.

지금 두 서버의 MCP 도구에는 "어떤 프로젝트와 업무 패키지가 있는가"를 알려주는 기능이 없어서 팝업 목록을 만들 수 없습니다.

## 요청 기능

두 서버(Daon2, Daon2-RAG)의 MCP에 각각 읽기 전용 도구 `list_knowledge_scopes`를 추가해 주세요.

**입력**

| 이름 | 필수 | 내용 |
| --- | --- | --- |
| `limit` | 예 | 한 번에 받을 개수 |
| `cursor` | 아니요 | 다음 페이지 위치 |

**출력**

```json
{
  "scopes": [
    {
      "project_id": "...",
      "project_name": "...",
      "work_package_id": "...",
      "work_package_name": "...",
      "updated_at": "..."
    }
  ],
  "next_cursor": null
}
```

Daon2는 호출에 `tenant_id`가 필요하므로 각 항목에 `tenant_id`도 포함해 주세요.

**수용 기준**

1. 호출자에게 허용된 프로젝트·업무 패키지만 반환합니다.
2. 허용 밖 항목은 존재도 드러나지 않아야 합니다.
3. 빈 목록과 오류를 구분합니다.
4. 이 목록의 값으로 기존 도구를 그대로 호출할 수 있어야 합니다. (Daon2: `approved_knowledge_search`의 `scope`, Daon2-RAG: `search_document_evidence`의 `project_id`, `work_package_id`)

## 회신 요청

| # | 질문 | 대상 |
| --- | --- | --- |
| 1 | 같은 업무 패키지의 `project_id`, `work_package_id`가 Daon2와 Daon2-RAG에서 같은 값인가요? 다르면 대응 관계를 어떻게 얻나요? | 양쪽 |
| 2 | ysna에서 MCP가 켜져 있나요? 접속 주소와 프로토콜 판본을 알려 주세요. | 양쪽 |
| 3 | Daon2-User용 서비스 자격(주체, audience, scope)은 어떻게 발급받나요? 자격값은 문서나 채팅에 적지 말고 별도 경로로 전달해 주세요. | 양쪽 |
| 4 | Daon2-User는 사용자·조직별 제한을 두지 않습니다. 서비스 자격 하나에 전체 프로젝트·업무 패키지를 허용할 수 있나요? | 양쪽 |
