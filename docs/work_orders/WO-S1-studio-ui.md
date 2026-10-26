# WO-S1. Studio 화면 (패널·카드·뷰어·Notebook 메뉴)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | S1-01 ~ S1-18, S2-01 ~ S2-14, S3-01 ~ S3-05, S0-11, 신규 S0-13(다중 소스 선택), 신규 S7(디자인) 연계 |
| 선행 | WO-F1 T1-09·T1-10(API·BFF 계약), WO-D(아이콘·토큰) |
| 기준 설계서 | §3, §6, §5.2 / 디자인 참조: NotebookLM 스튜디오 화면(첨부 4장) |
| 조사 근거 | 프론트 구조 조사 2026-10-20 (경로는 `D:\Project\Daon2_User` 기준) |

경로 약어: `UI` = `packages/ui/src`, `WEB` = `apps/web`, `T` = `scripts/tests`.

---

## 0. 현재 구조 요약 (변경 지점의 근거)

| 사실 | 위치 | 영향 |
| --- | --- | --- |
| 실제 제품 UI는 `ProductWorkspaceShell`(2,344줄, 상태 ~80개). 3면 레이아웃 `data-layout="source-conversation-studio"`(`workspace.css` l.235-236: `minmax(250px,18%) minmax(420px,1fr) minmax(360px,27%)`) | `UI/product-workspace-shell.jsx` l.1897 | Studio 패널 폭 변경은 이 CSS 한 줄 |
| **교체 대상 Studio 면**은 `SafePane id="product-pane-studio"` 본문 `desktopStudio ?? <ProductStudioPane/> + 레거시 "빠른 근거 보고서"` | 같은 파일 l.2175-2220 | `desktopStudio ?? …` 분기는 **유지**(Desktop 오프라인 Studio가 대체 주입. `offline-studio-ui.test.mjs`, `desktop-*.test.mjs`가 검증) |
| `ProductWorkspaceShell`은 Desktop(`apps/desktop/src/desktop-shell.jsx`)과 공용 | | 변경 후 `verify:desktop-*` 영향 확인 필수 |
| 소스 선택은 **단일** `viewState.selectedSource`(`selectSource` l.1512)와 승인 지식 `selectedKnowledgeId` | 같은 파일 | NotebookLM식 "체크한 소스" 다중 선택이 없다 → S0-13에서 신설 |
| 채팅 답변은 `viewState.answer` 하나만 렌더(l.2051), 메시지 이력 없음 | 같은 파일 | "메모에 저장" 버튼 위치는 l.2051 `<p>` 뒤 |
| 인용 클릭 처리는 셸 내부(l.2059-2146, 종류별 분기) | 같은 파일 | 패널에서도 같은 근거 보기를 쓰려면 함수로 추출해 prop으로 전달 |
| BFF는 SSE 미지원, 응답 버퍼링, 요청 헤더 허용 목록, 10초 기본 타임아웃 | `WEB/lib/bff-api-proxy.js` | 폴링 사용(WO-F1 D6) |
| 문구는 모두 하드코딩 한국어, 메시지 카탈로그 없음, 테스트가 라벨 텍스트를 단언 | | 새 코드는 **카탈로그 모듈**을 쓰고 기존 라벨은 바꾸지 않는다 |
| 어댑터 경계: 웹 API 호출은 `WEB/components/actual-workspace.jsx`의 `createWebProductWorkspaceAdapter`가 만들고, `UI/notebook-context-adapter.js`가 노트북 범위를 강제 | | 새 어댑터 메서드는 **두 곳 모두**에 등록해야 `notebookId`가 주입된다 |
| 린트(`scripts/lint-workspace.mjs`)는 `fetch(`·절대 URL·`localhost`·`NEXT_PUBLIC_API_BASE_URL` 금지, 기본 대상 목록이 오래되어 새 파일은 인자로 전달해야 검사됨 | | 새 API 클라이언트는 `fetchImpl = fetch` 기본 인자 형식 |
| `verify-product-ui-boundary`는 `prototype_fixture`, `deferred_actual`, `@daon2-user/evidence-hub` 등 금지 토큰을 UI·번들에서 검사 | | 해당 문자열을 새 코드·주석·문구에 쓰지 않는다 |

---

## 1. 작업 목록

### T-S0-13. 다중 소스 선택 (선행 작업)

설계서 §6.1·§6.2는 Studio가 "현재 선택된 Source(여러 개)"를 쓴다고 전제한다. 현재 구조는 단일 선택이라 먼저 바꾼다.

- **새 상태**(`product-workspace-shell.jsx`): `checkedSourceVersionIds: string[]`(초기값: ready인 모든 Source, 사용자가 해제 가능). `selectedSource`(단일, 원문 보기·질문 범위용)는 유지하고 **의미를 분리**한다 — `selectedSource`는 "보고 있는 Source", `checked…`는 "생성·질문에 쓸 Source".
- **UI**: Source 목록 각 행 앞에 체크박스(`role="checkbox"`, 라벨 `"{파일명} 사용"`), 목록 머리에 "모두 선택/해제" 체크박스, 하단/머리에 "소스 N개" 표시(채팅 입력창 우측에도 `소스 N개` 표시, 설계서 §3.3).
- **질문 범위**: `buildQuestionKnowledgeContext`(l.601)가 `checkedSourceVersionIds`로 `resources:[{resourceKind:"source", resourceId, versionId}]`를 최대 8개까지 만든다(`knowledgeContextBody`는 이미 8개 허용). 9개 이상이면 안내("질문에는 최대 8개 소스를 쓸 수 있습니다") 후 앞 8개 사용.
- **답변 검증 완화**: `projectSafeQuestionAnswer`(l.514)가 "인용 소스가 현재 선택 Source와 일치"를 요구한다. 다중 선택에서는 `checked` 집합에 포함되면 통과하도록 수정. 같이 수정: `UI/notebook-context-adapter.js`의 `validCitation`/`projectNotebookSelectedContext`, `UI/product-workspace-model.js`의 `canCreateGroundedReport`.
- **Studio 패널 키**: l.2177의 `key={answer?.run_id:selectedSource?.sourceVersionId}`는 "선택 Source/질문이 바뀔 때 패널 상태를 초기화"하는 의도이므로 **v2 패널에서는 쓰지 않는다**(생성 중인 작업이 사라지면 안 됨). v2는 `key`를 `notebookId`로만 둔다.
- **테스트**: 기존 `T/product-workspace.test.mjs`(2,112줄)의 소스 선택 시나리오가 단일 선택 가정이면 새 동작에 맞게 갱신. 신규 `T/source-multi-select.test.mjs`(체크/해제/모두/8개 제한/질문 컨텍스트 본문).
- **완료 기준**: 소스 3개 중 2개 체크 → 질문 시 요청 본문 `resources`가 2개, 응답 인용이 통과, 체크 0개일 때 질문은 일반 상담(기존 동작).

### T-S1-01. 데이터 계층 `WEB/lib/studio-v2-api.js` (신규)

- 규칙은 `product-workspace-api.js`를 따른다: `fetchImpl = fetch` 기본 인자, `credentials:"same-origin", cache:"no-store", signal`, 쓰기에 `Idempotency-Key`(`safeIdempotencyKey`, 기본 `secureUuid()` — `@daon2-user/ui/secure-uuid`), 성공 시 `payload.data` 검증 후 반환, 실패는 `new Error(payload.error.code)`.
- 함수: `listStudioTypes`, `listStudioOutputs({cursor,limit})`, `getStudioOutput(id,{revision})`, `createStudioOutput({typeId,formatId,settings,sourceVersionIds})`, `renameStudioOutput(id,title,{etag})`, `deleteStudioOutput(id)`, `cancelStudioOutput(id)`, `regenerateStudioOutput(id,{settings})`, `createStudioRevision(id,{content,changeReason})`, `getStudioProvenance(id,{revision})`, `downloadStudioExport(id,format,{revision})`(기존 `downloadStudioExport`의 `{bytes,contentType,disposition}` 방식, 32 MiB 상한), `getStudioSharing(id)`, `recordLearningAttempt/list`, `createStudioMemo({title,markdown,fromRunResultId})`, `getCustomization/saveCustomization`.
- 경로는 모두 `/bff/api/workspaces/{ws}/notebooks/{nb}/studio/...`(WO-F1 T1-10). 노트북 범위는 어댑터가 주입(`notebookId`).
- 응답 검증은 `exact(obj, keys)` 헬퍼(키 집합 정확 일치)로 한다. 목록 항목 키: `output_id,type_id,format_id,title,status,error_code,source_count,current_revision,created_at,updated_at,stale`.
- **테스트** `T/studio-v2-api.test.mjs`: `fetchImpl` 가짜로 URL·메서드·헤더·본문·검증 실패 케이스.

### T-S1-02. 어댑터 연결

- `WEB/components/actual-workspace.jsx` `createWebProductWorkspaceAdapter`(l.19-84)에 `studioV2: Object.freeze({...})` 객체 추가: 위 함수를 `notebookOptions`로 감싼다.
- `UI/notebook-context-adapter.js` (`createNotebookContextWorkspaceAdapter`, l.160~215): `studioV2` 서브 객체를 같은 방식으로 감싸 `notebookId`를 강제한다(`typeof baseAdapter.studioV2 === "object"` 검사, 결과는 `Object.freeze`).
- **플래그**: 서버가 `studio_v2_enabled`를 `GET /bff/shell/runtime`(기존 런타임 상태 라우트) 또는 `/studio/types` 응답의 `available`로 알려주면 어댑터가 `studioV2.enabled`를 노출. v2가 꺼져 있으면 셸은 레거시 Studio를 그대로 렌더.
- 테스트: `T/notebook-context-adapter.test.mjs`에 `studioV2` 범위 주입 사례 추가.

### T-S1-03. 패널 모델 `UI/studio-panel-model.js` (신규, 순수 함수)

```js
createStudioPanelState({ types: [], outputs: [], status: "loading" })
// state: { status, types[], outputs[], nextCursor, pendingCreate: Set<typeId>, selectedOutputId, dialog: null|{kind,outputId}, busy: Set<outputId>, error: null|code, pollingActive }
reduce(state, action)   // LOADED, OUTPUT_CREATED, OUTPUT_UPDATED, OUTPUT_REMOVED, SELECT, DIALOG_OPEN/CLOSE, ERROR, POLL_RESULT
tileState(type, {sourceCount, readySourceCount, processingCount}) -> {enabled, reason}
cardSubtitle(output, types, {now}) -> string   // 설계서 §6.4 부제 규칙(형식·소스 N개·경과시간)
formatRelativeTime(iso, now) -> "93일 전" | "방금" | "3분 전" ...
hasActiveJob(outputs) -> boolean
```
- 부제 규칙: report → `{형식명} · 소스 {N}개 · {상대시간}`, 오디오/영상 → `{길이} · {형식} · 소스 …`, 메모 → `{상대시간}`만.
- 정렬: 서버 정렬(최신순) 그대로, 새로 만든 카드는 맨 위에 삽입.
- 폴링 규칙: `hasActiveJob`이면 1.5초 간격으로 `listStudioOutputs` 재조회, 없으면 중지. 탭 비활성(`document.hidden`)이면 간격 10초.
- **테스트** `T/studio-panel-model.test.mjs`(순수 함수라 DOM 불필요): 타일 상태(§6.1 표), 부제, 상대시간, 폴링 판정, 리듀서 전이.

### T-S1-04. 메시지 카탈로그 `UI/studio-messages.ko.js` (신규)

- `export const STUDIO_MESSAGES = Object.freeze({ "studio.title": "스튜디오", "studio.tile.report": "보고서", … })`와 `msg(key, params)` 함수(없는 키는 개발 중 예외). 오류 코드 → 문구 맵(`STUDIO_ERRORS`)도 여기(기존 `safeStudioErrorMessage` 방식 대체, 코드 형식 `^[A-Z][A-Z0-9_]{2,63}$` 유지, 원문 오류 문자열 렌더 금지).
- 영어 파일은 만들지 않되 키 구조는 이후 추가 가능하도록 한다(계획 S6-02).

### T-S1-05. Studio 패널 골격 + 타일 격자 `UI/studio-panel.jsx`, `studio-tile-grid.jsx` (신규)

- **컴포넌트**: `StudioPanel({ adapter, notebookId, checkedSources, onOpenCitation, onAskAboutNode, onToggleCollapse })`. 헤더(제목 "스튜디오", 패널 접기 아이콘 버튼), 타일 격자, 카드 목록(스크롤), 하단 고정 "메모 추가" 필 버튼.
- **레이아웃**(디자인 참조: 첨부 화면): 타일은 **2열 격자**, 각 타일은 필 모양(높이 56px, 반경 18px), 좌측 유형 아이콘(24px, 유형별 강조색) + 라벨(14px), 연필(설정) 아이콘은 호버/포커스 시 우측에 표시. 툴팁(`role="tooltip"`)으로 "소스를 기반으로 보고서 생성" 같은 설명. 보고서 타일의 `New` 배지는 `types[].new_until`(서버가 날짜 제공)까지 표시.
- 타일 상태: 비활성은 `aria-disabled="true"` + 사유 툴팁(자료 없음/선택 0개/처리 중/유형 미제공), 클릭 불가.
- **동작**: 타일 클릭 → `adapter.studioV2.createOutput({typeId, sourceVersionIds: checked})` → 즉시 목록 맨 위에 "생성 중" 카드 삽입(낙관적, 서버 응답의 `output_id`로 교체) → 폴링 시작. 중복 클릭 방지(`pendingCreate`). 오류 시 상단 `role="alert"` 배너.
- 접근성: 타일 그리드는 `role="group" aria-label="산출물 만들기"`, 각 타일은 `<button>`; 키보드 화살표 이동(roving tabindex).
- **CSS** `UI/studio-panel.css`(신규): 토큰만 사용(WO-D의 `--studio-*` 변수). 패널 전체 배경은 `--studio-surface`, 둥근 모서리 20px, 스크롤바 얇게. `prefers-reduced-motion` 시 애니메이션 제거.
- **셸 연결**: `product-workspace-shell.jsx` l.2175-2220 본문을 다음으로 교체.
  ```jsx
  {desktopStudio ? desktopStudio
    : adapter.studioV2?.enabled
      ? <StudioPanel key={notebookId} adapter={adapter} notebookId={notebookId}
          checkedSources={checkedSources} onOpenCitation={openStudioEvidence}
          onAskAboutNode={askAboutNode} />
      : <>{/* 기존 ProductStudioPane + 레거시 보고서 (제거 전까지 유지) */}</>}
  ```
  `PANE_ICONS`(l.230), 제목 문구 "업무 Studio" → "스튜디오"(v2일 때만; 기존 테스트 라벨 유지를 위해 조건부).
- **테스트** `T/studio-panel-react.test.mjs`: 표준 마운트 패턴(vite 번들 + `installMinimalDom` + `createRoot`, 가짜 `adapter.studioV2`)으로 (1) 타일 9개 렌더, (2) 소스 0개일 때 비활성, (3) 클릭 시 `createOutput` 호출 인자, (4) 생성 중 카드 표시, (5) 오류 배너.

### T-S1-06. 카드·메뉴 `UI/studio-card.jsx`, `studio-card-menu.jsx`

- 카드 행: 유형 아이콘 · 제목(1줄 말줄임, 14px 굵게) · 부제(12px, 보조색) · 우측 `재생`(오디오/영상 완료 시)·`⋮`. 생성 중은 스피너 아이콘+"생성 중…"+진행률(`progress_pct`)·취소 버튼, 실패는 경고 아이콘+사유 문구+"다시 시도", stale은 배지 "소스가 변경됨". 카드 전체가 버튼(열기), `⋮`는 별도 버튼(이벤트 전파 중단).
- **메뉴**(`role="menu"`, 트리거 `aria-haspopup="menu" aria-expanded`): 기본 5항목(공유·이름 바꾸기·다운로드·프롬프트 및 소스 보기·삭제) + 구분선 + 추가(다시 생성·설정 변경 후 다시 생성·메모로 저장). 생성 중/실패 카드: 다운로드·공유 비활성. Esc로 닫기, 바깥 클릭 닫기, 포커스 복귀. 패턴은 셸 설정 메뉴(l.~1884)·`notebook-home.jsx` 카드 메뉴(l.101-104).
- **이름 바꾸기**: 카드 제목이 입력 필드로 바뀜(Enter 저장, Esc 취소), `If-Match`로 `renameOutput(id,title,{etag})`.
- **삭제**: 공용 확인 대화상자(`role="dialog" aria-modal`, 셸의 `trapDialogFocus` 패턴을 `UI/dialog-utils.js`로 추출해 공유). 문구는 카탈로그.
- **다운로드**: 서브메뉴로 형식 목록(`types[].export_formats`). 클릭 → `downloadStudioExport` → Blob `<a download>`(기존 방식, URL은 60초 후 revoke). 생성 중 비활성.
- **테스트** `T/studio-card-menu.test.mjs`: 메뉴 항목 순서·비활성 규칙·키보드·삭제 확인·이름 변경 흐름.

### T-S1-07. 대화상자: 설정·프로비넌스·공유

- **설정**(`studio-settings-dialog.jsx`): 연필 아이콘에서 열림. 필드는 유형별 `settings_schema`로 렌더(언어·형식(프리셋)·길이·포커스 지시문·난이도·개수·독자·스타일). **모두 선택 입력**, 취소/생성 버튼. 포커스 지시문 상한 500자, 카운터 표시.
- **프롬프트 및 소스 보기**(`studio-provenance-dialog.jsx`, 설계서 §6.5.2): 섹션 5개 — 유형·형식 / 지시문(포커스·맞춤설정 적용 여부) / 설정 / 사용한 소스(이름·버전·"변경됨" 표시, 클릭 시 소스 보기) / 근거 목록(클릭 시 `onOpenCitation`). 시스템 프롬프트 원문은 서버가 주지 않으므로 표시 없음. 하단 "이 설정으로 다시 생성" 버튼.
- **공유**(`studio-share-dialog.jsx`): 현재 접근 가능한 사용자/그룹 목록(읽기 전용), "링크 복사"(노트북 권한자 전용 안내 문구), 공개 링크 없음 문구. 노트북 공유 대화상자로 이동하는 링크(S3-01).
- 테스트: 각 대화상자 열기/닫기·필드 직렬화·포커스 트랩.

### T-S2-xx. 상세 뷰어 (`UI/studio-viewers/*.jsx`)

공통 `StudioViewer({ output, revision, evidence, onOpenCitation, onEdit, onExport })`가 `type_id`로 분기한다. 모든 뷰어는 **읽기 전용 기본 + 편집 모드**(보고서·메모·슬라이드·카드·퀴즈만)이며, 근거 라벨 `[S#]`은 클릭 가능한 각주 번호로 렌더(`aria-label="근거 {n}: {소스명} {위치}"`), 클릭 → `onOpenCitation({sourceVersionId, evidenceSpanId, locator})`.

| ID | 뷰어 | 구현 요점 | 완료 기준(시나리오) |
| --- | --- | --- | --- |
| S2-01 | `report-viewer` | 섹션 헤딩·문단·불릿·표 렌더, 인용 번호, `warnings` 표시(`UNVERIFIED_CLAIM`은 문장 옆 "근거 미확인" 배지) | ST-T05 |
| S2-02 | 형식 선택 | 설정 대화상자의 `format_id` 선택지(요약/브리핑/블로그/스터디 가이드/사용자 정의) | ST-T25 |
| S2-03 | `table-viewer` | 정렬(열 헤더 클릭)·열 숨김·셀 클릭 근거, 가상 스크롤 불필요(≤60행) | |
| S2-04 | `mindmap-viewer` | 클라이언트 트리 레이아웃(WO-F2 `layout_tree`와 같은 알고리즘을 JS로 구현), SVG 렌더, 마우스휠 확대/드래그 이동, 노드 접기/펴기, 노드 선택 시 우측 상세(요약·근거·"이 개념으로 질문") | |
| S2-05 | 노드 질문 | `onAskAboutNode({label, sourceVersionIds})` → 셸이 `setQuestion(`"${label}"에 대해 설명해 줘`)`, 질문 범위를 노드 근거 소스로 **임시 지정**(체크 상태는 바꾸지 않음), 입력창 포커스, **자동 전송 없음** | ST-T23 |
| S2-06 | `flashcards-viewer` | 카드 뒤집기(클릭/스페이스), 이전·다음(←/→), 섞기, 알아요/모르겠어요 버튼 | |
| S2-07 | `quiz-viewer` | 문항별 보기 선택→제출→정오·해설·근거, 마지막에 점수 요약 | ST-T11 |
| S2-08 | 학습 히스토리 | 시도 저장(`recordLearningAttempt`), "모르는 카드만/틀린 문항만" 모드, 본인에게만 | ST-T24 |
| S2-09 | `slides-viewer` | 좌측 썸네일 목록 + 큰 슬라이드(16:9 CSS 박스) + 발표자 노트 토글, 레이아웃별 렌더 | ST-T22 |
| S2-10 | `memo-editor` | 마크다운 텍스트 영역 + 미리보기, 자동 저장(디바운스 1.5초 → `createRevision`), 인용 보존 | |
| S2-11 | 편집 UI 공통 | 편집 모드 전환, 저장 시 `createRevision`(user_edit), "AI로 다시 생성"과 구분, 충돌(409)은 안내 | |
| S2-12 | `infographic-viewer` | 이미지 확대 | Phase 2 |
| S2-13 | `audio-player` | `<audio>` + 속도·구간 + 스크립트 동기 하이라이트 | Phase 3 |
| S2-14 | `video-player` | `<video>` + 챕터 목록 | Phase 4 |

- 뷰어 컨테이너는 패널 안에서 목록과 전환되는 화면(상세 진입 시 뒤로 가기 버튼)으로 렌더하고, 넓은 화면에서는 패널 폭을 늘려 보여주는 옵션(`--studio-wide`)을 CSS 변수로 둔다.
- 근거 보기(`openStudioEvidence`)는 셸의 인용 처리 분기(l.2059-2146)를 `openEvidence(locator, sourceVersionId, evidenceSpanId)` 함수로 추출해 질문 인용과 Studio 인용이 같은 뷰어(PDF 쪽/DOCX 블록/PPTX/XLSX/오디오/이미지/법령)를 쓰게 한다. v2 근거는 `citation_id`가 없으므로 **새 근거 콘텐츠 엔드포인트가 필요**(WO-F1 T1-16, 아래 §3).
- 테스트: 뷰어별 `T/studio-viewer-<type>.test.mjs`(렌더·근거 클릭·편집 저장).

### T-S3-01~05. Notebook 상단 바·⋮ 메뉴

- **헤더**(셸 l.1878~): 우측에 `+ 노트북 만들기`(홈으로 이동 후 생성 대화상자 열기 또는 `adapter.createNotebook`), `공유`, `⋮`(Notebook 메뉴), 기존 설정 메뉴. Notebook 메뉴 항목: 채팅 설정, 노트북 맞춤설정, 노트북 복사, 채팅 기록 삭제(보조 문구 "채팅 기록은 나만 볼 수 있습니다"). 애널리틱스 항목은 렌더하지 않는다(1차 제외).
- **맞춤설정 대화상자**: 텍스트 영역(최대 4,000자), 저장 시 `saveCustomization(etag)`. 안내 문구 "채팅과 스튜디오 생성에 모두 적용되며, 이미 만든 산출물에는 적용되지 않습니다."
- **복사 대화상자**: 체크박스 3개(소스·메모·산출물), 새 노트북 이름 입력 → `adapter.copyNotebook`(WO-F3, 후속).
- **채팅 기록 삭제**: 확인 대화상자 → `adapter.deleteChatHistory`(WO-F3).
- 해당 백엔드가 준비되지 않은 항목은 메뉴에서 **비활성(툴팁 "준비 중")** 으로 표시하고 계획서 상태는 `[ ]` 유지.

### T-S1-08. 채팅 "메모에 저장" (S1-15)

- 셸 l.2051 `<p>{answer.answer}</p>` 아래에 아이콘 버튼 줄: `메모에 저장`(핀 아이콘), 복사(`navigator.clipboard`). 클릭 → `adapter.studioV2.createMemo({fromRunResultId: answer.run_result_id})` → Studio 목록 새로고침 + 토스트("메모에 저장했습니다. 메모는 노트북을 보는 모든 사람에게 보입니다" — **최초 1회만**, `localStorage` 키 `daon2.studio.memoNoticeSeen`, try/catch).
- 답변이 `insufficient`이면 버튼 비활성.
- 테스트 `T/chat-save-memo.test.mjs`.

### T-S0-11. 기존 Studio UI 제거

- v2가 안정화(Phase 1 종료)된 뒤 `UI/product-studio-pane.jsx`, `product-studio-model.js`, `studio-workflow-*`, 셸의 레거시 `<details>`, 관련 테스트(`product-studio.test.mjs`, `product-studio-click.test.mjs`(1,311줄), `product-studio-stepup-click.test.mjs`, `studio-report-api.test.mjs`, `workspace.test.mjs`의 프로토타입 부분)를 삭제한다. 삭제 전 `apps/desktop`이 이 모듈들을 import하는지 `grep`으로 확인하고(`desktop-shell.jsx`는 `desktopOfflineStudio`만 쓰는지) `verify:desktop-*` 통과를 확인한다.
- `UI/index.js`의 `ProductStudioPane`, `createProductStudioState`, `PRODUCT_STUDIO_OUTPUT_TYPES` 재export 제거 시 `scripts/tests/*`·`apps/desktop` 참조 점검.
- **완료 기준**: 레거시 파일 제거 후 `npm run verify:workspace`, `verify:desktop-lint/unit`, `verify:product-ui-boundary`, `npm run build --workspace @daon2-user/web` 통과.

---

## 2. 화면 상태·문구 요약 (카탈로그 키 목록)

`studio.title`, `studio.collapse`, `studio.tile.{audio_overview,slides,video_overview,mind_map,report,flashcards,quiz,infographic,data_table}`, `studio.tile.hint.{…}`(툴팁), `studio.tile.disabled.{no_sources,none_selected,processing,unavailable}`, `studio.card.{generating,failed,retry,stale,cancelled,cancel}`, `studio.menu.{share,rename,download,provenance,delete,regenerate,regenerate_with_settings,save_as_memo}`, `studio.confirm.delete.{title,body,confirm,cancel}`, `studio.memo.add`, `studio.memo.notice`, `studio.dialog.settings.*`, `studio.dialog.provenance.*`, `studio.dialog.share.*`, `studio.error.*`(오류 코드별), `notebook.menu.*`.

## 3. 백엔드 추가 요구 (WO-F1에 반영: T1-16)

- **v2 근거 콘텐츠 엔드포인트**: `GET /api/v1/workspaces/{ws}/notebooks/{nb}/studio/outputs/{id}/evidence/{ref_id}/content?revision` — `studio_v2_evidence`의 `evidence_span_id`로 기존 `read_citation_content`(`question_answering_postgres.py:894`)와 같은 형식(PDF 쪽/원문 JSON/이미지 등)과 헤더(`x-citation-locator-kind`, `x-citation-page`, `x-citation-region`)를 반환. 권한은 노트북 VIEW + Source 접근 재확인. BFF 라우트와 `RESPONSE_HEADERS` 재사용.
- 내용이 준비되기 전에는 셸의 근거 보기를 질문 인용과 공유하는 리팩터링(T-S2 공통)을 시작하지 않는다.

## 4. 의존 관계·순서

```text
WO-D(아이콘·토큰) ─┐
T-S0-13(다중 소스) ├→ T-S1-05(골격·타일) → T-S1-06(카드·메뉴) → T-S1-07(대화상자) → T-S2(뷰어: report→table→mindmap→cards/quiz→slides→memo)
T-S1-01·02(API·어댑터) ┘                       ↘ T-S1-08(메모 저장) ↘ T-S3(Notebook 메뉴)
WO-F1 T1-09·10 계약 확정 후 시작(그 전에는 가짜 어댑터로 개발)
```
- 첫 수직 슬라이스: **보고서 타일 → 생성 중 카드 → 완료 카드 → 보고서 뷰어 → 다운로드(docx)** 를 가짜 어댑터로 먼저 끝내고(WO-F1·F2와 독립 개발), 실제 API가 준비되면 어댑터만 교체한다.

## 5. 검증

```bash
node --test scripts/tests/studio-panel-model.test.mjs scripts/tests/studio-v2-api.test.mjs \
  scripts/tests/studio-panel-react.test.mjs scripts/tests/studio-card-menu.test.mjs \
  scripts/tests/source-multi-select.test.mjs scripts/tests/chat-save-memo.test.mjs
node scripts/lint-workspace.mjs packages/ui/src/studio-*.jsx packages/ui/src/studio-*.js apps/web/lib/studio-v2-api.js
npm run verify:workspace && npm run verify:product-ui-boundary && npm run verify:desktop-unit
npm run build --workspace @daon2-user/web
```
- WSL 화면 확인: `docs/04_test_reports/studio_ui/`에 시나리오별 스크린샷(데스크톱 폭 1440, 좁은 폭 390)과 체크리스트(ST-T01~T27 중 UI 항목)를 남긴다.

## 6. 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 셸이 2,344줄 모놀리스 | 변경 충돌·회귀 | 셸 변경은 마운트 지점·소스 체크·메모 버튼·헤더 메뉴 4곳으로 한정, 나머지는 새 컴포넌트로 격리 |
| Desktop 공용 셸 | Desktop 회귀 | `desktopStudio ?? …` 분기 보존, 각 PR에서 `verify:desktop-unit` 실행 |
| 기존 테스트의 한글 라벨 단언 | 라벨 변경 시 대량 실패 | 기존 라벨은 건드리지 않고 v2에서 새 라벨 사용, 레거시 제거 시 함께 삭제 |
| `data-layout` 단언(`web-final-ui.test.mjs` l.48) | 레이아웃 변경 시 실패 | 속성 값 유지, 패널 폭은 CSS 값만 변경 |
| 인용 처리 추출 리팩터링 | 질문 인용 회귀 | 추출 전 `product-workspace.test.mjs`의 인용 시나리오를 먼저 실행해 기준선 확보, 추출 후 동일 통과 확인 |
