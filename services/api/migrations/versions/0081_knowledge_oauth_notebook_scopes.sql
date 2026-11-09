-- 지식 Connector의 토큰 발급 방식과 노트북별 업무 패키지 선택(WO-K2). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0080'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'KNOWLEDGE_OAUTH_NOTEBOOK_SCOPES_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

ALTER TABLE public.knowledge_connectors DROP CONSTRAINT knowledge_connectors_auth_kind_check;
ALTER TABLE public.knowledge_connectors ADD CONSTRAINT knowledge_connectors_auth_kind_check
  CHECK (auth_kind IN ('bearer','none','oauth_client_credentials'));

CREATE TABLE public.notebook_knowledge_scopes (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  source_tenant_id text NOT NULL CHECK (length(source_tenant_id) BETWEEN 1 AND 256),
  project_id text NOT NULL CHECK (length(project_id) BETWEEN 1 AND 256),
  project_name text NOT NULL CHECK (length(project_name) BETWEEN 1 AND 512),
  work_package_id text NOT NULL CHECK (length(work_package_id) BETWEEN 1 AND 256),
  work_package_name text NOT NULL CHECK (length(work_package_name) BETWEEN 1 AND 512),
  selected_by text NOT NULL,
  selected_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id,project_id,work_package_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
ALTER TABLE public.notebook_knowledge_scopes OWNER TO daon_notebook_delete;
ALTER TABLE public.notebook_knowledge_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_knowledge_scopes FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_knowledge_scopes_scope ON public.notebook_knowledge_scopes
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
REVOKE ALL ON TABLE public.notebook_knowledge_scopes FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.notebook_knowledge_scopes TO daon_app;
