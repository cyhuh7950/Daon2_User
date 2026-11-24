// Provider 시험·저장 실패의 진단 한 줄. 서버가 error.details.provider에 실은 안전한 값만 보여 준다.
// 모양이 어긋난 값은 보여 주지 않는다(서버 검증과 같은 토큰 규칙).
const TOKEN = /^[A-Za-z0-9_.-]{1,64}$/u;
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$/u;

export function providerDiagnosticText(error) {
  const provider = error?.details?.provider;
  if (!provider || typeof provider !== "object") return "";
  const parts = [];
  if (typeof provider.model_id === "string" && MODEL_ID.test(provider.model_id)) parts.push(`실패한 모델: ${provider.model_id}`);
  const status = Number.isInteger(provider.upstream_status) && provider.upstream_status >= 400 && provider.upstream_status < 600
    ? provider.upstream_status : null;
  const reason = [provider.upstream_code, provider.upstream_param, provider.upstream_type]
    .find((value) => typeof value === "string" && TOKEN.test(value));
  if (status !== null) parts.push(`Provider 응답: HTTP ${status}${reason ? ` ${reason}` : ""}`);
  return parts.length ? ` ${parts.join(" · ")}` : "";
}
