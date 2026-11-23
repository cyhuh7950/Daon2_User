# NB1-I1 답변 과정 통합 검수 (ysna, 2026-11-23)

- 환경: https://daon2-user.sinsan.kr, admin 워크스페이스, 시험 노트북 `QA-N1-I1 답변 과정 시험`(합성 약관·가입 안내 텍스트 소스 2개)
- 배포: a5b3ea1(리비전 0084) → 결함 수정 후 c59fd7f
- 모델: Media Bridge Server · uss/solar-pro4 (D-12)

| # | 점검 | 결과 |
| --- | --- | --- |
| 1 | 노트북·소스 2개 등록, ready | 통과 |
| 2 | 근거 있는 질문 → "답변 과정" 5단계(소스 2개, 근거 7개, 외부 전송 허용·가림·삭제, Media Bridge·uss/solar-pro4, 인용 4개 확인), 근거 클릭 → 해당 소스 원문 열림 | 통과 (`nb1-i1/answer-process-grounded.jpg`) |
| 3 | 근거 없는 질문 → 근거 부족 표시와 ⑤ "확인 필요" | 처음 2회 실패: TEXT_GENERATION_GROUNDING_INVALID(로그 reason=anchors_unsupported) → 결함 N1-B01 수정(c59fd7f) 후 통과 (`nb1-i1/answer-process-insufficient.jpg`) |
| 4 | 외부 전송 차단 | 미검증: 시험 워크스페이스 정책을 바꾸지 않음. 차단 상태 화면은 하네스 캡처(`nb1-u1/process-blocked.png`)와 단위 시험(details.process)으로 갈음 |
| 5 | 노트북 다시 열기 → 같은 과정(chat-history) | 통과 |
| 6 | DB: 최신 run_results.canonical_json에 process 키, 인용 4·allowed, 주소·IP·토큰 모양 문자열 없음 | 통과 |
| 7 | 정리 | 노트북 영구 삭제가 SOURCE_VERSION_DEPENDENCY_BLOCKED로 막힘(NB1-I2 결함 N1-B04 이전 코드가 만든 연결 안 된 v2 때문). 정리 대기 |

관찰: 브라우저 자동 입력에서 한글 입력 직후 Enter가 질문을 보내지 않는 경우가 있었음(자동화 입력 조합 문제로 판단, 버튼 전송은 정상). 사용자 실제 입력은 미확인.
