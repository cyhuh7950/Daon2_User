#!/usr/bin/env bash
# 실행 중인 DB의 Provider 구성(연결·허용 모델·그 모델의 카탈로그 행)을 새 설치용 시드 SQL로 내보낸다.
# Key·암호문·확인 상태·검증 시각은 넣지 않는다(새 설치에서 관리자가 Key를 입력하고 연결 시험을 한다).
# 사용: bash deploy/daon2-user/seed/export-provider-seed.sh [DB컨테이너=daon2_user-postgres-1] > deploy/daon2-user/seed/provider-seed.sql
set -euo pipefail
PG=${1:-daon2_user-postgres-1}
q() { docker exec "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -qAt -c "$1"; }
echo "-- Provider 시드(Key 없음). deploy/daon2-user/seed/load-provider-seed.sh 가 비어 있는 DB에만 적용한다."
echo "BEGIN;"
q "SELECT format('INSERT INTO public.system_provider_connections (connection_id,provider_code,display_name,base_url,encrypted_credential,credential_nonce,encryption_key_version,credential_schema_version,credential_version,enabled,verification_status,verified_at,version,updated_by,trace_id,policy_version,access_mode,credential_requirement,short_code,adapter_type,provider_name,auto_model_id) VALUES (%L,%L,%L,%L,NULL,NULL,NULL,NULL,0,%L,%L,NULL,1,%L,%L,%L,%L,%L,%L,%L,%L,%L) ON CONFLICT (connection_id) DO NOTHING;',
  connection_id,provider_code,display_name,base_url,enabled,'unverified','seed','seed','seed',access_mode,credential_requirement,short_code,adapter_type,provider_name,auto_model_id)
  FROM public.system_provider_connections ORDER BY connection_id"
q "SELECT format('INSERT INTO public.system_provider_models (connection_id,model_id,reported_capabilities,effective_capabilities,override_applied,catalog_status,catalog_version,discovered_at,updated_by,catalog_origin,confirmed_reasoning_levels,reasoning_probed_at) VALUES (%L,%L,%L::text[],%L::text[],%L,%L,%L,NULL,%L,%L,%L::text[],NULL) ON CONFLICT (connection_id,model_id) DO NOTHING;',
  m.connection_id,m.model_id,m.reported_capabilities::text,m.effective_capabilities::text,m.override_applied,'stale',m.catalog_version,'seed',m.catalog_origin,'{}')
  FROM public.system_provider_models m
  WHERE EXISTS (SELECT 1 FROM public.system_provider_allowed_models a WHERE a.connection_id=m.connection_id AND a.model_id=m.model_id)
     OR EXISTS (SELECT 1 FROM public.system_provider_connections c WHERE c.connection_id=m.connection_id AND c.auto_model_id=m.model_id)
  ORDER BY m.connection_id,m.model_id"
q "SELECT format('INSERT INTO public.system_provider_allowed_models (connection_id,model_id,updated_by) VALUES (%L,%L,%L) ON CONFLICT DO NOTHING;', connection_id,model_id,'seed')
  FROM public.system_provider_allowed_models ORDER BY connection_id,model_id"
echo "COMMIT;"
