-- 소스 묶음(WO-N1 N1-5, 결정 D-11 노트북 공유, 정정 C-4). 기존 데이터는 바꾸지 않는다. DB 함수·트리거 없음.
-- 같은 워크스페이스에서 노트북을 보는 모두가 같은 묶음을 본다(0074 studio_v2 일반 테이블과 같은 tenant·workspace 기준 RLS).
-- 정본 표(sources·source_versions·notebook_bindings·notebook_source_unbindings)에는 FK·권한 변경을 걸지 않는다.
-- 떼어지거나 삭제 요청된 소스의 묶음 행은 조회에서 숨길 뿐 지우지 않는다. 소스 하나는 노트북 안에서 묶음 하나에만 속한다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0086'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app' AND NOT rolsuper AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'SOURCE_GROUPS_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.source_groups (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  group_id text NOT NULL CHECK (group_id ~ '^sg-[0-9a-f]{32}$'),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  position integer NOT NULL CHECK (position>=0),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,group_id),
  UNIQUE (tenant_id,workspace_id,notebook_id,group_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
CREATE INDEX source_groups_notebook_idx ON public.source_groups(tenant_id,workspace_id,notebook_id,position);

CREATE TABLE public.source_group_members (
  tenant_id text NOT NULL,
  workspace_id text NOT NULL,
  notebook_id text NOT NULL,
  group_id text NOT NULL,
  source_id text NOT NULL,
  position integer NOT NULL CHECK (position>=0),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id,source_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id,group_id) REFERENCES public.source_groups(tenant_id,workspace_id,notebook_id,group_id) ON DELETE CASCADE
);
CREATE INDEX source_group_members_group_idx ON public.source_group_members(tenant_id,workspace_id,notebook_id,group_id,position);

ALTER TABLE public.source_groups OWNER TO daon_notebook_delete;
ALTER TABLE public.source_group_members OWNER TO daon_notebook_delete;
ALTER TABLE public.source_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_groups FORCE ROW LEVEL SECURITY;
ALTER TABLE public.source_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_group_members FORCE ROW LEVEL SECURITY;
CREATE POLICY source_groups_scope ON public.source_groups
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
CREATE POLICY source_group_members_scope ON public.source_group_members
  USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))
  WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''));
REVOKE ALL ON TABLE public.source_groups FROM PUBLIC;
REVOKE ALL ON TABLE public.source_group_members FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.source_groups, public.source_group_members TO daon_app;
