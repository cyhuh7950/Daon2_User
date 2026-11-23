"""노트북 개요·추천 질문(WO-N1 N1-4, NB2-F2). 노트북마다 1건, 워크스페이스 공유. 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0086'
down_revision = '0085'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0086' THEN
        RAISE EXCEPTION 'NOTEBOOK_OVERVIEWS_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.notebook_overviews) THEN
        RAISE EXCEPTION 'NOTEBOOK_OVERVIEWS_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.notebook_overviews;
    """)
