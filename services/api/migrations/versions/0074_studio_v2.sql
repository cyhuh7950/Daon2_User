-- Studio v2: 별도 테이블 집합. 기존 canon/Studio 테이블과 DB 함수는 변경하지 않는다.
-- 소유자는 daon_notebook_delete(노트북 삭제 CASCADE가 앱 역할의 DELETE 권한 없이 동작), 앱 역할은 SELECT/INSERT/UPDATE만 가진다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0073'
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_app'
      AND NOT rolsuper AND NOT rolbypassrls)
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='daon_notebook_delete'
      AND rolinherit AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls)
    OR pg_catalog.pg_has_role('daon_app','daon_notebook_delete','MEMBER') THEN
    RAISE EXCEPTION 'STUDIO_V2_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

CREATE TABLE public.studio_v2_outputs (
  tenant_id text NOT NULL, workspace_id text NOT NULL,
  output_id text NOT NULL CHECK (output_id ~ '^sv2-[0-9a-f]{32}$'),
  notebook_id text NOT NULL, owner_actor_id text NOT NULL,
  type_id text NOT NULL CHECK (type_id IN ('report','data_table','mind_map','flashcards','quiz','slides','infographic','audio_overview','video_overview','memo','authored_document')),
  format_id text,
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
  status text NOT NULL CHECK (status IN ('queued','generating','completed','failed','cancelled')),
  error_code text,
  settings_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings_json)='object' AND octet_length(settings_json::text)<=16384),
  source_version_ids text[] NOT NULL DEFAULT '{}',
  current_revision integer NOT NULL DEFAULT 0 CHECK (current_revision>=0),
  idempotency_key_sha256 text NOT NULL CHECK (idempotency_key_sha256 ~ '^[0-9a-f]{64}$'),
  request_fingerprint text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  PRIMARY KEY (tenant_id,workspace_id,output_id),
  UNIQUE (tenant_id,workspace_id,owner_actor_id,idempotency_key_sha256),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);
CREATE INDEX studio_v2_outputs_notebook_idx ON public.studio_v2_outputs(tenant_id,workspace_id,notebook_id,created_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE public.studio_v2_revisions (
  tenant_id text NOT NULL, workspace_id text NOT NULL, output_id text NOT NULL,
  revision_no integer NOT NULL CHECK (revision_no>0),
  revision_type text NOT NULL CHECK (revision_type IN ('generated','user_edit','regenerated')),
  content_json jsonb NOT NULL CHECK (octet_length(content_json::text)<=2097152),
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  warnings_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  generated_with jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,output_id,revision_no),
  FOREIGN KEY (tenant_id,workspace_id,output_id) REFERENCES public.studio_v2_outputs(tenant_id,workspace_id,output_id) ON DELETE CASCADE
);

CREATE TABLE public.studio_v2_sources (
  tenant_id text NOT NULL, workspace_id text NOT NULL, output_id text NOT NULL,
  revision_no integer NOT NULL, source_version_id text NOT NULL,
  source_id text, content_digest_sha256 text,
  PRIMARY KEY (tenant_id,workspace_id,output_id,revision_no,source_version_id),
  FOREIGN KEY (tenant_id,workspace_id,output_id,revision_no) REFERENCES public.studio_v2_revisions(tenant_id,workspace_id,output_id,revision_no) ON DELETE CASCADE
);

CREATE TABLE public.studio_v2_evidence (
  tenant_id text NOT NULL, workspace_id text NOT NULL, output_id text NOT NULL,
  revision_no integer NOT NULL, ref_id text NOT NULL,
  source_version_id text, evidence_span_id text,
  locator_kind text, locator_value text, quote_sha256 text,
  origin text NOT NULL DEFAULT 'notebook_source' CHECK (origin IN ('notebook_source','mcp_daon_rag','mcp_daon','mcp_law')),
  external_ref jsonb,
  PRIMARY KEY (tenant_id,workspace_id,output_id,revision_no,ref_id),
  FOREIGN KEY (tenant_id,workspace_id,output_id,revision_no) REFERENCES public.studio_v2_revisions(tenant_id,workspace_id,output_id,revision_no) ON DELETE CASCADE
);

CREATE TABLE public.studio_v2_assets (
  tenant_id text NOT NULL, workspace_id text NOT NULL, output_id text NOT NULL,
  asset_id text NOT NULL,
  revision_no integer NOT NULL,
  kind text NOT NULL CHECK (kind IN ('docx','pdf','xlsx','csv','md','txt','json','svg','png','pptx','mp3','wav','mp4')),
  object_key text NOT NULL, bytes bigint NOT NULL CHECK (bytes>=0), sha256 text NOT NULL,
  duration_ms integer, content_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  cleaned_at timestamptz,
  PRIMARY KEY (tenant_id,workspace_id,output_id,asset_id),
  UNIQUE (tenant_id,workspace_id,output_id,revision_no,kind),
  FOREIGN KEY (tenant_id,workspace_id,output_id) REFERENCES public.studio_v2_outputs(tenant_id,workspace_id,output_id) ON DELETE CASCADE
);

CREATE TABLE public.studio_v2_jobs (
  tenant_id text NOT NULL, workspace_id text NOT NULL, job_id text NOT NULL,
  output_id text NOT NULL, owner_actor_id text NOT NULL,
  state text NOT NULL CHECK (state IN ('queued','leased','generating','completed','failed','cancelled')),
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt>=0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
  lease_owner text, lease_until timestamptz,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  cancel_requested boolean NOT NULL DEFAULT false,
  progress_pct smallint NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
  progress_note text, safe_error_code text,
  request_json jsonb NOT NULL CHECK (jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=65536),
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  PRIMARY KEY (tenant_id,workspace_id,job_id),
  CHECK ((state IN ('leased','generating')) = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)),
  FOREIGN KEY (tenant_id,workspace_id,output_id) REFERENCES public.studio_v2_outputs(tenant_id,workspace_id,output_id) ON DELETE CASCADE
);
CREATE INDEX studio_v2_jobs_active_idx ON public.studio_v2_jobs(next_attempt_at) WHERE state IN ('queued','leased','generating');

CREATE TABLE public.studio_v2_learning_attempts (
  tenant_id text NOT NULL, workspace_id text NOT NULL, attempt_id text NOT NULL,
  output_id text NOT NULL, revision_no integer NOT NULL, user_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('flashcard','quiz')),
  payload_json jsonb NOT NULL CHECK (octet_length(payload_json::text)<=65536),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,attempt_id),
  FOREIGN KEY (tenant_id,workspace_id,output_id) REFERENCES public.studio_v2_outputs(tenant_id,workspace_id,output_id) ON DELETE CASCADE
);

CREATE TABLE public.workspace_studio_v2_customization (
  tenant_id text NOT NULL, workspace_id text NOT NULL, notebook_id text NOT NULL,
  instruction text NOT NULL DEFAULT '' CHECK (length(instruction)<=4000),
  version integer NOT NULL DEFAULT 1 CHECK (version>0),
  updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,workspace_id,notebook_id),
  FOREIGN KEY (tenant_id,workspace_id,notebook_id) REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE
);

DO $acl$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['studio_v2_outputs','studio_v2_revisions','studio_v2_sources','studio_v2_evidence','studio_v2_assets','studio_v2_jobs','studio_v2_learning_attempts','workspace_studio_v2_customization'] LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO daon_notebook_delete', t);
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
    IF t = 'studio_v2_learning_attempts' THEN
      EXECUTE format($p$CREATE POLICY %I ON public.%I USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'') AND user_id=nullif(current_setting('app.actor_id',true),''))$p$, t||'_scope', t);
    ELSE
      EXECUTE format($p$CREATE POLICY %I ON public.%I USING (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),'')) WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))$p$, t||'_scope', t);
    END IF;
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', t);
  END LOOP;
END $acl$;

-- 워커(큐 claim·sweeper·자산 정리)는 테넌트를 모른 채 시작한다. 워커 전용 capability에만 교차 범위 정책을 연다.
CREATE POLICY studio_v2_jobs_worker ON public.studio_v2_jobs
  USING (current_setting('app.capability',true)='studio_v2.worker')
  WITH CHECK (current_setting('app.capability',true)='studio_v2.worker');
CREATE POLICY studio_v2_outputs_worker ON public.studio_v2_outputs FOR SELECT
  USING (current_setting('app.capability',true)='studio_v2.worker');
CREATE POLICY studio_v2_assets_worker ON public.studio_v2_assets
  USING (current_setting('app.capability',true)='studio_v2.worker')
  WITH CHECK (current_setting('app.capability',true)='studio_v2.worker');

GRANT SELECT,INSERT,UPDATE ON public.studio_v2_outputs, public.studio_v2_jobs, public.workspace_studio_v2_customization, public.studio_v2_assets TO daon_app;
GRANT SELECT,INSERT ON public.studio_v2_revisions, public.studio_v2_sources, public.studio_v2_evidence, public.studio_v2_learning_attempts TO daon_app;
