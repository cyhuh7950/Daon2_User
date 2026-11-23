-- 메모를 소스로 쓸 때의 메모-소스 연결(WO-N1 N1-3, 결정 D-10). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
-- 메모(studio_v2_outputs)에는 FK를 두지 않는다: 메모를 지워도 이미 만든 소스와 연결은 남긴다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0083'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'MEMO_SOURCE_LINKS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.memo_source_links (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  memo_output_id text NOT NULL CHECK (memo_output_id ~ '^sv2-[0-9a-f]{32}$'),
  source_id text NOT NULL,
  reflected_revision_no integer NOT NULL CHECK (reflected_revision_no>=1),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,memo_output_id),
  UNIQUE (tenant_id,workspace_id,source_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
CREATE INDEX memo_source_links_notebook_idx ON public.memo_source_links(tenant_id,workspace_id,notebook_id);

ALTER TABLE public.memo_source_links OWNER TO daon_notebook_delete;
ALTER TABLE public.memo_source_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memo_source_links FORCE ROW LEVEL SECURITY;
CREATE POLICY memo_source_links_scope ON public.memo_source_links
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
REVOKE ALL ON TABLE public.memo_source_links FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.memo_source_links TO daon_app;
