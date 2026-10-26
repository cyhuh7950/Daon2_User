#!/usr/bin/env bash
# ysna-server 최초 준비(멱등): secrets 파일과 .env 를 만든다. 비밀번호·키는 출력하지 않는다.
# 같은 서버의 기존 ~/deploy/daon-user/.env 에서 Provider 키·SMTP·신뢰 프록시 IP 줄만 읽어 옮긴다(서버 밖으로 나가지 않는다).
# 사용: ~/deploy/daon2-user 에서  DAON_GATEWAY_URL=https://daon2-user.sinsan.kr bash deploy/daon2-user/ysna-bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
GATEWAY=${DAON_GATEWAY_URL:?DAON_GATEWAY_URL 이 필요합니다(예: https://daon2-user.sinsan.kr)}
OLD=${DAON_REFERENCE_ENV:-$HOME/deploy/daon-user/.env}
mkdir -p secrets && chmod 700 secrets
gen() { [ -s "secrets/$1" ] || { umask 077; openssl rand -hex "${2:-32}" > "secrets/$1"; chmod 600 "secrets/$1"; }; }
for name in db_app_password db_owner_password db_superuser_password object_access_key object_secret_key; do gen "$name" 24; done
for name in provider_credential_key recovery_manifest_key step_up_token_key; do gen "$name" 48; done
[ -s secrets/tts_engines.json ] || { umask 077; echo '{"engines": []}' > secrets/tts_engines.json; }

if [ ! -f .env ]; then
  umask 077
  APP_PW=$(cat secrets/db_app_password)
  {
    echo "COMPOSE_PROJECT_NAME=daon2_user"
    echo "DAON_WEB_HOST_PORT=${DAON_WEB_HOST_PORT:-3340}"
    echo "DAON_PUBLIC_GATEWAY_URL=$GATEWAY"
    echo "DAON_WEB_PUBLIC_GATEWAY_URL=$GATEWAY"
    echo "DAON_API_INTERNAL_URL=http://api:8000"
    echo "DAON_OBJECT_STORAGE_ENDPOINT=object-storage:9000"
    echo "DAON_OBJECT_STORAGE_BUCKET=daon2-user"
    echo "DAON_OBJECT_STORAGE_SECURE=false"
    echo "DAON_OBJECT_ACCESS_KEY_FILE=$ROOT/secrets/object_access_key"
    echo "DAON_OBJECT_SECRET_KEY_FILE=$ROOT/secrets/object_secret_key"
    echo "DAON_RECOVERY_MANIFEST_KEY_FILE=$ROOT/secrets/recovery_manifest_key"
    echo "DAON_STEP_UP_TOKEN_KEY_FILE=$ROOT/secrets/step_up_token_key"
    echo "DAON_PROVIDER_CREDENTIAL_KEY_FILE=$ROOT/secrets/provider_credential_key"
    echo "DAON_DB_SUPERUSER_PASSWORD_FILE=$ROOT/secrets/db_superuser_password"
    echo "DAON_TTS_ENGINES_FILE=$ROOT/secrets/tts_engines.json"
    echo "DAON_DB_ADMIN_HOST_PORT=5436"
    echo "DAON_DB_APP_ROLE=daon_app"
    echo "DAON_DB_EXPECTED_NAME=postgres"
    echo "DAON_CLOUD_DATABASE_DSN=postgresql://daon_app:${APP_PW}@postgres:5432/daon2_user"
    echo "DAON_ORGANIZATION_ADMIN_V2_ENABLED=true"
    echo "DAON_STUDIO_V2_ENABLED=true"
    echo "DAON_KNOWLEDGE_CONNECTORS_ENABLED=true"
    echo "DAON_NOTIFICATION_INBOX_ENABLED=true"
    echo "LLM_EXTERNAL_EGRESS_APPROVED=false"
    if [ -f "$OLD" ]; then
      grep -E '^(DAON_TRUSTED_PROXY_IPS|UPSTAGE_API_KEY|CEREBRAS_API_KEY|GROQ_API_KEY|MISTRAL_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|OPENROUTER_API_KEY|ANTHROPIC_API_KEY|OLLAMA_BASE_URL|DAON_SMTP_[A-Z]+|DAON_EMAIL_FROM)=' "$OLD" || true
    else
      echo "DAON_TRUSTED_PROXY_IPS=${DAON_TRUSTED_PROXY_IPS:?참조 .env 가 없으면 DAON_TRUSTED_PROXY_IPS 가 필요합니다}"
    fi
  } > .env
fi
echo "ysna-bootstrap 완료: secrets $(ls secrets | wc -l)개, .env 줄 $(wc -l < .env)개"
