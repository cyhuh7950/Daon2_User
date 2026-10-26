-- 노트북·사용자별 모델/추론 수준 선택(요구 4)과 모델별 "확인된 추론 수준". DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0078'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'NOTEBOOK_MODEL_SELECTION_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

-- 관리자가 확인한 추론 수준만 사용자에게 열린다. 비어 있으면 "확인되지 않음"이라 모델 기본값만 쓴다.
ALTER TABLE public.system_provider_models
  ADD COLUMN confirmed_reasoning_levels text[] NOT NULL DEFAULT '{}'::text[]
  CHECK (confirmed_reasoning_levels <@ ARRAY['none','low','medium','high']::text[]);

CREATE TABLE public.notebook_model_selections (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  user_id text NOT NULL,
  connection_id text NOT NULL,
  model_id text NOT NULL CHECK (length(model_id) BETWEEN 1 AND 256),
  reasoning_level text CHECK (reasoning_level IN ('none','low','medium','high')),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id,user_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
ALTER TABLE public.notebook_model_selections OWNER TO daon_notebook_delete;
ALTER TABLE public.notebook_model_selections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_model_selections FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_model_selections_scope ON public.notebook_model_selections
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),''));
REVOKE ALL ON TABLE public.notebook_model_selections FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.notebook_model_selections TO daon_app;
