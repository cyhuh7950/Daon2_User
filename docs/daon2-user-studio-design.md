# Daon2-User Studio 설계서

## 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서 구분 | Daon2-User Studio 영역 신규 설계 (초안) |
| 문서 버전 | 0.2 초안 (2026-10-20) — 인터뷰 결정(부록 D)과 가상 MCP 전략 반영 |
| 상태 | 검토 대기. 이 문서는 구현 승인을 뜻하지 않음. 확정된 결정은 부록 D, 남은 미정은 §16 |
| 대상 제품 | Daon2-User (Notebook형 지식 업무지원 프로그램) |
| 참조 제품 | Google NotebookLM Studio 패널·메뉴 (첨부 화면 5종 기준) |
| 참조 자료 | `Backup/docs/daon-user-program-design.md`(§13 업무 Studio), `Backup/docs/Daon 사용자용 프로그램 기본 설계서.docx`, `Backup/apps`(web·desktop·mobile), `services/api` Studio 모듈 |
| 개발 저장소 | https://github.com/sinsan-develop/Daon2_User (신산님 지정). 이 문서는 아직 커밋·푸시하지 않음 |
| 적용 범위 | 3면 워크스페이스의 오른쪽 **Studio** 패널, 산출물 생성·보관·재사용, 그리고 Daon2·Daon2-RAG 지식(MCP) 기반 **작성형 문서 생성**(§7A) |
| 비적용 범위 | Source 등록·색인, 채팅·인용, 계정·조직·권한, Provider 연결은 daon-user 구조를 그대로 재사용하며 이 문서에서 재설계하지 않음 |

> 확인 한계: NotebookLM의 동작은 첨부 화면 5장과 공개된 일반 사용 경험을 근거로 한다. 화면에 보이지 않는 세부 동작(예: 생성 소요 시간, 내부 모델)은 가정이며 §16 열린 질문에 모았다.

---

## 1. 배경과 목표

### 1.1 배경

daon-user는 NotebookLM과 같은 경험을 목표로 했으나, Studio는 다음과 같이 NotebookLM과 사용 방식이 달라졌다.

| 구분 | NotebookLM Studio | daon-user 현재 Studio |
| --- | --- | --- |
| 시작 | 타일 한 번 클릭 → 바로 생성 시작 | 타일 선택 후 **8개 필수 설정**(목적·독자·언어·자료·분량·구성·형식·검토 조건)을 확정해야 생성 |
| 결과 | 목록에 즉시 카드로 누적, 생성 중 상태 표시 | OutputVersion·검토 요청·승인·전달·지식 등록 흐름에 묶임 |
| 산출물 | 오디오·동영상·슬라이드·마인드맵·보고서·플래시카드·퀴즈·인포그래픽·데이터 표 9종 | 보고서·점검표·비교표·지식 구조도·초안(+후속 6종)으로 업무 문서 중심. 오디오·동영상은 `json` 자리 표시 |
| 메모 | 채팅 답변 "메모에 저장", Studio 하단 "메모 추가" | 해당 개념 없음 |
| 부가 | 소스 개수·경과 시간·재생 버튼·더보기 메뉴가 한 줄 카드에 표시 | 버전·승인 상태 중심 표시 |

### 1.2 목표

1. **한 번의 클릭으로 시작**하는 NotebookLM형 Studio를 만든다. 설정은 선택 사항이며, 기본값만으로 생성이 시작되어야 한다.
2. NotebookLM Studio의 **9종 산출물과 메모**를 모두 설계 범위에 포함한다. 구현은 단계별로 나눈다(§13).
3. 모든 산출물은 **선택된 Source에 근거**하며, 근거 위치로 이동할 수 있다.
4. daon-user의 Source·채팅·인용·권한·큐·Provider 구조를 최대한 **재사용**한다.
5. 검토·승인·전달·지식 재등록 같은 거버넌스 흐름은 **핵심 경로에서 분리**하여 선택 기능으로 둔다.
6. Daon2·Daon2-RAG가 만든 지식(RAG·GraphRAG·온톨로지)을 **MCP 표준**으로 연결하고, 이를 근거로 사용자 요구에 맞는 업무 문서(약관·제안서·계약서 등)를 **질문·확인을 거쳐 작성**하는 기능을 Studio에 포함한다(§7A).

### 1.3 비목표

- NotebookLM의 시각 디자인 복제. 화면 구조와 상호작용만 참조한다.
- Google 서비스에 의존하는 기능(예: Google Drive 직접 연동)은 이 문서 범위가 아니다.
- 오디오·동영상 생성 품질의 NotebookLM 동급 보장.

---

## 2. 설계 원칙

| # | 원칙 | 설명 |
| --- | --- | --- |
| P1 | 클릭 즉시 생성 | 타일 클릭 즉시 작업이 시작된다. 설정은 타일 옆 편집(연필) 아이콘으로 여는 **선택형** 대화상자다. |
| P2 | 기본값 우선 | 자료·언어·길이·형식은 현재 Notebook 상태에서 자동 채운다. 필수 입력은 없다. |
| P3 | 근거 우선 | 산출물 내용은 선택 Source에서만 만든다. 근거를 찾지 못한 내용은 생성하지 않거나 "미확인"으로 표시한다. |
| P4 | 비동기·비차단 | 생성은 백그라운드 작업이다. 사용자는 채팅·다른 산출물 사용을 계속할 수 있다. |
| P5 | 목록 누적 | 산출물은 생성 순서대로 Studio 목록에 쌓이고 새로고침 후에도 남는다. |
| P6 | 재현 가능성 | 각 산출물은 생성 당시 Source 목록과 설정 스냅샷을 저장한다. |
| P7 | 거버넌스 분리 | 승인·전달·지식 재등록은 선택 동작이며 생성·열람의 선행조건이 아니다. |
| P8 | 안전 실패 | 실패는 카드에 사유와 재시도를 표시한다. 부분 결과를 성공처럼 보이지 않는다. |
| P9 | 플랫폼 일관성 | Web·Desktop·Mobile이 동일 API와 동일 산출물 모델을 사용한다. |

---

## 3. 참조 분석: NotebookLM Studio 화면

### 3.1 패널 구성 (첨부 화면 기준)

```text
┌ 스튜디오 ───────────────────── [패널 접기] ┐
│ [AI 오디오 오버뷰] [슬라이드 자료] [동영상 개요] │
│ [마인드맵]         [보고서 New!]  [플래시카드]   │
│ [퀴즈]             [인포그래픽]   [데이터 표]    │
│ ─────────────────────────────────────────── │
│ 산출물 카드 목록 (최신순)                       │
│   ▸ 아이콘 · 제목 · 부제(소스 N개 · 경과시간)   │
│   ▸ [재생(오디오·동영상만)] [⋮ 더보기]          │
│ ─────────────────────────────────────────── │
│                         [메모 추가]            │
└────────────────────────────────────────────┘
```

### 3.2 카드가 보여주는 정보

| 요소 | 관찰 내용 |
| --- | --- |
| 아이콘 | 산출물 유형별 고유 아이콘·색 (오디오=파랑, 슬라이드=분홍, 동영상=초록, 마인드맵=보라, 보고서=분홍, 플래시카드=노랑, 퀴즈=하늘, 인포그래픽=노랑 막대, 데이터 표=파랑 목록, 메모=흰색) |
| 제목 | 자동 생성된 제목 |
| 부제 | `소스 N개 · N일 전`. 오디오·동영상은 `길이 · 형식(설명 동영상/토론) · 소스 N개 · 경과`. 보고서는 `보고서 형식명 · 소스 N개`. 메모는 경과만 |
| 재생 | 오디오·동영상 카드에만 재생 버튼 |
| 더보기 | 모든 카드에 세로 점 3개 메뉴 |
| 메모 | 보고서와 구분되는 별도 종류. 채팅 답변의 "메모에 저장"으로도 생성 |
| New 배지 | 새 기능 타일에 일시 표시 |

### 3.2.1 더보기 메뉴와 Notebook 메뉴 (추가 첨부 화면 3종)

**산출물 카드 ⋮ 메뉴** — 5개 항목이 관찰된다.

| 항목 | 아이콘 | 비고 |
| --- | --- | --- |
| 공유 | 공유 | 산출물 단위 공유 |
| 이름 바꾸기 | 연필 | |
| 다운로드 | 다운로드 | 유형에 따라 형식 선택 |
| 프롬프트 및 소스 보기 | 정보 | 생성에 쓰인 지시문(프롬프트)과 Source 목록 확인 |
| 삭제 | 휴지통 | |

**Notebook 상단 바** — `+ 노트북 만들기`, `공유` 버튼, 세로 점 메뉴, 설정, 계정이 있다.

**Notebook ⋮ 메뉴** — Studio·채팅 동작에 영향을 주는 항목이다.

| 항목 | 설명 |
| --- | --- |
| 채팅 설정 | 채팅 응답 방식 설정 |
| 노트북 맞춤설정 | Notebook 전체에 적용되는 목적·스타일 지시. 채팅과 Studio 생성에 함께 반영되는 것으로 추정 |
| 노트북 복사 | Notebook을 복제 |
| 애널리틱스 | 사용 통계 |
| 채팅 기록 삭제 | 보조 문구 "채팅 기록은 나만 볼 수 있습니다" — 채팅 기록은 사용자 개인 범위 |

### 3.3 채팅과의 연결 (첨부 화면 1)

- 채팅 답변 하단에 **메모에 저장**, 복사, 좋아요/싫어요가 있다.
- 채팅 입력창 오른쪽에 **소스 N개** 표시가 있어 현재 질문에 사용되는 Source 수를 알 수 있다.
- Studio 목록은 Source 선택 범위와 별개로 Notebook 단위로 유지된다.

---

## 4. daon-user 재사용 지도

### 4.1 그대로 재사용

| 영역 | 위치 | 이유 |
| --- | --- | --- |
| Source 등록·처리·색인·보존 | `services/api` `source_*`, `document_*`, `*_understanding` | Studio는 읽기 전용 소비자 |
| 질문 응답·근거 | `question_answering*.py`, `citation.py`, `knowledge_retrieval.py` | 생성 시 근거 검색에 사용 |
| 계정·조직·권한·감사 | `identity*`, `authorization`, `audit` | 변경 없음 |
| Provider·모델 라우팅 | `provider_*`, `routing.py`, `model_registry.py` | 생성 모델 선택·한도·키 관리 |
| 외부 전송 정책 | `egress_policy*`, `question_egress.py` | 생성에도 동일 적용 |
| 비동기 작업 큐·워커 | `studio_generation_queue.py`, `studio_generation_worker.py` (Postgres 리스 기반) | 구조를 유지하고 작업 종류를 확장 |
| 내보내기 | `studio_export.py` | 형식 추가만 |
| 3면 워크스페이스 레이아웃 | `packages/ui` `adaptive-workspace`, `product-workspace-shell` | 오른쪽 패널만 교체 |
| Desktop 로컬 서비스·오프라인 | `apps/desktop`, `services/local-service` | 후속 단계에서 연결 |

### 4.2 수정·대체

| 대상 | 현재 | 변경 |
| --- | --- | --- |
| `packages/ui/src/product-studio-model.js` | `OUTPUT_TYPES` 11종, `REQUIRED_SETTINGS` 8개 필수, `confirmGenerationSettings` 필수 확정 | 새 `studio-model`로 대체. 9종 + 메모, 필수 설정 제거 |
| `packages/ui/src/product-studio-pane.jsx` | 설정 폼 중심 338줄 | 타일 격자 + 카드 목록 + 메모 영역으로 재작성 |
| `studio-workflow-model/pane` | 검토·승인·전달 단계 | 산출물 더보기 메뉴의 **선택 기능**으로 이동 |
| `services/api` `studio_workspace.py` | 유형별 분기, 승인 흐름과 결합 | 유형 레지스트리 + 생성기 인터페이스로 분리 (§9) |
| 생성 설정 | `GenerationSettingsSnapshot` 필수 | 선택 설정 + 자동 기본값 스냅샷 |

### 4.3 폐기하지 않고 보존

기존 OutputVersion·검토·승인·전달 데이터와 API는 호환을 위해 유지한다. 새 Studio는 기존 `studio_outputs`를 확장해 사용하며 기존 산출물은 새 목록에서 "업무 산출물" 하위 유형으로 보인다. (마이그레이션 상세는 §11)

---

## 5. 기능 범위: 산출물 9종과 메모

| ID | 산출물 | 입력 | 출력 형태(보기) | 내보내기 | 단계 |
| --- | --- | --- | --- | --- | --- |
| ST-01 | 보고서 | Source | 구조화 문서(제목·절·표·인용) | DOCX, PDF, Markdown | Phase 1 |
| ST-02 | 데이터 표 | Source | 열·행 표 + 셀 근거 | XLSX, CSV, PDF | Phase 1 |
| ST-03 | 마인드맵 | Source | 노드·간선 그래프(확대·접기) | SVG, PNG, JSON | Phase 1 |
| ST-04 | 플래시카드 | Source | 앞·뒤 카드 덱(뒤집기·넘기기) | CSV, JSON, PDF | Phase 1 |
| ST-05 | 퀴즈 | Source | 문항·보기·정답·해설, 채점 모드 | JSON, CSV, PDF | Phase 1 |
| ST-06 | 슬라이드 자료 | Source | 슬라이드 덱(제목·불릿·표·이미지) | PPTX, PDF | **Phase 1** (2026-10-20 결정) |
| ST-07 | 인포그래픽 | Source | 정적 시각 요약 1장(세로형 등) | PNG, SVG, PDF | Phase 2 |
| ST-08 | AI 오디오 오버뷰 | Source | 두 화자 대화 음성 + 스크립트 | MP3/WAV, 스크립트 TXT | Phase 3 |
| ST-09 | 동영상 개요 | Source | 슬라이드+내레이션 영상 | MP4 | Phase 4 |
| ST-10 | 메모 | 사용자 입력 또는 채팅 답변 | 편집 가능한 텍스트 노트 | Markdown, TXT | Phase 1 |

### 5.1 유형별 변형(Format)

NotebookLM 화면의 부제(`설명 동영상`, `토론`, `전략 기획 제안서`)가 보여주듯 한 유형에 여러 형식이 있다. 선택 설정의 "형식"으로 제공한다.

| 유형 | 형식 예 |
| --- | --- |
| 보고서 | 요약 보고서, 브리핑 문서, 블로그 글, 스터디 가이드, 사용자 정의 |
| 오디오 | 심층 분석(두 화자 대화), 요약, 비평, 토론 |
| 동영상 | 설명 동영상, 요약 동영상 |
| 슬라이드 | 상세 덱, 발표용 요약 덱 |
| 퀴즈·카드 | 쉬움·보통·어려움, 문항·카드 수 |

사용자 정의 보고서는 자유 지시문(프롬프트)을 받는다.

### 5.2 1차에 포함하는 부가 동작 (2026-10-20 결정)

| ID | 동작 | 명세 |
| --- | --- | --- |
| ST-A1 | **마인드맵 노드에서 질문** | 노드 클릭 시 "이 개념으로 질문" 버튼이 나타난다. 누르면 채팅 입력창에 `"{노드 라벨}"에 대해 설명해 줘`가 채워지고, 해당 노드의 근거 Source를 질문 범위로 지정한다. 질문은 사용자가 확인·수정 후 전송한다(자동 전송 없음). |
| ST-A2 | **플래시카드·퀴즈 학습 히스토리** | 플래시카드: 카드별 "알아요/모르겠어요" 표시와 마지막 학습 시각. 퀴즈: 풀이 시도별 점수·문항별 정오·소요 시간. 사용자 본인에게만 보이며(개인 범위) 산출물이 삭제되면 함께 삭제된다. "모르는 카드만 다시", "틀린 문항만 다시" 모드를 제공한다. 재생성한 덱·퀴즈의 히스토리는 새 산출물에서 새로 시작한다. |
| ST-A3 | **보고서 형식 선택** | 보고서 생성 설정에서 형식을 고른다: 요약 보고서, 브리핑 문서, 블로그 글, 스터디 가이드, 사용자 정의(자유 지시문). 형식별 기본 구조와 길이 가이드는 형식 프리셋으로 서버가 관리한다. 타일 클릭 시 기본 형식은 요약 보고서. |

데이터: 학습 히스토리는 `studio_learning_attempts`(`output_id`, `revision_id`, `user_id`, `kind`=`flashcard/quiz`, `payload_json`, `created_at`)로 저장하고 API는 `GET/POST /notebooks/{nid}/studio/outputs/{id}/learning-attempts`를 둔다. 히스토리는 감사 대상이 아니며 Notebook 공유 범위에 노출되지 않는다.

---

## 6. 사용자 경험 설계

### 6.1 패널 상태

| 상태 | 표시 |
| --- | --- |
| Source 없음 | 타일 비활성. "자료를 추가하면 만들 수 있어요" 안내 |
| Source 있음, 선택 0개 | 타일 비활성. "자료를 선택하세요" |
| 준비됨 | 타일 활성. 하단 안내에 사용 Source 수 표시 |
| 일부 Source 처리 중 | 처리 완료된 Source만 사용한다는 안내 표시 |

### 6.2 생성 흐름

```text
타일 클릭
 → 기본값으로 작업 생성 (즉시)
 → 목록 맨 위에 "생성 중" 카드 추가 (스피너 + 유형 아이콘)
 → 완료되면 카드가 제목·부제로 확정
 → 카드 클릭 → 상세 뷰어 열기
```

- 타일 옆 연필 아이콘(호버 시 표시)으로 **사용자 설정 대화상자**를 연다. 확인 시 그 설정으로 생성한다.
- 동일 유형을 연속 생성하면 각각 별도 카드가 된다.
- 생성 중 카드는 취소 가능하다.

### 6.3 사용자 설정 대화상자 (모두 선택)

| 항목 | 기본값 | 적용 유형 |
| --- | --- | --- |
| 언어 | Notebook 언어(ko) | 전체 |
| 형식 | 유형별 기본 형식 | 전체 |
| 길이 | 보통 | 보고서·오디오·슬라이드·동영상 |
| 사용 Source | 현재 선택된 Source | 전체 |
| 포커스 지시문 | 없음 | 전체 (예: "3장 위주로") |
| 난이도 | 보통 | 퀴즈·플래시카드 |
| 개수 | 자동 | 퀴즈·플래시카드 |
| 대상 독자 | 일반 | 보고서·슬라이드 |
| 시각 스타일 | 기본 | 인포그래픽·슬라이드·동영상 |

설정은 `settings` JSON으로 저장되며 스키마 검증은 유형별로 한다. 필수 항목은 없다.

### 6.4 산출물 카드

```text
[아이콘] 제목                                   [▶] [⋮]
         부제: 형식 · 소스 N개 · 상대시간
```

| 상태 | 카드 표시 |
| --- | --- |
| queued / generating | 스피너 + "생성 중…" + 취소 |
| completed | 제목·부제 + (오디오·동영상) 재생 버튼 |
| failed | 경고 아이콘 + 사유 + **다시 시도** |
| stale | "Source가 변경됨" 배지 + 다시 생성 제안 |

### 6.5 더보기(⋮) 메뉴

NotebookLM과 같은 **기본 5항목**(공유·이름 바꾸기·다운로드·프롬프트 및 소스 보기·삭제)을 항상 같은 순서로 표시한다. 그 아래 구분선 뒤에 Daon2-User 추가 항목을 둔다.

| 구분 | 항목 | 대상 | 설명 |
| --- | --- | --- | --- |
| 기본 | 공유 | 전체 | 산출물 공유 대화상자 (§6.5.1) |
| 기본 | 이름 바꾸기 | 전체 | 제목 편집 |
| 기본 | 다운로드 | 유형별 | 내보내기 형식 하위 메뉴. 생성 중·실패 카드에서는 비활성 |
| 기본 | 프롬프트 및 소스 보기 | 전체 | 생성에 쓰인 지시문·설정·형식과 사용 Source 목록, 인용 패널 (§6.5.2) |
| 기본 | 삭제 | 전체 | 확인 후 삭제(보존 정책 준수) |
| 추가 | 다시 생성 | 전체 | 같은 설정으로 새 카드 생성 (기존 카드 유지) |
| 추가 | 설정 변경 후 다시 생성 | 전체 | 설정 대화상자 열기 |
| 추가 | 메모로 저장 | 텍스트형 | 내용을 메모로 복사 |
| 추가(후속) | 검토 요청 / 승인 / 전달 | 선택 기능 | **1차 미표시**(2026-10-20 결정). Phase 5에서 조직 정책이 켜진 경우에만 표시 |

#### 6.5.1 공유

- 범위: 산출물은 소유 Notebook의 공유 범위를 따른다. 산출물 "공유"는 해당 산출물을 **볼 수 있는 대상**을 안내·복사하는 대화상자이며, Notebook 권한을 우회하지 않는다.
- 대화상자 구성: 현재 접근 가능한 사용자·그룹 목록, 링크 복사(Notebook 열람 권한이 있는 사용자 전용 링크), 접근 권한이 없는 대상 추가 시 "Notebook 공유가 필요합니다" 안내와 Notebook 공유 대화상자 연결.
- 공개 링크(로그인 없이 열람)는 **제공하지 않는다**(2026-10-20 결정). 산출물별 추가 공유도 1차에서 제외하며, 접근 권한은 Notebook 공유로만 부여한다.

#### 6.5.2 프롬프트 및 소스 보기

| 영역 | 내용 |
| --- | --- |
| 유형·형식 | 예: 보고서 · 브리핑 문서 |
| 지시문 | 포커스 지시문, Notebook 맞춤설정 적용 여부와 내용. 시스템 프롬프트 원문은 노출하지 않고 **사용자가 준 지시문과 적용된 설정**만 표시 |
| 설정 스냅샷 | 언어·길이·난이도·대상 독자·시각 스타일 |
| 사용 Source | 생성 당시 Source 이름·버전 목록(삭제·교체된 Source는 "변경됨" 표시), 클릭 시 Source 보기 |
| 근거 | 인용 참조 목록, 클릭 시 해당 위치 이동 |
| 생성 정보 | 생성 일시, 소요 시간, 상태 이력. 모델·Provider명은 조직 정책에 따라 표시 |
| 동작 | "이 설정으로 다시 생성" 버튼 |

### 6.6 상세 뷰어

| 유형 | 뷰어 |
| --- | --- |
| 보고서 | 읽기 전용 문서. 문장 끝 인용 번호 클릭 → Source 위치 이동. 편집 모드(§6.7) |
| 데이터 표 | 정렬·열 숨김. 셀 클릭 → 근거 |
| 마인드맵 | 확대·축소·이동, 노드 접기, 노드 클릭 → 관련 근거와 "이 노드로 질문하기" |
| 플래시카드 | 카드 뒤집기, 이전·다음, 섞기, "모름 표시" |
| 퀴즈 | 한 문항씩 풀이, 제출 시 정오·해설·근거, 점수 요약 |
| 슬라이드 | 슬라이드 목록 + 큰 화면, 발표자 노트 |
| 인포그래픽 | 이미지 뷰어(확대) |
| 오디오 | 플레이어(재생·속도·구간 이동) + 스크립트 동기 표시 |
| 동영상 | 플레이어 + 챕터 목록 |
| 메모 | 인라인 편집기 |

### 6.7 편집

- 보고서·메모·슬라이드·플래시카드·퀴즈는 **사용자 편집**을 지원한다. 편집은 같은 산출물의 새 Revision으로 저장한다(`revision_type = user_edit`).
- 마인드맵·인포그래픽·오디오·동영상은 편집 대신 **다시 생성**으로 수정한다(Phase 1~4 범위).

### 6.8 메모

| 동작 | 설명 |
| --- | --- |
| 메모 추가 | Studio 하단 버튼 → 빈 메모 생성 → 편집기 열림 |
| 채팅에서 저장 | 답변의 "메모에 저장" → 답변 본문과 **인용을 보존**한 메모 생성 |
| 메모 → Source | "소스로 변환" 으로 메모를 Source에 추가 가능 (사용자 명시 동작, 자동 승격 금지) |

### 6.8.1 Notebook 수준 메뉴와 Studio의 관계

Studio 패널 자체의 화면은 아니지만 생성 동작에 영향을 주므로 이 설계서에서 계약을 정한다. 화면 구현 소유는 Notebook 홈·워크스페이스 영역이며, 아래는 Studio가 의존하는 항목이다.

**상단 바**

| 요소 | 설명 | Studio와의 관계 |
| --- | --- | --- |
| + 노트북 만들기 | 새 Notebook 생성 | 새 Notebook은 빈 Studio로 시작 |
| 공유 | Notebook 공유 대화상자 | 산출물 접근 범위의 기준 (§10) |
| ⋮ 메뉴 | 아래 표 | |

**Notebook ⋮ 메뉴**

| 항목 | 동작 | Studio 영향 |
| --- | --- | --- |
| 채팅 설정 | 응답 길이·스타일 등 채팅 설정 | 없음 (단, 채팅에서 만든 메모는 Studio에 보임) |
| 노트북 맞춤설정 | Notebook 단위 목적·역할·스타일 지시(자유 입력, 길이 상한 있음) | 생성 시 기본 지시문으로 **함께 적용**. 산출물의 "프롬프트 및 소스 보기"에 적용 여부 표시. 설정 변경은 이미 만든 산출물에는 소급 적용하지 않음 |
| 노트북 복사 | Notebook 복제 | Source·메모·산출물 복제 범위를 선택(기본: Source+메모+산출물). 산출물 Asset은 복제 시 새 저장 키로 복사. 권한은 복사한 사용자 소유로 재설정 |
| 애널리틱스 (**1차 제외**, 후속 Phase) | 사용 통계 | Studio 생성 횟수·유형별 비율·실패율 표시(소유자·관리자만). 본문 내용은 집계에 포함하지 않음 |
| 채팅 기록 삭제 | 채팅 기록 삭제, 보조 문구 "채팅 기록은 나만 볼 수 있습니다" | 채팅 기록은 **사용자 개인 범위**로 저장한다. 삭제해도 Studio 산출물·메모는 삭제되지 않음 |

- 채팅 기록 개인 범위 원칙은 §10 권한 표에 반영한다: 채팅 기록은 작성자 본인만 열람, 산출물·메모는 Notebook 권한을 따른다.
- 메모가 채팅 답변에서 만들어진 경우 메모는 Notebook 공유 범위에 노출된다. "메모에 저장" 시 이를 한 번 안내한다(첫 사용 시 토스트).

### 6.9 플랫폼별 배치

| 플랫폼 | Studio 배치 |
| --- | --- |
| Web 넓은 화면 | 오른쪽 패널 (접기 가능) |
| Web 좁은 화면 | 하단 탭 "Studio" 전환 화면. 타일은 2열 |
| Mobile | **후속 Phase.** 위 좁은 화면 구성을 재사용 |
| Desktop | **후속 Phase(1차는 Web만, 2026-10-20 결정).** Web 화면 재사용 + 오프라인 시 로컬 모델이 지원하는 유형만 활성 |

---

## 7. 생성 파이프라인

### 7.1 단계

```text
요청 수신
 → 검증(권한·Source 처리 상태·외부 전송 정책·한도)
 → Job 큐 등록 (queued)
 → Worker 점유 (leased)
 → 근거 수집 (선택 Source 청크·구조 정보 확보)
 → 유형별 생성기 실행 (generating)
 → 구조 검증(스키마·인용 유효성)
 → 렌더링/후처리(이미지·음성·영상 등)
 → 저장 (completed) 또는 실패 (failed)
```

### 7.2 상태 전이

```text
queued → leased → generating → completed
   │         │          │
   │         └──────────┴→ failed ──(재시도)→ queued
   └→ cancelled
completed → stale (Source 변경 감지 시, 표시만)
```

기존 큐의 `queued / leased / generating / completed / failed / unavailable` 상태를 유지하고 `cancelled`, `stale`을 추가한다.

### 7.3 생성기 인터페이스

```text
interface StudioGenerator:
    type_id: str
    settings_schema: JSONSchema
    plan(context, sources, settings) -> GenerationPlan      # 근거 수집 범위·분할 전략
    generate(plan, llm) -> StudioContent                    # 유형별 구조화 콘텐츠
    validate(content, sources) -> list[ValidationIssue]     # 스키마·인용 유효성
    render(content, format) -> bytes | None                 # 내보내기/뷰어용 후처리
```

- 모든 생성기는 **구조화 JSON**(§8.3)을 1차 결과로 만든다. 뷰어와 내보내기는 이 JSON을 사용한다.
- 오디오·동영상은 JSON(스크립트·장면)을 먼저 확정한 뒤 별도 후처리 Job(음성 합성·영상 합성)으로 이어진다.

### 7.4 근거 수집 전략

| Source 규모 | 전략 |
| --- | --- |
| 작음 (모델 컨텍스트 이내) | 전체 텍스트 투입 |
| 큼 | 계층 요약: Source별 요약 → 주제 클러스터 → 생성 (map-reduce) |
| 포커스 지시문 있음 | 지시문 기반 검색 결과를 우선 투입 후 보강 |

- 이미지·PDF·XLSX·DOCX·PPTX·음성 Source의 구조 정보는 daon-user의 `*_understanding` 결과를 사용한다.
- 생성에 사용한 청크 ID는 `evidence_refs`로 보존한다.

### 7.5 인용 계약

- 보고서·슬라이드·퀴즈 해설·플래시카드 뒷면·마인드맵 노드·데이터 표 셀은 **근거 참조**(`source_version_id`, 위치 식별자)를 가진다.
- `validate` 단계에서 참조가 실제 존재하는지 확인한다. 존재하지 않는 참조는 제거하고 해당 문장에 "근거 미확인" 표시를 붙인다. 모든 참조가 무효이면 생성 실패로 처리한다.
- 인포그래픽·오디오·동영상은 장면·구간 단위 근거 목록을 별도 "근거 보기"로 제공한다.

### 7.6 유형별 생성 사양

| 유형 | 핵심 산출 JSON | 주요 검증 |
| --- | --- | --- |
| 보고서 | `{title, sections[{heading, blocks[{type, text/table, refs}]}]}` | 절 수·길이 범위, 모든 사실 문장에 refs |
| 데이터 표 | `{columns[], rows[{cells[{value, refs}]}]}` | 열 정의 일관성, 숫자·날짜 형식 |
| 마인드맵 | `{root, nodes[{id,label,parent,refs}]}` | 트리 무순환, 깊이 ≤ 5, 노드 수 상한 |
| 플래시카드 | `{cards[{front, back, refs}]}` | 중복 제거, 앞면 길이 |
| 퀴즈 | `{questions[{q, options[], answer, explanation, refs}]}` | 정답이 보기에 포함, 보기 중복 없음 |
| 슬라이드 | `{slides[{title, bullets[], table?, image?, notes, refs}]}` | 슬라이드당 불릿 상한, 순서 |
| 인포그래픽 | `{layout, sections[{headline, value, icon, refs}]}` → 렌더링(SVG→PNG) | 텍스트 넘침 검사 |
| 오디오 | `{script[{speaker, text, refs}], duration_est}` → TTS | 화자 교대, 길이 범위 |
| 동영상 | `{scenes[{slide, narration, duration}]}` → 합성 | 장면 수·길이 합 |
| 메모 | `{markdown, refs?}` | — |

### 7.7 제목 자동 생성

완료 시 콘텐츠 첫 문장·핵심 주제를 기반으로 40자 이내 제목을 만든다. 사용자는 이름 바꾸기로 수정한다.

---

## 7A. 지식 연결(MCP)과 생성형 작성

### 7A.1 제품 역할 재정의

Daon2-User의 본질은 **Daon2·Daon2-RAG가 만든 지식 자산(RAG, GraphRAG, 온톨로지)을 근거로 사용자의 요구에 맞는 새 자료를 작성**하는 것이다. NotebookLM형 Studio(§5)는 사용자가 올린 Source에서 요약형 산출물을 만드는 기능이고, 이 절의 **작성(Authoring)** 은 기존 지식을 바탕으로 업무 문서를 새로 만드는 기능이다. 두 기능은 같은 Studio 목록·카드·뷰어·내보내기를 공유한다.

| 구분 | Studio 요약형 (§5) | 작성형 Authoring (이 절) |
| --- | --- | --- |
| 입력 | 사용자 Source | 사용자 요구 + MCP로 제공되는 지식(RAG·GraphRAG·온톨로지) + 사용자 Source |
| 시작 | 타일 클릭 | 작성 템플릿 선택 또는 채팅 요청 → **요구 확인 대화** |
| 사용자 개입 | 없음(선택 설정) | 부족한 정보·자료를 **질문하고 응답**받음 |
| 결과 | 보고서·표·카드 등 | 약관 초안, 제안서 초안, 계약서 초안 등 업무 문서 |

예시 시나리오

| ID | 시나리오 | 주 입력 지식 | 결과 |
| --- | --- | --- | --- |
| AU-S1 | 보험 약관 자료를 기반으로 **새 보험 약관 초안** | 약관 RAG·조항 온톨로지(Daon2-RAG) | 약관 초안(조항별 근거·변경 표시) |
| AU-S2 | 기존 제안서와 **새 RFP**를 기반으로 제안서 초안 | 기존 제안서 RAG, RFP(Source) | RFP 요구사항 대응형 제안서 초안 |
| AU-S3 | 기존 계약서와 **법령 MCP** 기반 새 계약서 | 계약서 RAG, 법령 MCP(국가법령정보센터) | 계약서 초안 + 법령 근거 점검표 |

### 7A.2 기존 설계서·소스 확인 결과

| 항목 | 확인 위치 | 상태 |
| --- | --- | --- |
| Daon Connector 계약(승인 지식·버전 목록·검색, RuleSet 조회·평가, 비동기 Run 상태) | 기존 설계서 §19.2 | **계약만 존재.** Release 1은 읽기·실행 한정 |
| Connector 레지스트리 | `services/api/.../mcp_connector.py` (종류 `mcp`, `daon_approved_knowledge`, 상태 `connected/disconnected/unavailable`) | **구현됨.** 단, 이름과 달리 표준 MCP 클라이언트가 아니라 "MCP 유사" 서버 소유 레지스트리 |
| 승인 지식 Connector | `approved_knowledge_connector.py` (`publish/read/search`) | **메모리 기반 스텁 수준**(원격 Daon2 호출 없음) |
| RuleSet Connector | `ruleset_connector.py` | 스텁 수준 |
| 실제 MCP 연결 | 기존 설계서 §46 (국가법령정보센터 한정, 고정 stdio 서버) | **설계 존재, 법령 1종 한정.** 임의 MCP URL·사용자 명령 실행 제외 |
| GraphRAG·온톨로지·외부 vector | 기존 설계서 §40·§42 등 "제외" 명시 | **Daon2-User 쪽 미구현·명시적 제외** |
| **Daon2-RAG의 MCP** | WSL-server `~/deploy/daon2-rag` 설계서 §5.10(문서 RAG MCP, 소스 개발·기본 OFF·미인수)과 `engines/daon_runtime/app/mcp_*.py`(런타임 어댑터, 2025-06-18) | **설계·소스 존재, 미가동·미검증.** 상세는 §7A.3.2 |
| **Daon2의 MCP 서버** | `~/deploy/daon2` 결정 기록 | **없음.** MCP는 Daon2가 외부 도구를 호출하는 용도, 범용 gateway는 Daon3 |
| 지식 그래프 | `knowledge_graph.py` (29줄, 노드·간선 검증만) | 자료구조 수준 |
| 문서 초안 | `document_draft.py` (27줄, 섹션·근거·검토 상태) | 자료구조 수준, 생성 로직 없음 |
| 사용자에게 부족 자료를 묻는 대화 | `conversation-intent.js`(의도 분류 정규식 42줄) | **작성형 질문 흐름은 없음** |

결론: **연결 계약·레지스트리·안전 경계(egress, 권한, 감사)는 재사용**할 수 있으나, **표준 MCP 클라이언트, Daon2/Daon2-RAG용 MCP 서버 계약, 작성(Authoring) 엔진, 요구 확인 대화**는 신규 설계·구현이 필요하다.

### 7A.3 Daon2·Daon2-RAG의 MCP 제공 구조

Daon2와 Daon2-RAG는 **MCP 서버**로, Daon2-User는 **MCP 클라이언트(호스트)** 로 동작한다. 사용자 선택이 아니라 **조직(관리자)이 등록하는 시스템 Connector**로 둔다.

```text
Daon2-User (MCP Host/Client)
 ├─ 연결 ─ Daon2 MCP Server      : 승인 지식, RuleSet, 업무 엔진 Run
 ├─ 연결 ─ Daon2-RAG MCP Server  : RAG 검색, GraphRAG 질의, 온톨로지 조회
 └─ 연결 ─ 법령 MCP Server       : 국가법령정보센터 (기존 §46)
```

#### 7A.3.1 표준 준수

- MCP 공식 사양을 따른다. 기준 판본은 Daon2-RAG 설계서(§5.10)가 고정한 **2026-07-28**이며, 구현된 런타임 어댑터(2025-06-18)와 기존 daon-user §46의 2025-11-25도 판본 어댑터(§7A.10.3)로 지원한다. 구현 착수 시점에 공식 사양을 재확인한다.
- 전송: **Streamable HTTP**를 원격 서버(Daon2·Daon2-RAG) 기본으로, stdio는 로컬·번들 서버(법령)에 한정. 현재 Daon2-RAG 런타임 어댑터는 단순 JSON-RPC POST이므로 이를 우선 지원한다.
- 수명주기: 판본에 따라 `server/discover`(2026-07-28) 또는 `initialize`(구 판본) → capability 협상 → `tools/list`·`resources/list`·`prompts/list` → 호출.
- 인증: MCP 권한 부여(OAuth 2.1 계열) 또는 조직 서비스 토큰. 자격정보는 서버 측에만 보관하고 브라우저에는 노출하지 않는다.
- 호스트가 모든 호출을 중개한다. LLM이 임의 URL·명령을 지정할 수 없다(기존 §46.3 원칙 유지).

#### 7A.3.2 서버별 제공 Capability

**확인된 현황 (2026-10-20, WSL-server `~/deploy/daon2-rag`, `~/deploy/daon2` 코드·설계서 확인)**

| 대상 | 현황 | 판단 |
| --- | --- | --- |
| Daon2-RAG 설계 §5.10 "문서 RAG의 MCP 제공" (2026-10-04 서면 검토안) | `POST /mcp`, 도구 `search_document_evidence`(필수 `project_id`·`work_package_id`·`question`), `get_document_evidence`, 리소스 `daon2-rag://documents/{document_id}/versions/{version_id}/runs/{run_id}/blocks/{block_id}`, 기준 프로토콜 MCP 2026-07-28(`server/discover`, 세션 없음), 서비스 신원·전용 audience·허용 쌍 검증, `DAON_DOCUMENT_MCP_ENABLED=false` 기본 OFF. **소스 개발 상태 보존, 실제 인수 검증은 사용자 인수테스트 단계** | 계약은 있으나 **미가동·미검증**. Daon2-User의 1차 소비 대상 |
| Daon2-RAG `engines/daon_runtime/app/mcp_*.py` | JSON-RPC 어댑터, 프로토콜 `2025-06-18`, 도구 `rag.search`·`rag.get_evidence`·`rag.get_context`·`rag.explain_lineage`(snapshot 기반) | 위 설계와 **다른 계열**(런타임 엔진용). 서버 조립 경계(`mcp_production.py`)만 있고 가동 여부 미확인 |
| Daon2 (온톨로지·RuleSet·GraphRAG) | MCP는 Daon2가 **외부 도구를 호출하는 용도**로 정의(2026-06-28 결정), 범용 MCP/tool gateway는 Daon3 범위. 온톨로지 그래프는 PostgreSQL 저장·조회·outbox worker와 관리자 화면이 있고, GraphRAG는 Daon2 기능이며 **제품 경로 동작 미확인**(2026-10-12 계획서). RAG ↔ Daon2 연결은 `OntologyRagClient`와 consumer 계약 V1(REST 계열) | **Daon2는 MCP 서버를 제공하지 않는다.** 신규 요청 대상 |
| 역할 경계 | RAG 설계서: "전문가 RuleSet·온톨로지는 Daon2, 최종 답변·자료 작성은 Daon-user가 담당. MCP는 문서 RAG의 **읽기 전용** 채널" | Daon2-User가 작성(Authoring)을 맡는 이 설계와 일치 |

**결정(2026-10-20): Daon2-RAG·Daon2의 MCP 연결은 아직 미완이므로 Daon2-User는 계약을 먼저 정의하고 가상(Virtual) MCP 서버로 개발을 진행한다.** 가상 서버는 표준 MCP를 따르며(§7A.10), 실제 서버가 준비되면 엔드포인트 교체만으로 전환한다. 가상 계약에서 현재 서버에 없는 기능은 **요청 설계서**(`docs/requests/daon2-mcp-provider-request.md`)로 Daon2-RAG·Daon2에 요청한다.

**Daon2-User가 사용하는 가상 계약 (Contract v0)**

원칙: 이름·입력은 Daon2-RAG 설계 §5.10의 기존 도구를 그대로 쓰고, 없는 것만 추가한다. 도구 이름은 snake_case.

| 서버 | 도구/리소스 | 상태 | 용도 |
| --- | --- | --- | --- |
| daon2-rag | `search_document_evidence` | **기존(설계 §5.10)** | 질문으로 문서 근거 검색 (project·work package 필수) |
| daon2-rag | `get_document_evidence` | **기존** | 근거 블록 재조회 |
| daon2-rag | resource `daon2-rag://documents/.../blocks/{block_id}` | **기존** | 블록 원문 읽기 |
| daon2-rag | `list_knowledge_scopes` | **요청** | 호출자가 읽을 수 있는 project·work package 목록 (질문 선택지·템플릿 입력용) |
| daon2-rag | `list_documents` | **요청** | scope 안 문서 목록·유형·버전·메타데이터 (예: 기존 제안서 선택) |
| daon2-rag | `get_document_outline` | **요청** | 문서 목차·구조(장·절·조항, 블록 ID 매핑) |
| daon2-rag | `read_document_section` | **요청** | 절/조항 단위 본문과 블록 목록 (기존 약관·제안서 섹션 재사용) |
| daon2-rag | 검색 필터·페이지네이션·유형 필터 | **요청** | `document_type`, 날짜, 메타데이터 필터, cursor |
| daon2-rag | `resources/subscribe`·`notifications/resources/updated` 또는 버전 조회 | **요청** | 지식 갱신 감지(산출물 stale) |
| daon2 | `ontology_search_concepts`, `ontology_get_concept`, `ontology_traverse` | **요청(신규)** | 개념·조항 유형·관계 조회와 탐색 |
| daon2 | `graphrag_query` (`mode`: `local`/`global`) | **요청(신규)** | GraphRAG 질의, 엔티티·관계·커뮤니티 요약·근거 반환 |
| daon2 | `ruleset_list`, `ruleset_get`, `ruleset_evaluate` | **요청(신규)** | 점검 규칙 조회와 초안 평가 |
| daon2 | `approved_knowledge_search`, `approved_knowledge_read` | **요청(신규, 기존 §19.2 계약)** | 전문가 승인 지식 |
| daon2 | prompt `authoring_template` (`prompts/list`·`prompts/get`) | **요청(신규)** | 작성 템플릿(필수 입력·섹션·점검 규칙) |

- 도구 입력·출력은 JSON Schema(`inputSchema`, `outputSchema`)를 가지며, 모든 결과는 **출처 식별자·지식 버전·계보**를 포함한다.
- 요청 항목의 상세 사양과 수용 기준은 요청 설계서에 있다. Daon2-User는 요청이 수용되기 전에도 가상 서버로 개발·시험한다.
- 프로토콜 판본: Daon2-RAG 설계서가 고정한 **MCP 2026-07-28**을 기준으로 하고, 구현된 런타임 어댑터는 2025-06-18이다. Daon2-User 클라이언트는 전송·수명주기 차이를 어댑터 뒤에 숨기고 협상된 판본으로 동작한다(§7A.10.3). 구현 착수 시 공식 명세를 재확인한다.

#### 7A.3.3 Connector 관리

| 항목 | 규칙 |
| --- | --- |
| 등록 | 조직 관리자만 등록·해제. 서버 URL·인증·허용 도구 목록·허용 컬렉션을 설정 |
| 도구 허용 | 서버가 광고하는 모든 도구가 아니라 **관리자가 허용한 도구만** 호스트에 노출 |
| 연결 확인 | 등록과 실제 연결 확인을 구분 (기존 §46.2: `CONNECTOR_NOT_VERIFIED`) |
| 상태 | `connected / disconnected / unavailable` + 마지막 확인 시각·오류 코드 (기존 DTO 유지) |
| 권한 | 호출 직전 현재 사용자·조직·Notebook 권한과 egress 정책 재확인 |
| 감사 | 호출 도구명·대상 서버·사용자·시각·결과 건수만 기록. 질의·응답 본문은 기록하지 않음 |
| 한도 | 호출당 타임아웃, 사용자·조직별 호출 한도, 동시 호출 제한 |
| 결과 취급 | MCP 응답은 **신뢰할 수 없는 데이터**다. 응답 안의 지시문을 실행하지 않는다(프롬프트 인젝션 방지) |

### 7A.4 지식 소비 모델

MCP로 받은 자료는 사용자 Source와 달리 **원격 지식 참조**이며 다음 중 하나로 소비한다.

| 방식 | 설명 | 용도 |
| --- | --- | --- |
| 즉시 조회(Ephemeral) | 생성 중 호출해 컨텍스트에만 사용, 저장 안 함 | 일반 검색·조회 |
| 근거 스냅샷(Snapshot) | 산출물에 쓰인 청크·그래프 조각을 **불변 스냅샷**으로 저장하고 해시 기록 | 근거 보기·재현·감사 |
| Source로 가져오기 | 사용자 명시 동작으로 Notebook Source에 등록 (기존 §46.4 import 방식) | 사용자가 오래 참조할 자료 |

- 산출물에는 사용한 **지식 서버·컬렉션·버전·청크 ID**를 근거 참조(EvidenceRef)로 저장한다. EvidenceRef에 `origin = notebook_source | mcp_daon_rag | mcp_daon | mcp_law`를 추가한다.
- 원격 지식 버전이 이후 갱신되면 산출물은 `stale`(§8.4)로 표시한다.

### 7A.5 작성(Authoring) 흐름

```text
작성 시작 (템플릿 선택 또는 채팅 요청)
 → 1. 작업 정의: 문서 종류·목적·대상·분량
 → 2. 요구 분석: 템플릿의 필수 입력 목록 대비 현재 정보 점검
 → 3. 요구 확인 대화: 부족 정보·자료를 사용자에게 질문
 → 4. 지식 수집: MCP(RAG·GraphRAG·온톨로지·법령) + 사용자 Source
 → 5. 계획 확인: 목차·참조 지식·가정 목록을 사용자에게 제시 (수정 가능)
 → 6. 초안 생성: 섹션별 생성 + 근거 연결
 → 7. 점검: RuleSet·법령·필수 조항·충돌·누락 점검
 → 8. 결과: Studio 카드로 저장, 뷰어에서 편집·재생성·내보내기
```

#### 7A.5.1 작성 템플릿 (Skill형 정의)

작성 유형은 **작성 템플릿**으로 선언한다. 템플릿은 Daon2의 `authoring_template` prompt 또는 조직이 관리하는 파일로 제공하며, 코드 변경 없이 추가할 수 있다.

```yaml
template_id: insurance_terms_draft
title: 보험 약관 초안
version: 1
inputs:                       # 요구 확인 대화의 질문 목록
  - key: product_type
    question: 어떤 종류의 보험입니까? (예: 실손, 종신, 자동차)
    required: true
  - key: base_terms
    question: 기준으로 삼을 기존 약관을 선택해 주세요.
    kind: knowledge_ref       # RAG 컬렉션·문서 선택
    required: true
  - key: change_points
    question: 기존 약관에서 바꾸려는 점이 있나요?
    required: false
knowledge:                    # 지식 수집 계획
  - tool: search_document_evidence
  - tool: ontology_search_concepts
  - tool: ruleset_get
sections:                     # 초안 구성
  - 총칙, 보장 내용, 보험금 지급사유, 면책, 보험료, 계약 해지, 분쟁 해결
checks:                       # 점검 규칙
  - ruleset: insurance_terms_required_clauses
  - law: 보험업법·약관규제법 관련 조문 대조
output:
  type: document_draft
  formats: [docx, pptx]      # 인터뷰 결정: 작성 결과 형식 DOCX·PPTX
```

**첫 구현 템플릿: RFP 대응 제안서 초안 (인터뷰 결정 반영)**

```yaml
template_id: rfp_response_proposal
inputs:
  - { key: rfp_document,        question: "대상 RFP 문서를 선택해 주세요.",            kind: source_ref,    required: true }
  - { key: reference_proposals, question: "참고할 기존 제안서를 선택해 주세요.",        kind: knowledge_ref, required: true }
  - { key: proposer_profile,    question: "제안 주체의 강점·실적·인력을 알려 주세요.",   kind: text,          required: false }
  - { key: price_schedule,      question: "가격(예산)과 일정, 투입 인력을 알려 주세요.", kind: structured,    required: false }
knowledge:
  - { tool: list_documents, args: { document_type: proposal } }
  - { tool: get_document_outline }
  - { tool: search_document_evidence }
  - { tool: ontology_search_concepts }
sections: [사업 이해, 요구사항 대응, 수행 방안, 일정·조직, 가격, 부록(요구사항 대응표)]
checks:
  - { derived: rfp_requirement_coverage }     # 모든 RFP 요구사항이 제안서 섹션에 대응되는지
  - { ruleset: proposal_required_sections }
output: { type: document_draft, formats: [docx, pptx], user_selectable: true }   # 생성 시 DOCX만 / PPTX만 / 둘 다 선택
```

- **필수 입력**은 대상 RFP 문서와 참고할 기존 제안서 2개다. 비어 있으면 초안 생성을 시작하지 않고 다시 묻는다(§7A.5.2).
- **선택 입력**은 제안 주체·강점, 가격·일정이다. 사용자가 모르면 "미정"으로 두고 진행할 수 있으며, 해당 위치는 초안에 `[작성 필요]`로 표시하고 가정 목록에 기록한다. 이후 입력해 다시 생성할 수 있다.
- **요구사항 확인 단계는 필수**다. RFP에서 추출한 요구사항 목록을 계획 확인(§7A.5.3)에서 사용자에게 보여 주고 추가·삭제·수정 후 확정해야 초안 작성이 시작된다.
- 출력은 DOCX(본문 제안서), PPTX(발표용) 중 **사용자가 생성 시 선택**한다(기본: DOCX). PPTX를 선택하면 DOCX와 별도로 발표 흐름에 맞춰 구성한다. 요구사항 대응표는 DOCX 부록 표로 포함한다.

- 템플릿은 `inputs`로 **무엇을 물을지**, `knowledge`로 **무엇을 가져올지**, `checks`로 **무엇을 점검할지**를 정의한다.
- 템플릿이 없는 자유 요청(예: "이 RFP에 맞는 제안서 써줘")은 서버가 요청을 분류하고 가장 가까운 템플릿을 제안한다. 맞는 템플릿이 없으면 일반 작성 템플릿(`generic_document`)을 사용한다.

#### 7A.5.2 요구 확인 대화 (질문형 수집)

| 규칙 | 내용 |
| --- | --- |
| 질문 시점 | 필수 입력 중 값이 없거나 모호할 때만 질문한다. 이미 대화·Source에서 확인된 값은 묻지 않는다. |
| 질문 방식 | 한 번에 최대 3개 묶음 질문. 선택지가 있으면 선택형(버튼), 자료가 필요하면 **자료 요청**(Source 추가·지식 컬렉션 선택) |
| 자료 요청 | "기존 약관 PDF를 추가해 주세요", "비교할 RFP를 선택해 주세요"처럼 필요한 자료를 구체적으로 요청 |
| 기본값 제안 | 근거 있는 기본값을 제시하고 사용자가 수정·확정 |
| 건너뛰기 | 선택 입력은 건너뛸 수 있고 "가정" 목록에 기록 |
| 중단·재개 | 작성 세션은 저장되며 나중에 이어서 진행 |
| 종료 조건 | 필수 입력이 모두 확정되면 계획 확인 단계로 이동 |

요구 확인은 채팅 패널에서 진행하고, 진행 상황(입력 n/m 확정)은 Studio 카드에 "작성 중 · 입력 대기"로 표시한다. 사용자가 응답해야 하는 상태는 카드에 별도 배지(입력 필요)를 보인다.

#### 7A.5.3 계획 확인

초안을 쓰기 전에 다음을 사용자에게 보여 주고 확인받는다. 수정 후 확정한다.

- 문서 목차와 섹션별 목적
- 사용할 지식(서버·컬렉션·문서·법령)과 사용자 Source
- 적용되는 점검 규칙(RuleSet·법령)
- 가정 목록(질문에 답하지 않아 기본값으로 둔 항목)

#### 7A.5.4 초안 생성과 근거

- 섹션별로 생성하고 각 문장·조항에 근거 참조를 연결한다. 근거가 없는 신규 문구는 `신규 작성(근거 없음)`으로 표시해 검토 대상으로 분리한다.
- **변경 표시**: 기존 문서를 바탕으로 한 작성(AU-S1)은 기존 조항과의 차이(유지·수정·신규·삭제 제안)를 표시한다.
- **RFP 대응**(AU-S2): RFP 요구사항을 추출해 요구사항 목록을 만들고, 각 요구사항에 대응하는 제안서 섹션과 근거 지식을 연결한 **대응표**를 함께 생성한다. 대응되지 않은 요구사항은 누락으로 경고한다.
- **법령 대조**(AU-S3): 계약서 조항별로 관련 법령 조문을 대조하고 충돌·누락을 점검표로 제공한다. 법률 자문·판정으로 표현하지 않고 "근거 대조" 결과로 표시한다.

#### 7A.5.5 점검과 경고

| 점검 | 방식 | 결과 표시 |
| --- | --- | --- |
| 필수 조항·항목 | 템플릿 `checks`, Daon2 `ruleset_evaluate` | 충족/미충족/확인 필요 |
| 법령 대조 | 법령 MCP | 관련 조문·충돌 가능 항목 |
| 근거 무결성 | EvidenceRef 검증 | "근거 미확인" 배지 |
| 용어·일관성 | 온톨로지 기준 용어 점검 | 용어 불일치 목록 |

점검 결과는 산출물 상세의 "점검" 탭에 표시하고, 위반 항목 클릭 시 해당 위치로 이동한다.

### 7A.6 결과와 Studio 연동

- 작성 결과는 Studio 카드 유형 `authored_document`(하위 `template_id`)로 저장한다. 카드 부제는 `{템플릿명} · 지식 N건 · 소스 N개 · 경과`.
- ⋮ 메뉴의 "프롬프트 및 소스 보기"(§6.5.2)에 **요구 확인 응답, 사용한 MCP 도구·컬렉션·버전, 가정 목록, 점검 결과**를 포함한다.
- 사용자 편집·재생성(§6.7)을 지원한다. 입력을 바꿔 다시 생성하면 기존 응답을 불러와 수정한다.
- 작성 결과를 Daon2의 지식으로 되돌려 등록하는 기능은 범위 밖이다. 등록은 기존 거버넌스(검토·승인)를 거치는 별도 기능이며 Phase 5에서 다룬다.
- 요약형 Studio(§5)도 Notebook에서 "지식 컬렉션 선택" 시 MCP 지식을 입력으로 사용할 수 있다(Phase 후속).

### 7A.7 API 추가 (초안)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/knowledge-connectors` | 조직에 등록된 MCP Connector 목록·상태·허용 컬렉션 |
| POST·DELETE | `/admin/knowledge-connectors` | 등록·해제 (조직 관리자) |
| POST | `/admin/knowledge-connectors/{id}/verify` | 연결 확인(initialize·도구 목록 점검) |
| GET | `/notebooks/{nid}/authoring/templates` | 사용 가능한 작성 템플릿 목록 |
| POST | `/notebooks/{nid}/authoring/sessions` | 작성 세션 시작 `{template_id?, request_text?}` |
| GET | `/notebooks/{nid}/authoring/sessions/{sid}` | 세션 상태: 확정 입력, 대기 질문, 단계 |
| POST | `/notebooks/{nid}/authoring/sessions/{sid}/answers` | 질문 응답 제출(값, 선택한 지식·Source) |
| POST | `/notebooks/{nid}/authoring/sessions/{sid}/plan/confirm` | 계획 확인·수정 후 확정 |
| POST | `/notebooks/{nid}/authoring/sessions/{sid}/cancel` | 중단 |

세션이 완료되면 `studio_outputs`에 산출물이 생성되고 기존 생성 Job·상태 구독을 그대로 사용한다.

### 7A.8 보안·정책

| 항목 | 규칙 |
| --- | --- |
| 지식 접근 | 사용자·조직 권한에 맞는 결과만 사용한다. **권한 전달 방식은 미정**(위임 토큰 vs 서비스 계정 + 범위 필터, §16-17, 수신측 회신 대기). 가상 서버는 서비스 계정 + 허용 쌍 필터로 시험하고, Daon2-User는 어느 방식이든 호출 전 사용자 권한을 재확인한다 |
| 외부 전송 | MCP 서버가 조직 내부 서비스인지 외부 서비스인지 등록 시 분류하고, 외부 분류는 기존 egress 정책을 통과해야 호출 |
| 프롬프트 인젝션 | 지식 응답은 데이터로만 취급. 응답 속 지시문 실행 금지, 도구 호출은 템플릿·계획에 선언된 것만 |
| 민감 정보 | 작성 중 사용자 입력은 모델 Provider 정책에 따라 처리. 로그에 본문 미기록 |
| 책임 표시 | 약관·계약서 초안에는 "AI 작성 초안, 전문가 검토 필요" 문구를 고정 표시 |

### 7A.9 단계별 구현 위치

§13의 단계에 다음 Phase를 추가한다.

| 단계 | 내용 | 완료 기준 |
| --- | --- | --- |
| Phase M0 | MCP 클라이언트 기반(판본 어댑터 포함)·Connector 관리·관리자 등록·연결 확인·감사, **가상 MCP 서버·Contract v0·계약 시험 모음(§7A.10)**, 법령 MCP 재연결 | 가상 서버와 발견·tools/list·tools/call·resources/read 성공, 권한·결함 주입 시험 통과 |
| Phase M1 | 실제 서버 전환: Daon2-RAG `search_document_evidence`/`get_document_evidence` 가동 시 교체, 요청 항목 수용 순서대로 교체 | 실제 서버가 Contract v0 필수 시험 통과, 질의→근거 스냅샷 저장→Studio 근거 보기 |
| Phase A1 | 작성 엔진 기본(템플릿 로더, 요구 확인 대화, 계획 확인, 섹션 생성)과 **첫 템플릿: RFP 대응 제안서**(요구사항 추출·확인, 대응표, DOCX/PPTX 출력) | AU-S2 종단 시나리오(합성 코퍼스, 수동 평가) |
| Phase A2 | 보험 약관(변경 표시)·계약서(법령 MCP 대조 점검표) 템플릿 | AU-S1, AU-S3 종단 시나리오 |
| Phase A3 | RuleSet 점검 연동, 템플릿 관리 UI (작성 결과 지식 재등록은 현재 불필요, 2026-10-20 결정) | 점검 탭, 조직 템플릿 추가 |

> 실행 순서(2026-10-20 결정): Phase 0 → **Phase 1(요약형 Studio, 슬라이드 포함)과 Phase M0(가상 MCP)를 병행** → Phase A1(RFP 템플릿) → Phase A2 → Phase 2 이후. Phase M1(실서버 전환)은 Daon2-RAG·Daon2 준비 시점에 맞춰 수시 진행한다. 상세 일정은 §13.2.

---

### 7A.10 가상(Virtual) MCP 서버와 개발 전략

#### 7A.10.1 목적

Daon2-RAG·Daon2의 MCP 제공이 미완이어도 Daon2-User 개발을 막지 않는다. **계약을 먼저 고정**하고 가상 서버가 그 계약을 제공하며, 실제 서버가 준비되면 같은 계약 시험을 통과시켜 교체한다.

#### 7A.10.2 구성

```text
services/mcp-virtual/            (신규, 개발·QA 전용)
  daon2_rag_virtual/             search_document_evidence 등 Daon2-RAG 계약 구현
  daon2_virtual/                 ontology·graphrag·ruleset·approved_knowledge·prompts
  fixtures/                      합성 지식 (약관·제안서·RFP·계약서·법령 조문, 온톨로지, RuleSet)
  contracts/                     Contract v0 (도구·리소스 JSON Schema, 오류 코드, 예제)
packages/mcp-contract-tests/     실제/가상 서버 공통 계약 시험 (client-side conformance)
```

| 항목 | 규칙 |
| --- | --- |
| 표준 준수 | 공식 MCP SDK를 사용해 표준 전송·수명주기·`tools/list`·`resources/*`·`prompts/*`를 제공한다. 임의 프로토콜을 만들지 않는다. |
| 데이터 | **합성 데이터만** 사용한다(실제 보험·계약·제안서 사용 금지). 업무 도메인별 소규모 코퍼스: 보험 약관 3종, 제안서 3건, RFP 2건, 계약서 3건, 법령 조문 일부 |
| 결정성 | 같은 입력은 같은 결과를 반환한다(점수·순서 고정). 시험 재현성 확보 |
| 결함 주입 | 헤더 `X-Virtual-Fault` 또는 도구 인자로 **지연·타임아웃·빈 결과·권한 거부·모델 불일치·버전 변경·잘못된 스키마** 응답을 재현한다 |
| 버전 변경 | fixture를 갱신하는 관리 엔드포인트로 지식 버전 갱신 → stale 시험 |
| 인증 | 실제와 같은 방식(Bearer, audience, scope 허용 쌍)을 흉내 내어 클라이언트 인증 경로를 시험한다. 시험용 키는 문서에 기록하지 않는다. |
| 배포 | 로컬 프로세스(개발)와 WSL-server `daon2_user` Compose 서비스(테스트)로 실행. 기본 비공개 네트워크 |
| 경계 | 운영 환경에서는 가상 서버 연결을 **차단**한다(환경 변수 `ENV=production`이면 가상 Connector 등록 거부) |
| 표시 | 가상 서버 응답에는 `serverInfo.name`이 `*-virtual`이고, UI 근거 보기에 "가상 지식(시험용)" 배지를 표시한다 |

#### 7A.10.3 클라이언트 어댑터

- Daon2-User MCP 클라이언트는 `McpTransport`(요청 전송)와 `McpLifecycle`(discover/initialize)을 어댑터로 분리한다.
- 지원 판본: 2026-07-28(주), 2025-06-18(보조, Daon2-RAG 런타임 어댑터 대응). 서버가 알리는 판본으로 협상한다.
- 판본이 지원 범위 밖이면 연결을 `unavailable`(`MCP_VERSION_UNSUPPORTED`)로 표시한다.

#### 7A.10.4 계약 시험(Contract Conformance)

공통 시험 모음을 가상 서버와 실제 서버에 동일하게 실행한다.

| 시험 | 내용 |
| --- | --- |
| 발견 | 서버 정보·판본·capability, 도구·리소스·프롬프트 목록 |
| 스키마 | 모든 도구의 입력·출력이 Contract v0 스키마와 일치 |
| 근거 | 결과마다 출처 ID·버전·계보 존재, `get_document_evidence`로 재조회 시 일치 |
| 권한 | 허용 밖 scope 요청은 거부, 타 scope 블록은 존재 비노출 오류 |
| 오류 | 타임아웃·빈 결과·모델 불일치·미완료·삭제 문서의 오류 코드 구분 |
| 한도 | 결과 크기·페이지 상한 준수 |
| 갱신 | 버전 변경 감지(구독 또는 조회) |

실제 서버 전환 기준: **Contract v0 필수 시험 100% 통과**. 요청 항목 중 미수용 기능은 시험 목록에서 `pending`으로 표시하고, 해당 기능을 쓰는 템플릿은 비활성(또는 가상 서버 전용)으로 유지한다.

#### 7A.10.5 전환 절차

1. 가상 서버로 Phase M0~A1 개발·시험 (WSL-server `daon2_user` 환경)
2. Daon2-RAG `search_document_evidence`/`get_document_evidence` 가동 시 해당 Connector만 실제 엔드포인트로 교체, 계약 시험 실행
3. 요청 항목이 수용되는 순서대로 가상 도구를 실제 도구로 교체
4. 모든 Connector가 실제 서버가 되면 가상 서버는 QA 전용으로 유지(결함 주입 시험용)

#### 7A.10.6 요청 설계서

Daon2-RAG·Daon2에 요청하는 기능과 수용 기준은 `docs/requests/daon2-mcp-provider-request.md`에 정리했다. 요청 수용 여부와 일정은 해당 문서의 상태 표에서 관리한다.

---

## 8. 데이터 모델

### 8.1 개념

```text
Notebook 1 ─ n StudioOutput ─ n OutputRevision
                   │
                   ├─ 1 GenerationJob (최근)  ─ n 상태 이력
                   ├─ n EvidenceRef
                   └─ n Asset (오디오·이미지·영상 파일)
Notebook 1 ─ n Memo (StudioOutput의 한 유형으로 취급)
```

### 8.2 테이블 초안

기존 `studio_outputs` 계열을 확장한다. 정확한 DDL은 구현 단계에서 확정하며 아래는 의미 수준이다.

| 테이블 | 주요 컬럼 | 비고 |
| --- | --- | --- |
| `studio_outputs` | `output_id`, `tenant_id`, `notebook_id`, `owner_id`, `type_id`, `format_id`, `title`, `status`, `source_count`, `created_at`, `updated_at`, `deleted_at` | 기존 컬럼 유지 + `type_id` 값 확장 |
| `studio_output_revisions` | `revision_id`, `output_id`, `revision_no`, `revision_type`(`generated/user_edit/regenerated`), `content_json`, `content_sha256`, `settings_json`, `created_at` | 저장된 Revision은 불변 |
| `studio_output_sources` | `output_id`, `revision_id`, `source_version_id` | 생성 당시 Source 스냅샷 |
| `studio_output_evidence` | `revision_id`, `ref_id`, `source_version_id`, `locator`, `quote_hash` | 인용 위치 |
| `studio_output_assets` | `asset_id`, `revision_id`, `kind`(`audio/image/video/pptx…`), `storage_key`, `bytes`, `duration_ms`, `sha256` | 파일은 객체 저장소 |
| `studio_generation_jobs` | 기존 큐 테이블 유지 + `type_id`, `progress_pct`, `cancel_requested` | |

### 8.3 콘텐츠 JSON 공통 봉투

```json
{
  "schema": "studio.report.v1",
  "language": "ko",
  "generated_with": {"provider": "...", "model": "...", "prompt_version": "..."},
  "body": { },
  "warnings": [{"code": "UNVERIFIED_CLAIM", "path": "/body/sections/2/blocks/1"}]
}
```

- 스키마 이름에 버전을 포함해 이후 변경에 대응한다.
- `generated_with`는 감사·재현용이며 UI에 기본 노출하지 않는다.

### 8.4 Stale 판정

산출물의 `studio_output_sources`에 있는 `source_version_id`가 새 버전으로 교체되거나 삭제되면 해당 산출물을 `stale`로 표시한다. 자동 재생성은 하지 않는다.

---

## 9. API 설계 (초안)

기존 `/api/v1` 규칙, 인증, Idempotency-Key, 오류 코드 체계를 따른다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/notebooks/{nid}/studio/types` | 사용 가능 유형·형식·설정 스키마·비활성 사유 |
| POST | `/notebooks/{nid}/studio/outputs` | 생성 요청 `{type_id, format_id?, settings?, source_version_ids?}` → `202 {output_id, job_id}` |
| GET | `/notebooks/{nid}/studio/outputs` | 카드 목록(상태·제목·부제 필드), 페이징 |
| GET | `/notebooks/{nid}/studio/outputs/{id}` | 상세(최신 Revision 콘텐츠) |
| PATCH | `/notebooks/{nid}/studio/outputs/{id}` | 제목 변경 |
| POST | `/notebooks/{nid}/studio/outputs/{id}/revisions` | 사용자 편집 저장 |
| POST | `/notebooks/{nid}/studio/outputs/{id}/regenerate` | 같은 설정/변경 설정으로 재생성 |
| POST | `/notebooks/{nid}/studio/outputs/{id}/cancel` | 생성 취소 |
| DELETE | `/notebooks/{nid}/studio/outputs/{id}` | 삭제 |
| GET | `/notebooks/{nid}/studio/outputs/{id}/exports/{format}` | 내보내기. Idempotency-Key 유지, Step-up 인증은 **조직 정책이 켜진 경우만** 요구(2026-10-20 결정) |
| GET | `/notebooks/{nid}/studio/outputs/{id}/assets/{asset_id}` | 오디오·이미지·영상 스트리밍(Range 지원) |
| POST | `/notebooks/{nid}/studio/memos` | 메모 생성(빈 메모 또는 채팅 답변 변환) |
| GET | `/notebooks/{nid}/studio/outputs/{id}/provenance` | 프롬프트 및 소스 보기: 지시문·설정 스냅샷·Source·근거 목록 |
| GET·PUT | `/notebooks/{nid}/customization` | 노트북 맞춤설정 조회·저장 (생성 기본 지시문) |
| POST | `/notebooks/{nid}/copy` | Notebook 복사 `{include: [sources, memos, outputs]}` |
| GET | `/notebooks/{nid}/analytics/studio` | **(후속, 1차 제외)** Studio 사용 통계(소유자·관리자) |
| DELETE | `/notebooks/{nid}/chat-history` | 본인 채팅 기록 삭제 |
| GET | `/notebooks/{nid}/studio/outputs/{id}/sharing` | 산출물 접근 가능 대상 조회(Notebook 권한 기준). 산출물별 추가 공유 변경(PUT)은 후속 |
| GET·POST | `/notebooks/{nid}/studio/outputs/{id}/learning-attempts` | 플래시카드·퀴즈 학습 히스토리(§5.2, 본인 범위) |
| GET | `/notebooks/{nid}/studio/events` | 생성 상태 변경 스트림(SSE). 미지원 환경은 목록 폴링 |

### 9.1 생성 요청 예

```json
POST /api/v1/notebooks/nb_1/studio/outputs
{ "type_id": "report", "format_id": "briefing" }
```

설정을 보내지 않으면 서버가 기본값으로 스냅샷을 만들고, 선택 Source가 없으면 요청에서 `source_version_ids`를 받는다. 처리 완료 Source가 없으면 `STUDIO_NO_READY_SOURCE`를 반환한다.

### 9.2 오류 코드 (신규)

| 코드 | 의미 | UI 문구 방향 |
| --- | --- | --- |
| `STUDIO_NO_READY_SOURCE` | 처리 완료 Source 없음 | 자료 처리 완료 후 시도 |
| `STUDIO_TYPE_UNAVAILABLE` | 현재 환경에서 유형 미지원 | 비활성 사유 표시 |
| `STUDIO_QUOTA_EXCEEDED` | 한도 초과 | 한도·재설정 시점 안내 |
| `STUDIO_EGRESS_BLOCKED` | 외부 전송 정책 차단 | 정책 안내 |
| `STUDIO_GENERATION_FAILED` | 생성 실패 | 다시 시도 |
| `STUDIO_VALIDATION_FAILED` | 근거 검증 실패 | 포커스 지시문 조정 제안 |
| `STUDIO_CANCELLED` | 사용자 취소 | — |

---

## 10. 권한·보안·거버넌스

| 항목 | 규칙 |
| --- | --- |
| 채팅 기록 | 작성자 본인만 열람·삭제 가능. 산출물·메모와 별도 범위 |
| 접근 | 산출물은 소유 Notebook의 권한을 따른다. Notebook 열람자는 목록·상세·내보내기 가능 여부를 Notebook 역할에서 상속한다. |
| 생성 권한 | Notebook 편집 이상 |
| Source 접근 | 생성 시점에 요청자가 읽을 수 있는 Source만 사용 |
| 외부 전송 | 기존 `egress_policy` 판정을 통과한 모델·Provider만 사용. 오디오·영상 합성 외부 서비스도 동일 |
| 감사 | 생성·삭제·내보내기·공유 이벤트 기록 (내용 본문은 감사 로그에 저장하지 않음) |
| 비밀 | 프롬프트·응답 로그에 키·토큰 저장 금지 |
| 산출물 지식화 | 산출물이 Source로 **자동 등록되지 않는다.** 메모→Source 변환처럼 사용자 명시 동작만 허용 |
| 선택 거버넌스 | 검토·승인·전달은 **후속 Phase 5**. 도입 후에도 조직 정책이 켜진 경우에만 메뉴 노출 |

### 10.1 daon-user 대비 거버넌스 단순화

| 기존 요구 | 새 설계 |
| --- | --- |
| 생성 전 설정 확정 필수 | 선택 |
| 모든 산출물 OutputVersion 승인 체계 | 조직 선택 기능 |
| RuleSet 강제 적용 | 조직이 RuleSet을 연결한 경우에만 생성 시 적용하고 결과에 준수 여부 경고 표시 |
| 승인 전 내보내기 제한 | 조직 정책으로 설정 |

---

## 11. 마이그레이션과 호환

1. 기존 `studio_outputs`/`OutputVersion` 데이터는 삭제하지 않는다.
2. 기존 유형 매핑: `evidence_report→report`, `comparison_table→data_table`, `knowledge_map→mind_map`, `slides/infographic/flashcards/quiz/audio/video→동일 신규 type_id`. `compliance_checklist`, `business_draft`는 `report`의 형식(`compliance`, `draft`)으로 흡수한다.
3. 기존 `generation_settings` 스냅샷은 `settings_json`으로 이관한다.
4. 새 번호 Alembic 마이그레이션은 **현재 실제 head를 확인한 뒤** 추가한다.
5. API는 `/studio/outputs` 신규 경로를 추가하고 기존 경로는 1 Release 동안 유지한 뒤 제거 여부를 결정한다.

---

## 12. 비기능 요구

| 항목 | 목표 (시간 항목은 가정치, 2026-10-20 결정: 수치 목표 없이 진행률 표시 중심, 목표는 WSL 실측 후 확정) |
| --- | --- |
| 생성 시작 지연 | 클릭 후 1초 이내 "생성 중" 카드 표시 (유지) |
| 텍스트형 완료 시간 | 보고서·표·카드·퀴즈·마인드맵 90초 이내(Source 중간 규모) |
| 슬라이드·인포그래픽 | 3분 이내 |
| 오디오 | 10분 이내(5~10분 분량 기준) |
| 동영상 | 20분 이내 |
| 동시 생성 | **사용자당 2건, 서비스 전체 4건**(2026-10-20 결정), 설정으로 조정 가능, 초과 시 큐 대기 |
| 복구 | Worker 비정상 종료 시 리스 만료 후 재시도(최대 2회), 이후 failed |
| 접근성 | 키보드 조작, 스크린리더 라벨, 색 대비 4.5:1 이상, 오디오 스크립트 제공 |
| 저장 용량 | 산출물 Asset은 Notebook 보존 정책과 함께 삭제 |
| i18n | 모든 UI 문구 L10N 키 사용(ko 기본) |

---

## 13. 단계별 구현 계획

각 단계는 독립 배포 가능해야 하며, 이전 단계의 API·모델을 깨지 않는다.

| 단계 | 내용 | 산출물 | 완료 기준 |
| --- | --- | --- | --- |
| Phase 0 | 기반 정비 | 새 `studio-model`·패널 골격, 유형 레지스트리, 생성기 인터페이스, Job 상태 확장, 마이그레이션 | 빈 타일 격자와 카드 목록이 기존 큐와 연결, 기존 산출물 조회 호환 |
| Phase 1 | 텍스트형 + 슬라이드 | 보고서·데이터 표·마인드맵·플래시카드·퀴즈·메모·**슬라이드 자료(PPTX)** + 채팅 "메모에 저장" | 7종 클릭 생성→카드 누적→뷰어→내보내기, 인용 이동, 실패·취소·재시도, PPTX가 PowerPoint에서 열림 |
| Phase 2 | 시각형 | 인포그래픽 (슬라이드는 Phase 1로 이동) | 렌더링 품질 기준 통과, 텍스트 넘침 검사 |
| Phase 3 | 오디오 | AI 오디오 오버뷰(대화형 2화자) | TTS 연동, 플레이어·스크립트 동기, 외부 전송 정책 준수 |
| Phase 4 | 동영상 | 동영상 개요 | 슬라이드+내레이션 합성, 챕터, MP4 내보내기 |
| Phase 5 | 확장 | 사용자 편집 고도화, 선택형 검토·승인·전달 재연결, 애널리틱스, Desktop 오프라인 유형, Mobile 최적화, 산출물별 추가 공유(필요 시) | 각각 별도 계획서 |

### 13.1 Phase 1 상세 작업 분해

1. UI: `studio-model`, 타일 격자, 카드, ⋮ 메뉴, 설정 대화상자, 상태 구독(SSE/폴링)
2. API: `/studio/types`, `/studio/outputs`, 취소·재생성·삭제
3. 생성기 6종 + 메모, 구조화 JSON 스키마, 검증기 (슬라이드 포함)
4. 뷰어 7종 (보고서·표·마인드맵·카드·퀴즈·슬라이드·메모)
5. 내보내기: DOCX·PPTX·PDF·XLSX·CSV·SVG·PNG·JSON·Markdown
6. 인용: 근거 참조 저장·이동
7. 부가 동작: 마인드맵 노드 질문(ST-A1), 학습 히스토리(ST-A2), 보고서 형식 선택(ST-A3) — §5.2
8. 테스트: 단위(스키마·검증기), 계약(API), 통합(큐·워커), E2E(클릭→카드→뷰어)

### 13.2 통합 실행 순서

작성형(§7A.9)의 Phase M0·M1·A1~A3는 이 표의 Phase와 다음 순서로 맞물린다.

| 순서 | 단계 | 비고 |
| --- | --- | --- |
| 1 | Phase 0 기반 정비 | daon-user 복사·rename(환경 문서 §8) 선행 |
| 2 | Phase 1 요약형 Studio (7종) **∥** Phase M0 가상 MCP·MCP 클라이언트 | 병행 가능, 서로 의존 없음 |
| 3 | Phase A1 RFP 대응 제안서 | Phase 1의 Studio 목록·뷰어·내보내기와 Phase M0의 가상 MCP 필요 |
| 4 | Phase A2 약관·계약서 | |
| 5 | Phase 2 인포그래픽 → Phase 3 오디오(로컬 TTS) → Phase 4 동영상 | 서버 GPU·메모리 확인 후(환경 문서 E7) |
| 6 | Phase A3 RuleSet 점검·템플릿 관리 UI, Phase 5 확장 | |
| 수시 | Phase M1 실서버 전환 | 요청 설계서 수용 순서대로 |

---

## 14. 검증 기준

### 14.1 기능 검수 시나리오 (Phase 1)

| ID | 시나리오 | 기대 결과 |
| --- | --- | --- |
| ST-T01 | Source 3개 선택 후 보고서 타일 클릭 | 1초 내 생성 중 카드, 완료 시 제목·부제(소스 3개) 표시 |
| ST-T02 | 생성 중 채팅 질문 | 채팅이 차단되지 않음 |
| ST-T03 | 연필 아이콘으로 형식·길이 변경 후 생성 | 변경한 설정이 부제·내용에 반영 |
| ST-T04 | Source 선택 0개 | 타일 비활성과 안내 |
| ST-T05 | 보고서 인용 번호 클릭 | 해당 Source 위치가 열림 |
| ST-T06 | 존재하지 않는 근거 참조를 모델이 반환 | 해당 문장 "근거 미확인" 표시 또는 생성 실패 |
| ST-T07 | 생성 중 취소 | 카드 취소 상태, 리소스 정리 |
| ST-T08 | Worker 강제 종료 | 리스 만료 후 재시도, 최종 failed 시 사유와 다시 시도 |
| ST-T09 | Source 새 버전 등록 | 산출물에 stale 배지 |
| ST-T10 | 채팅 답변 "메모에 저장" | 인용 포함 메모 생성 |
| ST-T11 | 퀴즈 풀이·제출 | 정오·해설·근거·점수 표시 |
| ST-T12 | 다운로드 | 형식별 파일이 열리고 제목·내용 일치 |
| ST-T13 | 권한 없는 사용자 접근 | 403, 목록에 노출되지 않음 |
| ST-T14 | 외부 전송 차단 정책 | 생성 거부와 정책 사유 표시 |
| ST-T15 | 새로고침 | 카드 목록 유지 |
| ST-T16 | 카드 ⋮ 메뉴 열기 | 기본 5항목이 지정된 순서로 표시, 생성 중 카드는 다운로드 비활성 |
| ST-T17 | 프롬프트 및 소스 보기 | 포커스 지시문·설정·Source 목록·근거 표시, 시스템 프롬프트 원문은 미노출 |
| ST-T18 | 노트북 맞춤설정 입력 후 생성 | 생성 결과와 "프롬프트 및 소스 보기"에 적용 표시, 기존 산출물은 변하지 않음 |
| ST-T19 | 채팅 기록 삭제 | 본인 채팅만 삭제, 메모·산출물 유지, 타 사용자 채팅 영향 없음 |
| ST-T20 | 노트북 복사 | 선택 범위(Source·메모·산출물)가 복제되고 새 Notebook 소유자로 권한 재설정 |
| ST-T21 | 산출물 공유 대화상자 | Notebook 권한 없는 대상은 추가 불가, 안내 표시, 공개 링크 없음 |
| ST-T22 | 슬라이드 자료 생성·PPTX 다운로드 | 슬라이드 뷰어 표시, PPTX가 PowerPoint에서 열리고 제목·불릿·인용이 일치 |
| ST-T23 | 마인드맵 노드 "이 개념으로 질문" | 채팅 입력창에 질문이 채워지고 노드 근거 Source가 범위로 지정, 자동 전송 없음 |
| ST-T24 | 플래시카드·퀴즈 학습 | 알아요/모르겠어요·점수 저장, "모르는 카드만/틀린 문항만" 모드, 본인에게만 보임 |
| ST-T25 | 보고서 형식 선택 | 요약·브리핑·블로그·스터디 가이드·사용자 정의 각각 형식 반영, 부제에 형식명 표시 |
| ST-T26 | 동시 생성 한도 | 사용자 3번째·서비스 5번째 요청은 큐 대기로 표시되고 순서대로 시작 |
| ST-T27 | 내보내기 인증 | 기본 설정에서 Step-up 없이 다운로드, 조직 정책 ON 시 추가 인증 요구 |

### 14.2 품질 평가

- 검수 방식(2026-10-20 결정): **합성 코퍼스 + 수동 평가**. 고정 시나리오(약관·제안서·RFP)를 만들어 사람이 근거 일치·요구사항 대응·미확인 표시를 점검하고, 기준선은 첫 평가 결과로 정한다.
- 근거 충실도: 표본 산출물에서 근거 문장 일치율(사람 평가)
- 환각 검사: 인용 없는 사실 문장 비율
- 사용성: 클릭 수(타일→결과 열람 ≤ 2), 첫 생성 성공률

### 14.3 자동 검증 항목

- 콘텐츠 JSON 스키마 검증, 인용 참조 무결성, 상태 전이 단위 테스트
- API 계약 테스트(OpenAPI 갱신)
- 접근성 자동 검사(대비·라벨), 모바일 폭 레이아웃 스냅샷

---

## 15. 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 오디오·영상 품질·비용 | Phase 3·4 일정·비용 | 텍스트형(Phase 1) 우선 배포, TTS·영상은 Provider 추상화 + 비용 한도 |
| 대용량 Source에서 지연·비용 | 사용성 저하 | map-reduce, 진행률 표시, 길이 상한·경고 |
| 환각·잘못된 인용 | 신뢰 하락 | 구조 검증·참조 무결성·미확인 표시 |
| 기존 Studio 데이터 호환 | 회귀 | 매핑 표(§11)·읽기 호환 테스트 |
| 외부 모델 전송 정책 | 규정 위반 | 기존 egress 정책 재사용, 생성 전 판정 |
| 범위 확대 | 일정 지연 | 단계별 완료 기준 고정, 거버넌스 기능은 Phase 5로 분리 |
| 이전 프로젝트의 과도한 절차 | 같은 실패 반복 | 핵심 경로에서 승인·설정 필수화 금지(P1, P7) |

---

## 16. 열린 질문

| # | 질문 | 영향 |
| --- | --- | --- |
| 1 | **[해소 · 부록 D]** Daon2-User는 daon-user 저장소를 이어서 쓰는가, 별도 저장소로 이식하는가? | 마이그레이션(§11) 전제 |
| 2 | **[해소 · 부록 D]** 생성에 사용할 모델은 기존 Provider 라우터(클라우드/로컬)만 쓰는가? 오디오(TTS)·영상·이미지 생성은 어떤 Provider를 쓰는가? | Phase 2~4 설계 |
| 3 | **[해소 · 부록 D]** 로컬(Desktop) 오프라인 환경에서 지원할 유형 범위는? | Phase 5 |
| 4 | **[해소 · 부록 D]** 산출물 공유 범위는 Notebook 공유와 동일한가, 산출물별 공개 링크가 필요한가? | §10 |
| 5 | **[해소 · 부록 D]** 검토·승인·전달은 기존 조직 요구가 남아 있는가? 남는다면 어떤 고객·조직이 쓰는가? | Phase 5 우선순위 |
| 6 | **[해소 · 부록 D]** 내보내기에 기존 Step-up 인증·Idempotency 요구를 유지하는가? | UX 마찰 |
| 7 | **[부분 해소 · 부록 D]** 생성 시간·품질 목표 수치(§12, §14.2) 확정 | 검수 기준 |
| 8 | **[해소 · 부록 D]** NotebookLM 화면에 없는 동작(오디오 대화형 개입, 마인드맵 노드 확장 등)을 포함할 것인가? | 범위 |
| 9 | **[해소 · 부록 D]** 동시 생성 한도(사용자당 2·전체 4), 일일 한도·과금은 1차 없음 | 운영 |
| 10 | **[해소 · 부록 D]** 노트북 맞춤설정이 채팅과 Studio에 모두 적용되는 것으로 추정했다. 이 추정이 맞는가? | §6.8.1 |
| 11 | **[해소 · 부록 D]** 노트북 복사 시 산출물·Asset을 포함할 것인가, Source만 복사할 것인가? | §6.8.1, 저장 용량 |
| 12 | **[해소 · 부록 D]** 애널리틱스의 범위(Studio 한정인가, Notebook 전체인가)와 열람 권한 | §6.8.1 |
| 13 | **[해소 · 부록 D]** **가상 MCP로 개발을 진행하고 Daon2-RAG·Daon2에 요청한다**(결정됨). 요청 설계서의 수용 여부·일정 확인 | §7A.10, 요청 설계서 |
| 13-1 | Daon2-RAG 서버가 Daon2-User를 호출자로 인식하는 방법(서비스 신원·audience 발급, 허용 project·work package 쌍 등록) — 요청 설계서 R-RAG-08 | §7A.8, Phase M0 |
| 14 | **[해소 · 부록 D]** 작성형(Authoring) A1을 요약형 Phase 2(슬라이드·인포그래픽)보다 먼저 구현할 것인가? | §7A.9 일정 |
| 15 | **[해소 · 부록 D]** 첫 작성 템플릿은 약관·제안서·계약서 중 무엇부터인가? 각 템플릿의 필수 입력·점검 규칙은 누가 정의하는가(Daon2 전문가 vs 조직)? | §7A.5.1 |
| 16 | **[해소 · 부록 D]** 작성 결과를 Daon2·Daon2-RAG에 지식으로 재등록하는 요구가 있는가? | §7A.6, Phase 5 |
| 17 | 지식 서버(Daon2·Daon2-RAG) 호출 시 사용자 권한을 전달하는 방식(위임 토큰 vs 서비스 계정 + 범위 필터). **수신측 회신 대기**, 그동안 가상 서버는 서비스 계정 + 범위 필터로 시험 | §7A.8 |
| 18 | **[해소 · 부록 D]** RFP 템플릿에서 제안 주체 정보·가격·일정이 없을 때 "미정"으로 두고 초안 생성을 허용하는가? 슬라이드(PPTX) 본문은 DOCX와 같은 내용 요약인가, 별도 구성인가? | §7A.5.1 |
| 19 | **[해소 · 부록 D]** RFP 문서의 요구사항 추출 정확도 목표와, 추출 결과를 사용자가 수정·확정하는 단계가 필요한가? | §7A.5.3~4 |

**남은 열린 질문**: 7(수치 확정은 실측 후), 13-1·17(MCP 사용자 권한, 수신측 회신 대기). 8(부가 동작)과 9(일일 한도·과금)는 2026-10-20 인터뷰로 해소되었다.

---

## 부록 A. 용어

| 용어 | 정의 |
| --- | --- |
| Studio | Notebook 오른쪽 산출물 생성·보관 패널 |
| 산출물(Output) | Studio에서 생성된 결과 한 건 (메모 포함) |
| Revision | 산출물의 저장 시점 콘텐츠. 저장 후 불변 |
| 타일 | 산출물 유형을 시작하는 버튼 |
| 카드 | Studio 목록의 산출물 한 줄 항목 |
| 근거 참조(EvidenceRef) | 산출물 내용과 Source 위치를 잇는 연결 |
| stale | 사용한 Source가 이후 변경되어 최신이 아닐 수 있음을 나타내는 상태 |

---

## 부록 B. 기존 요소 대응표

| 기존 daon-user 요소 | 새 Studio 처리 |
| --- | --- |
| `OUTPUT_TYPES` 11종 | 9종 + 메모, 신규 `type_id` (§11 매핑) |
| `REQUIRED_SETTINGS` | 폐기. 선택 설정 (§6.3) |
| `confirmGenerationSettings` | 폐기 |
| `GenerationSettingsSnapshot` | 기본값 포함 자동 스냅샷으로 대체 |
| `studio-workflow-*` (검토·승인·전달) | 후속 Phase 5에서 선택 기능으로 재연결 (§10.1), 1차 UI 미표시 |
| `StudioGenerationQueue/Worker` | 유지·확장 |
| `studio_export.py` | 형식 추가 |
| 기존 Release 2·3 후속 산출물 | 슬라이드 Phase 1, 인포그래픽 Phase 2, 오디오 Phase 3, 동영상 Phase 4로 재배치 |

---

## 부록 C. 개발·테스트 환경

| 항목 | 내용 |
| --- | --- |
| 개발 | 로컬(Windows) 작업 트리 |
| 개발 저장소 | `git@github-sinsan-develop:sinsan-develop/Daon2_User.git` |
| 테스트 배포 | WSL-server(`daon@172.27.253.53`) `~/deploy/daon2-user` |
| 같은 호스트의 연동 대상 | `daon2-rag-api`(MCP 서버), `daon2-api`, 기존 `daon_user-*` 컨테이너(웹 3330, 기존 daon-user QA) |
| 주의 | 기존 daon-user 컨테이너와 포트(3330 등)·DB·네트워크 이름이 겹치지 않게 분리한다. 호스트에서 이미 사용 중인 포트: 80/81/443, 2222, 3330, 5432, 5656, 6379, 8080, 8642, 8660, 8670, 9902, 11434 |
| 현재 상태 | `~/deploy/daon2-user` 디렉터리는 2026-10-20 확인 시점에 **비어 있음** |

---

## 부록 D. 확정 결정 기록 (인터뷰)

| 일자 | 결정 | 근거·영향 | 관련 |
| --- | --- | --- | --- |
| 2026-10-20 | 첫 마일스톤은 **요약형 Studio**(§5)를 먼저 구현하고, 작성형(§7A)은 그 위에 얹는다. | Phase 1(텍스트형 6종) 완료 후 Phase A1 착수. MCP 기반(Phase M0·M1)은 Phase 1과 병행 가능 | §7A.9, §16-14 |
| 2026-10-20 | 첫 번째 작성 템플릿은 **RFP 대응 제안서 초안**(AU-S2). | 첫 템플릿의 필수 입력은 RFP 문서(Source)와 기존 제안서 지식. 요구사항 추출·대응표가 핵심 기능 | §7A.1, §7A.5.4, §16-15 |
| 2026-10-20 | 생성 LLM은 **daon-user의 Provider 라우터·egress 정책을 재사용**한다. | 신규 Provider 계층을 만들지 않음. 오디오·영상 합성 Provider는 별도 결정 | §10, §16-2 |
| 2026-10-20 | 코드는 **daon-user(Backup)를 새 저장소로 복사한 뒤 이름을 daon2-user로 일괄 변경(rename)** 하고 Studio를 교체한다. | rename은 첫 기능 개발 전 별도 커밋. Studio UI·모델은 새로 작성, Source·채팅·인용·API는 계승 | §4, 환경 문서 §8, §16-1 |
| 2026-10-20 | Daon2-RAG·Daon2의 MCP 연결은 미완이므로 **가상(Virtual) MCP로 계약을 정의하고 개발을 진행**한다. MCP 표준을 준수하고, 부족한 기능은 Daon2-RAG·Daon2에 **요청 설계서로 요청**한다. | §7A.10 가상 서버·계약 시험, 요청 설계서 `docs/requests/daon2-mcp-provider-request.md` | §7A, §16-13 |
| 2026-10-20 | 요약형 Studio **Phase 1은 텍스트형 + 슬라이드**(보고서·데이터 표·마인드맵·플래시카드·퀴즈·메모·슬라이드 자료). | 슬라이드(PPTX 생성·뷰어) 포함으로 Phase 1 범위 증가 | §5, §13 |
| 2026-10-20 | RFP 제안서 초안(AU-S2)의 필수 질문 입력: **대상 RFP 문서, 참고할 기존 제안서, 제안 주체·강점, 가격·일정**. | 요구 확인 대화(§7A.5.2)의 템플릿 입력. 아래 §7A.5.1 예시 반영 | §7A.5 |
| 2026-10-20 | 작성 결과 출력 형식은 **DOCX, PPTX**. (PDF·XLSX는 이번 선택에서 제외) | 요구사항 대응표는 DOCX 안에 표로 포함. 별도 XLSX는 후속 | §7A.6 |
| 2026-10-20 | RFP 템플릿 입력 중 **RFP 문서·기존 제안서는 필수, 제안 주체·강점과 가격·일정은 선택**(미정 허용, `[작성 필요]` 표시). | §7A.5.1 예시 반영 | §16-18 |
| 2026-10-20 | RFP 요구사항 목록은 **사용자가 확인·수정 후 확정**해야 초안 작성이 시작된다. | 계획 확인 단계(§7A.5.3)의 필수 항목 | §16-19 |
| 2026-10-20 | 작성 결과의 DOCX·PPTX는 **사용자가 생성 시 선택**(DOCX만/PPTX만/둘 다). PPTX는 발표 흐름에 맞춰 별도 구성. | 생성 설정에 출력 형식 선택 추가 | §7A.6 |
| 2026-10-20 | 오디오·동영상(Phase 3·4)의 음성·영상 합성은 **로컬(WSL) 오픈소스 TTS**를 사용한다. | 외부 전송 없음. 서버 GPU 유무 미확인(환경 문서 E7), 메모리 7.8 GiB 제약으로 모델 크기·동시성 검토 필요 | §7.6, §12, 환경 E7·E9 |
| 2026-10-20 | 산출물 공유 범위는 **Notebook 권한과 동일**하다. 산출물별 추가 공유·공개 링크는 두지 않는다. | §6.5.1 공유 대화상자는 현재 접근 가능 대상 안내와 링크 복사(Notebook 권한자 전용)만 제공. `PUT .../sharing` API는 후속 | §6.5.1, §10, §16-4 |
| 2026-10-20 | 노트북 복사는 **Source+메모+산출물**을 복사하고, 복사 시 포함 범위를 선택할 수 있다. | §6.8.1 복사 표 그대로, 산출물 Asset은 새 저장 키로 복제 | §6.8.1, §16-11 |
| 2026-10-20 | 애널리틱스는 **1차에서 제외**한다. | §6.8.1 메뉴 항목·`/analytics/studio` API는 후속 Phase. 메뉴에는 표시하지 않음 | §6.8.1, §16-12 |
| 2026-10-20 | 노트북 맞춤설정은 **채팅과 Studio 모두에 적용**한다. 이미 만든 산출물에는 소급하지 않는다. | §6.8.1 그대로. 작성형(Authoring)에서는 템플릿 지시와 충돌 시 템플릿 지시가 우선(아래 참고) | §6.8.1, §16-10 |
| 2026-10-20 | 동시 생성 한도: **사용자당 2개, 서비스 전체 4개**(설정으로 조정 가능). 초과는 큐 대기. | WSL-server 메모리 7.8 GiB 제약. §12 비기능 표 갱신 | §12, §16-9 |
| 2026-10-20 | 생성 시간은 **수치 목표 없이 진행률 표시·취소 보장 중심**으로 한다. 목표치는 WSL 실측 후 확정. | §12 시간 목표는 "가정치"에서 "실측 후 확정"으로 변경 | §12, §16-7 |
| 2026-10-20 | 품질 검수는 **합성 코퍼스 + 수동 평가**로 한다. | 약관·제안서·RFP 합성 문서의 고정 시나리오를 사람이 근거·항목 충족으로 점검. 기준선은 첫 평가 후 설정 | §14.2, §16-7 |
| 2026-10-20 | 검토·승인·전달 흐름은 **후속 Phase로 연기**한다. 1차에는 UI에서 숨기고 기존 데이터·API만 보존한다. | §6.5 추가 메뉴 "검토 요청/승인/전달"은 1차 미표시. Phase 5에서 조직 정책 기반 재연결 | §6.5, §10.1, §16-5 |
| 2026-10-20 | Desktop(Windows) 오프라인 Studio는 **후속 Phase**, 1차는 **Web만** 대상으로 한다. | Phase 1~A1은 Web. Desktop·Mobile은 Web 화면 재사용 방식으로 후속 | §6.9, §13, §16-3 |
| 2026-10-20 | 산출물 내보내기는 **기본적으로 추가 인증(Step-up) 없이** 허용하고, 민감 조직만 정책으로 활성화한다. Idempotency-Key는 유지한다. | §9 내보내기 API에서 Step-up 헤더는 조직 정책이 켜진 경우만 요구 | §9, §16-6 |
| 2026-10-20 | 작성 결과를 Daon2·Daon2-RAG에 **지식으로 재등록하는 기능은 현재 불필요**. MCP는 읽기 전용 유지. | 요청 설계서 §11과 일치. 후속 논의 | §7A.6, §16-16 |
| 2026-10-20 | 1차에 넣을 NotebookLM 부가 동작: **마인드맵 노드에서 질문, 플래시카드·퀴즈 학습 히스토리, 보고서 형식 선택(요약·브리핑·블로그 등)**. | §5.2에 명세 추가. 나머지(오디오 대화 개입 등)는 후속 | §5.2, §16-8 |
| 2026-10-20 | 일일 생성 수·비용 할당 정책은 **1차에 없음**. 외부 Provider 사용 시 기존 운영 한도 정책을 따른다. | §12 동시 생성 한도만 적용 | §16-9 |
| 2026-10-20 | Daon2-RAG·Daon2 MCP의 사용자 권한 전달 방식은 **미정**(수신측 회신 후 결정). 가상 서버는 서비스 계정 + 범위 필터 방식으로 시험한다. | 요청 R-RAG-08, R-D2-08 | §7A.8 |
| 2026-10-20 | 개발은 로컬, 테스트는 WSL-server `~/deploy/daon2-user` 배포. 원격은 `sinsan-develop/Daon2_User`. | 환경 문서 참조 | 환경 문서 |

> 기존 §16 열린 질문 중 위 결정으로 해소된 항목은 1, 2(LLM 부분), 13, 14, 15번이다(17번은 수신측 회신 대기, 18·19번 해소). 인터뷰 2차로 4(공유), 10(맞춤설정), 11(복사), 12(애널리틱스)도 해소되었다. 나머지는 인터뷰에서 계속 확정한다.
