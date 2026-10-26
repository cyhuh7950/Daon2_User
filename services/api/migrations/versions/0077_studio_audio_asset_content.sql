-- 오디오 개요(WO-F7): 자산 바이트를 DB에 직접 보관한다(객체 저장소는 워커에 연결돼 있지 않다). 기존 행·정책은 바꾸지 않는다.
DO $precondition$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
    OR (SELECT count(*) FROM public.alembic_version)<>1
    OR (SELECT version_num FROM public.alembic_version)<>'0076'
    OR to_regclass('public.studio_v2_assets') IS NULL THEN
    RAISE EXCEPTION 'STUDIO_AUDIO_PRECONDITION' USING ERRCODE='55000';
  END IF;
END $precondition$;

ALTER TABLE public.studio_v2_assets
  ADD COLUMN content bytea CHECK (content IS NULL OR octet_length(content)<=33554432);
