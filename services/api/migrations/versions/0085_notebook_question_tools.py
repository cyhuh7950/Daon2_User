"""노트북·사용자별 질문 도구 켜고 끄기(WO-N1 N1-2). 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0085'
down_revision = '0084'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0085' THEN
        RAISE EXCEPTION 'NOTEBOOK_QUESTION_TOOLS_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.notebook_question_tools) THEN
        RAISE EXCEPTION 'NOTEBOOK_QUESTION_TOOLS_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.notebook_question_tools;
    """)
