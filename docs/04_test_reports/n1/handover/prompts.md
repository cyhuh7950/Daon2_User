# WO-N1 인계 확인 질문 (계획서 §9)

매 인계 확인(NB1-H~NB4-H, NB5-H)에서 아래 질문을 **글자 그대로** 쓴다. 대화 요약이나 추가 설명을 주지 않는다. 결과는 `docs/04_test_reports/n1/handover/<단계>-<확인>.md`에 저장하고 `NOTEBOOK_WORK_CHECK.md`의 "인계 확인 기록"에 판정을 적는다.

## 공통 질문 Q1 (H-A, H-B)

```text
D:\Project\Daon2_User 의 WO-N1 작업을 이어받는다. 이 대화 밖의 정보 없이 저장소의 정본만 읽어라:
AGENTS.md, D:\Project\PMO\AGENTS.md, NOTEBOOK_WORK_PLAN.md, NOTEBOOK_WORK_CHECK.md, WORK_STATUS.md, 그리고 실제 Git 상태(git status, git branch -a, git worktree list, git log -5).
파일은 수정하지 마라. 한국어로 다음을 답하라.
1. 현재 단계와 마지막으로 완료([0])된 작업 단위 ID
2. 다음 작업 단위 ID와, 그 단위의 입력 자료·수정 범위·검수 기준 요약
3. 열린 브랜치·worktree, ysna 배포 커밋, 남은 미검증 항목
4. 다음 단위를 담당에게 맡기는 지시문(NOTEBOOK_WORK_PLAN.md §5 양식을 모두 채워서)
5. 신산님께 물어야 할 것이 있는지(있으면 무엇이 문서에 빠졌는지)
```

## 총괄 교체 질문 Q2 (H-C)

```text
당신은 D:\Project\Daon2_User WO-N1 작업의 새 총괄이다. 이전 총괄의 대화는 없다. 정본(AGENTS.md, D:\Project\PMO\AGENTS.md, NOTEBOOK_WORK_PLAN.md, NOTEBOOK_WORK_CHECK.md, WORK_STATUS.md)과 실제 Git 상태(git status, git branch -a, git worktree list, git ls-remote --heads origin, git log -5)만 보고 파일은 수정하지 말고 한국어로 답하라.
1. 진행 중([2]·[1])이거나 되돌려진 작업 단위가 있는가
2. 병합·배포·정리가 끝나지 않은 것이 있는가(브랜치, worktree, 태그, 임시 자원)
3. 다음에 담당에게 보낼 지시문(§5 양식)
4. 이미 끝나서 다시 하면 안 되는 일
5. 신산님께 알려야 할 대기 사항
```

## 실행 방법

| 확인 | 실행 |
| --- | --- |
| H-A 같은 도구 새 세션 | Claude Code의 새 컨텍스트(이 대화 기록이 없는 subagent)에 Q1을 그대로 준다 |
| H-B 다른 도구 | `codex exec --sandbox read-only -C D:\Project\Daon2_User "<Q1>"` — 실행 후 `git status`로 변경 없음을 확인한다 |
| H-C 총괄 교체 | Claude Code의 새 컨텍스트에 Q2를 그대로 준다 |

## 합격 기준

| 확인 | 기준 |
| --- | --- |
| H-A | 1~3이 CHECK 문서·WORK_STATUS·실제 Git과 일치. 4가 계획서의 다음 단위와 같은 단위이고 §5 양식 칸을 모두 채움. 5에서 문서 누락이 지적되면 불합격(문서를 고치고 다시 실행) |
| H-B | H-A와 같은 기준. 2의 단위 ID가 H-A와 같음. 파일 변경 없음 |
| H-C | 1·2가 실제 Git(브랜치·worktree·원격 브랜치·태그)과 일치. 3이 H-A의 4와 같은 단위. 4에 완료 단위를 다시 하라는 내용이 없음. 5가 CHECK 문서의 대기 사항과 같음 |
