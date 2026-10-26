-- 추론 수준을 실제 요청으로 확인한 시각. NULL이면 아직 확인하지 않은 모델이다(빈 확인값과 구별한다).
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0079' THEN
    RAISE EXCEPTION 'REASONING_PROBED_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

ALTER TABLE public.system_provider_models ADD COLUMN reasoning_probed_at timestamptz;
