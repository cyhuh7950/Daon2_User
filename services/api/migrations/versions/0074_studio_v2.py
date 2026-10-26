"""Studio v2 별도 테이블 집합. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0074'
down_revision = '0073'
branch_labels = None
depends_on = None

_TABLES = (
    'studio_v2_learning_attempts', 'studio_v2_jobs', 'studio_v2_assets', 'studio_v2_evidence',
    'studio_v2_sources', 'studio_v2_revisions', 'workspace_studio_v2_customization', 'studio_v2_outputs',
)


def upgrade():
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(
        Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    counts = ' + '.join(f'(SELECT count(*) FROM public.{t})' for t in _TABLES)
    drops = '\n'.join(f'    DROP TABLE public.{t};' for t in _TABLES)
    op.execute(f"""
    DO $$ BEGIN
      IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user)
        OR (SELECT count(*) FROM public.alembic_version)<>1
        OR (SELECT version_num FROM public.alembic_version)<>'0074' THEN
        RAISE EXCEPTION 'STUDIO_V2_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF ({counts})>0 THEN
        RAISE EXCEPTION 'STUDIO_V2_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
{drops}
    """)
