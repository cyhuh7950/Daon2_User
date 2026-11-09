"""지식 Connector 토큰 발급 방식과 노트북별 업무 패키지 선택. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0081'
down_revision = '0080'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0081' THEN
        RAISE EXCEPTION 'KNOWLEDGE_OAUTH_NOTEBOOK_SCOPES_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.notebook_knowledge_scopes)
        OR EXISTS(SELECT 1 FROM public.knowledge_connectors WHERE auth_kind='oauth_client_credentials') THEN
        RAISE EXCEPTION 'KNOWLEDGE_OAUTH_NOTEBOOK_SCOPES_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.notebook_knowledge_scopes;
    ALTER TABLE public.knowledge_connectors DROP CONSTRAINT knowledge_connectors_auth_kind_check;
    ALTER TABLE public.knowledge_connectors ADD CONSTRAINT knowledge_connectors_auth_kind_check CHECK (auth_kind IN ('bearer','none'));
    """)
