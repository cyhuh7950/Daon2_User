"""지식 Connector(MCP) 등록부. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0075'
down_revision = '0074'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0075' THEN
        RAISE EXCEPTION 'KNOWLEDGE_CONNECTORS_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.knowledge_connectors) THEN
        RAISE EXCEPTION 'KNOWLEDGE_CONNECTORS_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.knowledge_connectors;
    """)
