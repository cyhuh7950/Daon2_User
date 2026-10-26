"""TTS 엔진 등록부. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0078'
down_revision = '0077'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0078' THEN
        RAISE EXCEPTION 'TTS_ENGINES_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.tts_engines) THEN
        RAISE EXCEPTION 'TTS_ENGINES_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.tts_engines;
    """)
