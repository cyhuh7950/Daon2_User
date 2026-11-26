-- WO-N9 데이터 집계: 스튜디오 산출물 유형 data_aggregation 허용.
ALTER TABLE public.studio_v2_outputs DROP CONSTRAINT studio_v2_outputs_type_id_check;
ALTER TABLE public.studio_v2_outputs ADD CONSTRAINT studio_v2_outputs_type_id_check
  CHECK (type_id IN ('report','data_table','mind_map','flashcards','quiz','slides','infographic','audio_overview','video_overview','memo','authored_document','web_page','data_aggregation'));
