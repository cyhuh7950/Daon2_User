"""데이터 집계(WO-N9). data_aggregation 유형 허용. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0089'
down_revision = '0088'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(
        Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
        OR (SELECT count(*) FROM public.alembic_version)<>1
        OR (SELECT version_num FROM public.alembic_version)<>'0089' THEN
        RAISE EXCEPTION 'DATA_AGGREGATION_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.studio_v2_outputs WHERE type_id='data_aggregation') THEN
        RAISE EXCEPTION 'DATA_AGGREGATION_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    ALTER TABLE public.studio_v2_outputs DROP CONSTRAINT studio_v2_outputs_type_id_check;
    ALTER TABLE public.studio_v2_outputs ADD CONSTRAINT studio_v2_outputs_type_id_check
      CHECK (type_id IN ('report','data_table','mind_map','flashcards','quiz','slides','infographic','audio_overview','video_overview','memo','authored_document','web_page'));
    """)
