"""노트북 복사 요청, 채팅 기록 비움, 조직 작성 템플릿, Connector 호출 한도. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0076'
down_revision = '0075'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0076' THEN
        RAISE EXCEPTION 'NOTEBOOK_COPY_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.notebook_copy_requests) OR EXISTS(SELECT 1 FROM public.notebook_chat_clears)
        OR EXISTS(SELECT 1 FROM public.authoring_templates) THEN
        RAISE EXCEPTION 'NOTEBOOK_COPY_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.notebook_copy_requests;
    DROP TABLE public.notebook_chat_clears;
    DROP TABLE public.authoring_templates;
    ALTER TABLE public.knowledge_connectors DROP COLUMN call_limits;
    """)
