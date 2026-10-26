"""오디오 개요 자산 바이트 열. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0077'
down_revision = '0076'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0077' THEN
        RAISE EXCEPTION 'STUDIO_AUDIO_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.studio_v2_assets WHERE content IS NOT NULL) THEN
        RAISE EXCEPTION 'STUDIO_AUDIO_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    ALTER TABLE public.studio_v2_assets DROP COLUMN content;
    """)
