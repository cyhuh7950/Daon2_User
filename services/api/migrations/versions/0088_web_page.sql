-- WO-N8 웹 페이지 만들기: 스튜디오 산출물 유형 web_page 허용, 편집 턴 미리보기 칸.
ALTER TABLE public.studio_v2_outputs DROP CONSTRAINT studio_v2_outputs_type_id_check;
ALTER TABLE public.studio_v2_outputs ADD CONSTRAINT studio_v2_outputs_type_id_check
  CHECK (type_id IN ('report','data_table','mind_map','flashcards','quiz','slides','infographic','audio_overview','video_overview','memo','authored_document','web_page'));
ALTER TABLE public.studio_v2_edit_turns
  ADD COLUMN preview_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(preview_json)='object');
