#!/usr/bin/env bash
# daon-user의 모델 Provider 설정(연결·모델 목록·허용 모델·헬스 설정)과 자격 증명 암호 키를 daon2_user 로 가져온다.
# WSL ~/deploy/daon2-user 에서 실행. 비밀 값은 출력하지 않는다(행 수와 상태만 출력). 원본 DB는 읽기 전용.
# 전제: daon2_user 의 provider 테이블이 비어 있다(이미 값이 있으면 중단). 암호 키는 원본 키 파일을 그대로 복사한다.
set -euo pipefail
cd "$(dirname "$0")/../.."
OLD_ROOT=${OLD_ROOT:-$HOME/deploy/daon-user}
OLD_PG=${OLD_PG:-local-postgres}
OLD_DB=${OLD_DB:-daon_user}
NEW_PG=${NEW_PG:-daon2_user-postgres-1}
NEW_DB=${NEW_DB:-daon2_user}
NP() { docker exec -i "$NEW_PG" psql -U postgres -d "$NEW_DB" -v ON_ERROR_STOP=1 -qAt "$@"; }
OP() { docker exec -i "$OLD_PG" psql -U postgres -d "$OLD_DB" -v ON_ERROR_STOP=1 -qAt "$@"; }

existing=$(NP -c "SELECT (SELECT count(*) FROM system_provider_connections)+(SELECT count(*) FROM system_provider_models)")

# 1) 암호 키: 새 키는 보관하고 원본 키로 교체(새 DB에 암호화된 값이 아직 없다).
if ! cmp -s "$OLD_ROOT/secrets/provider_credential_key" secrets/provider_credential_key; then
  cp -p secrets/provider_credential_key secrets/provider_credential_key.pre-import
  install -m 600 "$OLD_ROOT/secrets/provider_credential_key" secrets/provider_credential_key
  echo "key: replaced with daon-user key (backup kept)"
else
  echo "key: already identical"
fi

# 2) 데이터 복사(데이터만, 트리거 비활성, 한 트랜잭션). 값은 파이프로만 이동한다.
#    system_provider_health_settings 는 마이그레이션이 기본 행을 만들므로 복사하지 않는다.
if [ "$existing" = "0" ]; then
  { echo "BEGIN;"; docker exec "$OLD_PG" pg_dump -U postgres -d "$OLD_DB" --data-only --disable-triggers       -t system_provider_connections -t system_provider_models -t system_provider_allowed_models; echo "COMMIT;"; }     | docker exec -i "$NEW_PG" psql -U postgres -d "$NEW_DB" -v ON_ERROR_STOP=1 -q >/dev/null
else
  echo "provider rows already present ($existing); skipping copy"
fi
# 이전 시도가 중간에 실패해 FK 트리거가 꺼진 채 남았을 수 있다(준비 검사가 FK 트리거 활성을 요구한다).
for t in system_provider_connections system_provider_models system_provider_allowed_models; do NP -c "ALTER TABLE public.$t ENABLE TRIGGER ALL"; done
for t in system_provider_connections system_provider_models system_provider_allowed_models; do
  echo "$t: old=$(OP -c "SELECT count(*) FROM $t") new=$(NP -c "SELECT count(*) FROM $t")"
done

# 3) Workspace 기본 모델. 설정에 정의된 값(daon-user 의 workspace_model_defaults)을 그대로 가져오고, 임의로 덮어쓰지 않는다.
#    - 원본에 같은 Workspace 가 있으면 그 기본값(연결·모델)을 가져온다(예: Media Bridge uss/solar-pro4).
#    - 원본에 정의가 없는 Workspace/기능은 비워 둔다. 기본 모델은 소스·스크립트에 고정하지 않고 설정 화면(기본 모델 저장)에서 정한다.
#    문서 처리(Source 이해)는 기본 모델의 Provider 를 그대로 쓰며, 외부 Provider 는 Egress 정책(allow_approved_external)이 허용할 때만 원문을 받는다.
OP -F'|' -c "SELECT workspace_id,capability,connection_id,model_id FROM workspace_model_defaults" | while IFS='|' read -r ws cap conn model; do
  NP -v ws="$ws" -v cap="$cap" -v conn="$conn" -v model="$model" <<'SQL'
INSERT INTO workspace_model_defaults(tenant_id,workspace_id,capability,connection_id,model_id,version,updated_by,trace_id,policy_version)
SELECT w.tenant_id,w.workspace_id,:'cap',:'conn',:'model',1,'provider-import','provider-import','provider-import'
FROM workspaces w WHERE w.workspace_id=:'ws'
  AND EXISTS (SELECT 1 FROM system_provider_connections c WHERE c.connection_id=:'conn')
ON CONFLICT (tenant_id,workspace_id,capability) DO UPDATE SET connection_id=EXCLUDED.connection_id, model_id=EXCLUDED.model_id,
  version=workspace_model_defaults.version+1, updated_by='provider-import';
SQL
done
echo "workspace_model_defaults: new=$(NP -c 'SELECT count(*) FROM workspace_model_defaults')"
