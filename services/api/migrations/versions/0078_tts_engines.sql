-- TTS 엔진 등록부(WO-F7T). API 키는 ProviderCredentialCipher(AES-GCM)로 암호화해 저장한다. DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0077'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'TTS_ENGINES_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.tts_engines (
  tenant_id text NOT NULL,
  engine_id text NOT NULL CHECK (engine_id ~ '^te-[0-9a-f]{32}$'),
  slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9_-]{0,31}$'),
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
  base_url text NOT NULL CHECK (length(base_url) BETWEEN 8 AND 2048),
  provider_kind text NOT NULL DEFAULT 'external_api' CHECK (provider_kind IN ('external_api','server_internal','local','local_runtime')),
  language text NOT NULL DEFAULT 'ko' CHECK (language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$'),
  timeout_seconds integer NOT NULL DEFAULT 120 CHECK (timeout_seconds BETWEEN 5 AND 600),
  voice_a text NOT NULL CHECK (voice_a ~ '^[A-Za-z0-9_.-]{1,40}$'),
  voice_b text NOT NULL CHECK (voice_b ~ '^[A-Za-z0-9_.-]{1,40}$'),
  voice_choices text[] NOT NULL DEFAULT '{}' CHECK (cardinality(voice_choices)<=64),
  credential_ciphertext bytea,
  credential_nonce bytea,
  credential_version integer NOT NULL DEFAULT 0 CHECK (credential_version>=0),
  encryption_key_version integer,
  status text NOT NULL DEFAULT 'unverified' CHECK (status IN ('unverified','verified','failed','disabled')),
  last_checked_at timestamptz,
  error_code text,
  is_default boolean NOT NULL DEFAULT false,
  version integer NOT NULL DEFAULT 1 CHECK (version>0),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,engine_id),
  UNIQUE (tenant_id,slug),
  CHECK ((credential_ciphertext IS NULL) = (credential_nonce IS NULL))
);
CREATE UNIQUE INDEX tts_engines_one_default_idx ON public.tts_engines(tenant_id) WHERE is_default;

ALTER TABLE public.tts_engines OWNER TO daon_app;
ALTER TABLE public.tts_engines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tts_engines FORCE ROW LEVEL SECURITY;
CREATE POLICY tts_engines_scope ON public.tts_engines
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),''));
REVOKE ALL ON TABLE public.tts_engines FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.tts_engines TO daon_app;
