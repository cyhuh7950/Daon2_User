-- 노트북·사용자별 질문 도구 켜고 끄기(WO-N1 N1-2, 결정 D-02: 웹 도구 없음). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
-- enabled_json에는 사용자가 직접 바꾼 도구만 {"<도구 id>": true|false}로 남는다. 없는 도구는 기본값(켬)이고, 행이 없으면 지금까지와 같은 동작이다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0084'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'NOTEBOOK_QUESTION_TOOLS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.notebook_question_tools (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  actor_id text NOT NULL,
  enabled_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(enabled_json)='object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id,actor_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
ALTER TABLE public.notebook_question_tools OWNER TO daon_notebook_delete;
ALTER TABLE public.notebook_question_tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_question_tools FORCE ROW LEVEL SECURITY;
CREATE POLICY notebook_question_tools_scope ON public.notebook_question_tools
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND actor_id=nullif(current_setting('app.actor_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND actor_id=nullif(current_setting('app.actor_id',true),''));
REVOKE ALL ON TABLE public.notebook_question_tools FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.notebook_question_tools TO daon_app;
