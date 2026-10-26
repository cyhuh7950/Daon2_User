const DENY = Object.freeze({
  mode: "deny_external",
  allowed_provider_kinds: [],
  allowed_destinations: [],
  classification: "restricted",
  max_bytes: 0,
  masking_required: true,
  redaction_required: true,
  required_approver: "organization_admin",
});

// 정책 모드 3종: 외부 전송 차단 / 추가 인증 후 허용 / 추가 인증 없이 허용.
// 저장 형식은 mode(deny_external | allow_approved_external)와 required_approver("none" = 추가 인증 없음)이다.
export function policyChoice(policy) {
  if (policy.mode === "deny_external") return "deny_external";
  return policy.required_approver === "none" ? "allow_without_step_up" : "allow_with_step_up";
}

export function applyPolicyChoice(draft, choice) {
  if (choice === "deny_external") return createEgressPolicyDraft({ ...draft, mode: "deny_external", required_approver: draft.required_approver === "none" ? "organization_admin" : draft.required_approver });
  if (choice === "allow_without_step_up") return createEgressPolicyDraft({ ...draft, mode: "allow_approved_external", required_approver: "none" });
  return createEgressPolicyDraft({ ...draft, mode: "allow_approved_external", required_approver: draft.required_approver === "none" ? "organization_admin" : draft.required_approver });
}

export const POLICY_CHOICE_LABELS = Object.freeze({
  deny_external: "외부 전송 차단",
  allow_with_step_up: "추가 인증 후 허용",
  allow_without_step_up: "추가 인증 없이 허용",
});

export function createEgressPolicyDraft(overrides = {}) {
  return { ...DENY, ...overrides };
}

const INITIAL = Object.freeze({
  status: "idle", effective: null, draft: createEgressPolicyDraft(),
  canSave: false, errorCode: null,
});

function canSaveDraft(effective, draft) {
  const parentDenied = effective?.parent_locked === true
    && effective?.editable_scope !== "organization";
  const triesToRelax = draft.mode === "allow_approved_external";
  return !parentDenied || !triesToRelax;
}

export function egressPolicyReducer(state = INITIAL, action) {
  if (action.type === "context_loading") return {
    ...INITIAL, status: "loading", draft: createEgressPolicyDraft(),
  };
  if (action.type === "loading") return { ...state, status: "loading", errorCode: null };
  if (action.type === "loaded") {
    const scopePolicy = action.data.editable_scope === "organization"
      ? action.data.organization_policy
      : action.data.workspace_policy;
    const draft = createEgressPolicyDraft(scopePolicy || action.data);
    return {
      status: "ready", effective: action.data,
      draft, canSave: canSaveDraft(action.data, draft), errorCode: null,
    };
  }
  if (action.type === "drafted") {
    return {
      ...state, draft: action.draft,
      canSave: canSaveDraft(state.effective, action.draft), errorCode: null,
    };
  }
  if (action.type === "saving") return { ...state, status: "saving", errorCode: null };
  if (action.type === "failed") return { ...state, status: "error", errorCode: action.code };
  return state;
}
