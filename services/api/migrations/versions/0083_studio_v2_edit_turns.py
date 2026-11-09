"""완료 자료 대화 수정의 지시와 수정안. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0083'
down_revision = '0082'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0083' THEN
        RAISE EXCEPTION 'STUDIO_V2_EDIT_TURNS_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.studio_v2_edit_turns) THEN
        RAISE EXCEPTION 'STUDIO_V2_EDIT_TURNS_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.studio_v2_edit_turns;
    """)
