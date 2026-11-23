"use client";
// 답변 과정(NB1-U1, WO-N1 N1-1). 서버가 준 answer_process.v1 블록의 값만 단계별로 보인다.
// 모델의 생각을 흉내 낸 문장은 만들지 않는다. 문구는 notebook-messages.ko.js의 notebook.process.* 키만 쓴다.
import { useId, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import "./answer-process.css";

const ORIGINS = new Set(["raw_source", "notebook_source", "daon_knowledge", "mcp_daon_rag", "mcp_law"]);
const DECISIONS = new Set(["allowed", "blocked", "not_needed"]);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value) => (typeof value === "string" && value.length > 0 ? value : null);
const count = (value) => (Number.isSafeInteger(value) && value >= 0 ? value : 0);

function Step({ name, title, emphasis = false, children }) {
  return (
    <li className="answer-process-step" data-step={name} data-emphasis={emphasis ? "true" : "false"}>
      <div className="answer-process-step-head">
        <strong>{msg(title)}</strong>
        {emphasis ? <span className="answer-process-attention">{msg("notebook.process.attention")}</span> : null}
      </div>
      <ul className="answer-process-facts">{children}</ul>
    </li>
  );
}

const Fact = ({ children }) => <li>{children}</li>;

function evidenceLabel(item) {
  const title = text(item.title) ?? msg("notebook.process.evidence.untitled");
  return Number.isSafeInteger(item.page) && item.page >= 1 ? `${title} · ${msg("notebook.process.evidence.page", { page: item.page })}` : title;
}

/**
 * 답변 아래(또는 외부 전송 차단 오류 카드 안)에 놓는 접힌 "답변 과정".
 * props
 * - process: answer_process.v1 블록 또는 null(과정 기록 없음)
 * - onOpenEvidence(event, item): 근거 항목을 눌렀을 때. 대화창은 Citation 클릭과 같은 함수로 잇는다
 * - canOpenEvidence(item): 열 수 있는 근거만 버튼으로 보인다(없으면 모두 글자)
 * - defaultExpanded: 처음부터 펼칠지(하네스용, 기본 false)
 */
export function AnswerProcess({ process, onOpenEvidence, canOpenEvidence, defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded === true);
  const panelId = useId();
  const block = isRecord(process) && process.version === 1 ? process : null;
  return (
    <section className="answer-process" data-process-state={processState(block)}>
      <button type="button" className="answer-process-toggle" aria-expanded={expanded ? "true" : "false"} aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}>
        {msg("notebook.process.toggle")}
      </button>
      {expanded ? (
        <div className="answer-process-panel" id={panelId}>
          {block ? <ProcessSteps block={block} onOpenEvidence={onOpenEvidence} canOpenEvidence={canOpenEvidence} />
            : <p className="answer-process-none">{msg("notebook.process.none")}</p>}
        </div>
      ) : null}
    </section>
  );
}

/** 하네스·시험이 쓰는 상태 이름: normal | insufficient | blocked | general | none */
export function processState(block) {
  if (!isRecord(block)) return "none";
  if (block.egress?.decision === "blocked") return "blocked";
  if (block.verification?.insufficient === true) return "insufficient";
  if (block.evidence === null) return "general";
  return "normal";
}

function ProcessSteps({ block, onOpenEvidence, canOpenEvidence }) {
  const scope = isRecord(block.scope) ? block.scope : {};
  const packages = Array.isArray(scope.knowledge_packages) ? scope.knowledge_packages.map((item) => text(item?.name)).filter(Boolean) : [];
  const tools = Array.isArray(scope.tools) ? scope.tools.map(text).filter(Boolean) : null;
  const evidence = isRecord(block.evidence) ? block.evidence : null;
  const selected = evidence && Array.isArray(evidence.selected) ? evidence.selected.filter(isRecord) : [];
  const egress = isRecord(block.egress) ? block.egress : {};
  const decision = DECISIONS.has(egress.decision) ? egress.decision : null;
  const model = isRecord(block.model) ? block.model : null;
  const verification = isRecord(block.verification) ? block.verification : null;
  const policy = text(egress.policy_ref);
  return (
    <ol className="answer-process-steps" aria-label={msg("notebook.process.list")}>
      <Step name="scope" title="notebook.process.step.scope">
        <Fact>{msg("notebook.process.scope.sources", { count: count(scope.source_count) })}</Fact>
        <Fact>{packages.length ? msg("notebook.process.scope.knowledge", { names: packages.join(", ") }) : msg("notebook.process.scope.knowledge_none")}</Fact>
        {/* tools가 null이면(도구 기능 전) 줄을 생략한다 */}
        {Array.isArray(scope.tools)
          ? <Fact>{tools.length ? msg("notebook.process.scope.tools", { names: tools.join(", ") }) : msg("notebook.process.scope.tools_none")}</Fact> : null}
      </Step>
      {evidence ? (
        <Step name="evidence" title="notebook.process.step.evidence">
          <Fact>{msg("notebook.process.evidence.searched", { count: count(evidence.searched) })}</Fact>
          <Fact>{msg("notebook.process.evidence.selected", { count: selected.length })}</Fact>
          {selected.length ? (
            <li className="answer-process-evidence">
              <ul>
                {selected.map((item, index) => {
                  const label = evidenceLabel(item);
                  const origin = ORIGINS.has(item.origin) ? msg(`notebook.process.origin.${item.origin}`) : null;
                  const openable = typeof onOpenEvidence === "function" && typeof canOpenEvidence === "function" && canOpenEvidence(item) === true;
                  return (
                    <li key={`${item.source_version_id ?? "none"}:${item.page ?? "none"}:${index}`}>
                      {openable ? (
                        <button type="button" className="answer-process-evidence-open" data-evidence={String(index)}
                          aria-label={msg("notebook.process.evidence.open", { title: label })}
                          onClick={(event) => onOpenEvidence(event, item)}>{label}</button>
                      ) : <span>{label}</span>}
                      {origin ? <span className="answer-process-origin">{origin}</span> : null}
                    </li>
                  );
                })}
              </ul>
            </li>
          ) : null}
        </Step>
      ) : null}
      <Step name="egress" title="notebook.process.step.egress" emphasis={decision === "blocked"}>
        {decision ? <Fact>{msg("notebook.process.egress.decision", { decision: msg(`notebook.process.egress.${decision}`) })}</Fact> : null}
        <Fact>{msg(egress.masked === true ? "notebook.process.egress.masked" : "notebook.process.egress.masked_none")}</Fact>
        <Fact>{msg(egress.redacted === true ? "notebook.process.egress.redacted" : "notebook.process.egress.redacted_none")}</Fact>
        {policy ? <Fact><span className="answer-process-muted">{msg("notebook.process.egress.policy", { ref: policy })}</span></Fact> : null}
      </Step>
      <Step name="model" title="notebook.process.step.model">
        {model ? <>
          {text(model.connection) ? <Fact>{msg("notebook.process.model.connection", { name: model.connection })}</Fact> : null}
          {text(model.model) ? <Fact>{msg("notebook.process.model.name", { name: model.model })}</Fact> : null}
          {text(model.reasoning) ? <Fact>{msg("notebook.process.model.reasoning", { level: model.reasoning })}</Fact> : null}
        </> : <Fact>{msg("notebook.process.model.not_called")}</Fact>}
      </Step>
      <Step name="verification" title="notebook.process.step.verification" emphasis={verification?.insufficient === true}>
        {verification ? <>
          <Fact>{msg("notebook.process.verification.citations", { count: count(verification.citations) })}</Fact>
          <Fact>{msg(verification.valid === false ? "notebook.process.verification.invalid" : "notebook.process.verification.valid")}</Fact>
          <Fact>{verification.insufficient === true
            ? <strong>{msg("notebook.process.verification.insufficient")}</strong> : msg("notebook.process.verification.sufficient")}</Fact>
          <Fact>{msg(verification.retried === true ? "notebook.process.verification.retried" : "notebook.process.verification.not_retried")}</Fact>
        </> : <Fact>{msg("notebook.process.verification.skipped")}</Fact>}
      </Step>
    </ol>
  );
}
