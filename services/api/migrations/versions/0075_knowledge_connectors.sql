-- 지식 Connector(MCP) 등록부. 토큰은 ProviderCredentialCipher(AES-GCM)로 암호화해 저장한다. DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0074'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'KNOWLEDGE_CONNECTORS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.knowledge_connectors (
  tenant_id text NOT NULL,
  connector_id text NOT NULL CHECK (connector_id ~ '^kc-[0-9a-f]{32}$'),
  kind text NOT NULL CHECK (kind IN ('daon2_rag','daon2','law')),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  endpoint_url text NOT NULL CHECK (length(endpoint_url) BETWEEN 8 AND 2048),
  protocol_version text,
  auth_kind text NOT NULL DEFAULT 'bearer' CHECK (auth_kind IN ('bearer','none')),
  credential_ciphertext bytea,
  credential_nonce bytea,
  credential_version integer NOT NULL DEFAULT 0 CHECK (credential_version>=0),
  encryption_key_version integer,
  allowed_tools text[] NOT NULL DEFAULT '{}',
  allowed_scopes jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(allowed_scopes)='array' AND octet_length(allowed_scopes::text)<=16384),
  is_virtual boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'unverified' CHECK (status IN ('unverified','verified','failed','disabled')),
  last_checked_at timestamptz,
  error_code text,
  version integer NOT NULL DEFAULT 1 CHECK (version>0),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,connector_id),
  CHECK ((credential_ciphertext IS NULL) = (credential_nonce IS NULL)),
  CHECK (auth_kind='none' OR credential_ciphertext IS NOT NULL)
);
CREATE INDEX knowledge_connectors_kind_idx ON public.knowledge_connectors(tenant_id,kind);

ALTER TABLE public.knowledge_connectors OWNER TO daon_app;
ALTER TABLE public.knowledge_connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_connectors FORCE ROW LEVEL SECURITY;
CREATE POLICY knowledge_connectors_scope ON public.knowledge_connectors
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),''));
REVOKE ALL ON TABLE public.knowledge_connectors FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.knowledge_connectors TO daon_app;
