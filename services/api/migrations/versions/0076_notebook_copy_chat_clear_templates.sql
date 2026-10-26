-- 노트북 복사 요청(멱등), 채팅 기록 비움 표시, 조직 작성 템플릿, Connector별 호출 한도. 기존 테이블의 데이터·함수는 바꾸지 않는다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0075'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls)
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_notebook_delete' AND rolinherit AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'NOTEBOOK_COPY_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

ALTER TABLE public.knowledge_connectors
  ADD COLUMN call_limits jsonb NOT NULL DEFAULT '{}'::jsonb
  CHECK (jsonb_typeof(call_limits)='object' AND octet_length(call_limits::text)<=1024);

CREATE TABLE public.notebook_copy_requests (
  tenant_id text NOT NULL, workspace_id text NOT NULL, actor_id text NOT NULL,
  idempotency_key_sha256 text NOT NULL CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{64}$'),
  request_fingerprint text NOT NULL,
  source_notebook_id text NOT NULL, new_notebook_id text NOT NULL,
  result_json jsonb NOT NULL CHECK (jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=8192),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,actor_id,idempotency_key_sha256)
);
ALTER TABLE public.notebook_copy_requests OWNER TO daon_app;
ALTER TABLE public.notebook_copy_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_copy_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_copy_requests_scope ON public.notebook_copy_requests
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND actor_id=nullif(current_setting('app.actor_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND actor_id=nullif(current_setting('app.actor_id',true),''));
REVOKE ALL ON TABLE public.notebook_copy_requests FROM PUBLIC;
GRANT SELECT,INSERT ON public.notebook_copy_requests TO daon_app;

CREATE TABLE public.notebook_chat_clears (
  tenant_id text NOT NULL, workspace_id text NOT NULL, notebook_id text NOT NULL, user_id text NOT NULL,
  cleared_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id,user_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
ALTER TABLE public.notebook_chat_clears OWNER TO daon_notebook_delete;
ALTER TABLE public.notebook_chat_clears ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_chat_clears FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_chat_clears_scope ON public.notebook_chat_clears
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),''));
REVOKE ALL ON TABLE public.notebook_chat_clears FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.notebook_chat_clears TO daon_app;

CREATE TABLE public.authoring_templates (
  tenant_id text NOT NULL,
  template_id text NOT NULL CHECK (template_id ~ '^org_[a-z0-9_]{1,60}$'),
  version integer NOT NULL CHECK (version>0),
  definition_json jsonb NOT NULL CHECK (jsonb_typeof(definition_json)='object' AND octet_length(definition_json::text)<=65536),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,template_id,version)
);
ALTER TABLE public.authoring_templates OWNER TO daon_app;
ALTER TABLE public.authoring_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.authoring_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY authoring_templates_scope ON public.authoring_templates
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),''));
CREATE POLICY authoring_templates_worker ON public.authoring_templates FOR SELECT
  USING (current_setting('app.capability',true)='studio_v2.worker');
REVOKE ALL ON TABLE public.authoring_templates FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.authoring_templates TO daon_app;
