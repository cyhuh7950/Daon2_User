-- 노트북 개요·추천 질문(WO-N1 N1-4, 결정 D-06, 정정 C-5). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
-- 노트북마다 1건이고 같은 워크스페이스 사용자가 함께 본다(0074 studio_v2 일반 테이블과 같은 tenant·workspace 기준 RLS).
-- 작업 잡기(queued → working)는 이 표에서만 FOR UPDATE SKIP LOCKED로 한다. 워커는 테넌트를 모른 채 시작하므로 전용 capability에만 교차 범위 정책을 연다.
-- source_fingerprint는 생성에 쓴 준비된 소스 버전 ID를 정렬해 이은 문자열의 SHA-256(소문자 16진 64자)이다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0085'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'NOTEBOOK_OVERVIEWS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.notebook_overviews (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','working','ready','failed','blocked')),
  summary text CHECK (summary IS NULL OR char_length(summary)<=4000),
  questions jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(questions)='array'),
  citations jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(citations)='array'),
  source_fingerprint text CHECK (source_fingerprint IS NULL OR source_fingerprint ~ '^[0-9a-f]{64}$'),
  model_ref text CHECK (model_ref IS NULL OR char_length(model_ref)<=300),
  safe_error_code text CHECK (safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{2,63}$'),
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt>=0),
  lease_until timestamptz,
  requested_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
CREATE INDEX notebook_overviews_pending_idx ON public.notebook_overviews(updated_at) WHERE state IN ('queued','working');
ALTER TABLE public.notebook_overviews OWNER TO daon_notebook_delete;
ALTER TABLE public.notebook_overviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_overviews FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_overviews_scope ON public.notebook_overviews
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
CREATE POLICY notebook_overviews_worker ON public.notebook_overviews
  USING (current_setting('app.capability',true)='notebook_overview.worker')
  WITH CHECK (current_setting('app.capability',true)='notebook_overview.worker');
REVOKE ALL ON TABLE public.notebook_overviews FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.notebook_overviews TO daon_app;
