-- 완료 자료 대화 수정의 지시와 수정안(WO-K5). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0082'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'STUDIO_V2_EDIT_TURNS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.studio_v2_edit_turns (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  turn_id text NOT NULL,
  output_id text NOT NULL,
  owner_actor_id text NOT NULL,
  job_id text NOT NULL,
  base_revision integer NOT NULL CHECK (base_revision>=1),
  instruction text NOT NULL CHECK (char_length(instruction) BETWEEN 1 AND 2000),
  state text NOT NULL CHECK (state IN ('queued','working','ready','no_change','failed','applied','discarded')),
  reply text,
  changes_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(changes_json)='array'),
  new_evidence_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(new_evidence_json)='array'),
  error_code text,
  applied_revision integer,
  idempotency_key_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,turn_id),
  UNIQUE (tenant_id,workspace_id,owner_actor_id,idempotency_key_sha256),
  FOREIGN KEY (tenant_id,workspace_id,output_id) REFERENCES public.studio_v2_outputs(tenant_id,workspace_id,output_id) ON DELETE CASCADE
);
CREATE INDEX studio_v2_edit_turns_output_idx ON public.studio_v2_edit_turns(tenant_id,workspace_id,output_id,created_at);
CREATE UNIQUE INDEX studio_v2_edit_turns_one_active ON public.studio_v2_edit_turns(tenant_id,workspace_id,output_id) WHERE state IN ('queued','working');

ALTER TABLE public.studio_v2_edit_turns OWNER TO daon_notebook_delete;
ALTER TABLE public.studio_v2_edit_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.studio_v2_edit_turns FORCE ROW LEVEL SECURITY;
CREATE POLICY studio_v2_edit_turns_scope ON public.studio_v2_edit_turns
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
REVOKE ALL ON TABLE public.studio_v2_edit_turns FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.studio_v2_edit_turns TO daon_app;
