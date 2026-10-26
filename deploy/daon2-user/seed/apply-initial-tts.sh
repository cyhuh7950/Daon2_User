#!/usr/bin/env bash
# 새 설치의 초기 음성(TTS) 엔진을 등록한다(앱이 한 번 기동해 admin 조직이 만들어진 뒤). 멱등.
# Key 는 넣지 않는다 — 관리자가 설정 → 음성 엔진에서 Key 를 입력하고 연결 확인을 한다.
# 이미 화면 등록 엔진이 있거나 배포 설정 파일(DAON_TTS_CONFIG_FILE)에 엔진이 있으면 건드리지 않는다(화면 등록이 파일을 덮어쓰므로 Key 없는 행이 동작 중인 엔진을 깨지 않게).
# 값은 환경변수로 바꾼다: SEED_TTS_SLUG, SEED_TTS_LABEL, SEED_TTS_BASE_URL, SEED_TTS_VOICE_A, SEED_TTS_VOICE_B, SEED_TTS_VOICE_CHOICES(쉼표)
# 사용: bash deploy/daon2-user/seed/apply-initial-tts.sh [tenant=admin] [DB컨테이너] [API컨테이너]
set -uo pipefail
cd "$(dirname "$0")/../../.."
TENANT=${1:-admin}; PG=${2:-daon2_user-postgres-1}; API=${3:-daon2_user-api-1}
SLUG=${SEED_TTS_SLUG:-supertonic}; LABEL=${SEED_TTS_LABEL:-Supertonic}
URL=${SEED_TTS_BASE_URL:-https://tts.supertonic.sinsan.kr}
VA=${SEED_TTS_VOICE_A:-F1}; VB=${SEED_TTS_VOICE_B:-M1}
CHOICES=${SEED_TTS_VOICE_CHOICES:-F1,F2,F3,F4,F5,M1,M2,M3,M4,M5}
DB=${DAON_DB_NAME:-daon2_user}
psql_q() { docker exec -i "$PG" psql -U postgres -d "$DB" -qAt "$@"; }

HAS_FILE=$(docker exec "$API" python -c "import os,json;p=os.environ.get('DAON_TTS_CONFIG_FILE','');print(len(json.load(open(p)).get('engines',[])) if p and os.path.exists(p) else 0)" 2>/dev/null || echo 0)
if [ "${HAS_FILE:-0}" != 0 ]; then echo "음성 엔진: 배포 설정 파일에 엔진 ${HAS_FILE}개가 있어 시드하지 않습니다."; exit 0; fi
COUNT=$(psql_q -c "SELECT count(*) FROM public.tts_engines WHERE tenant_id='$TENANT'")
if [ "$COUNT" != 0 ]; then echo "음성 엔진: 이미 ${COUNT}개 등록되어 있어 시드하지 않습니다."; exit 0; fi
ARRAY="{$(echo "$CHOICES" | tr -d ' ')}"
psql_q -v ON_ERROR_STOP=1 \
  -v t="$TENANT" -v slug="$SLUG" -v label="$LABEL" -v url="$URL" -v va="$VA" -v vb="$VB" -v choices="$ARRAY" <<'SQL'
INSERT INTO public.tts_engines (tenant_id, engine_id, slug, label, base_url, provider_kind, language, timeout_seconds,
  voice_a, voice_b, voice_choices, status, is_default, created_by)
VALUES (:'t', 'te-' || md5(:'t' || ':' || :'slug'), :'slug', :'label', :'url', 'external_api', 'ko', 120,
  :'va', :'vb', :'choices'::text[], 'unverified', true, 'seed')
ON CONFLICT DO NOTHING;
SQL
echo "음성 엔진 시드: $SLUG ($URL) 등록 — 설정 → 음성 엔진에서 Key 를 입력하고 연결 확인을 하세요."
