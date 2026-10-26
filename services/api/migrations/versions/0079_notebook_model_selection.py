"""노트북·사용자별 모델/추론 수준 선택. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0079'
down_revision = '0078'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0079' THEN
        RAISE EXCEPTION 'NOTEBOOK_MODEL_SELECTION_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.notebook_model_selections)
        OR EXISTS(SELECT 1 FROM public.system_provider_models WHERE cardinality(confirmed_reasoning_levels)>0) THEN
        RAISE EXCEPTION 'NOTEBOOK_MODEL_SELECTION_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.notebook_model_selections;
    ALTER TABLE public.system_provider_models DROP COLUMN confirmed_reasoning_levels;
    """)
