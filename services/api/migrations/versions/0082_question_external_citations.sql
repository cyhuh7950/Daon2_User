-- 질문 답변에 인용된 외부 근거의 불변 스냅샷(WO-K3). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0081'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'QUESTION_EXTERNAL_CITATIONS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.question_external_citations (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  citation_id text NOT NULL CHECK (citation_id ~ '^extcit-[0-9a-f]{32}$'),
  run_result_id text NOT NULL,
  connector_id text NOT NULL,
  project_id text NOT NULL CHECK (length(project_id) BETWEEN 1 AND 256),
  project_name text NOT NULL CHECK (length(project_name) BETWEEN 1 AND 512),
  work_package_id text NOT NULL CHECK (length(work_package_id) BETWEEN 1 AND 256),
  work_package_name text NOT NULL CHECK (length(work_package_name) BETWEEN 1 AND 512),
  document_id text NOT NULL CHECK (length(document_id) BETWEEN 1 AND 256),
  document_version_id text NOT NULL CHECK (length(document_version_id) BETWEEN 1 AND 256),
  understanding_run_id text NOT NULL CHECK (length(understanding_run_id) BETWEEN 1 AND 256),
  block_id text NOT NULL CHECK (length(block_id) BETWEEN 1 AND 256),
  page integer NOT NULL CHECK (page>=1),
  document_name text CHECK (document_name IS NULL OR length(document_name) BETWEEN 1 AND 1024),
  body text NOT NULL CHECK (length(body) BETWEEN 1 AND 65536),
  body_sha256 text NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
  created_by text NOT NULL,
  retrieved_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,citation_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
CREATE INDEX question_external_citations_result_idx ON public.question_external_citations(tenant_id,workspace_id,run_result_id);
ALTER TABLE public.question_external_citations OWNER TO daon_notebook_delete;
ALTER TABLE public.question_external_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.question_external_citations FORCE ROW LEVEL SECURITY;
CREATE POLICY question_external_citations_scope ON public.question_external_citations
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
REVOKE ALL ON TABLE public.question_external_citations FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.question_external_citations TO daon_app;
