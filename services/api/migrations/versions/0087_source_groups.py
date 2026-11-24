"""소스 묶음(WO-N1 N1-5, NB3-F2). 노트북 공유(결정 D-11), 묶음은 화면 편의(질문 범위 계산 불변). 유자료 DB는 forward 보정만 한다."""
from pathlib import Path
from alembic import op

revision = '0087'
down_revision = '0086'
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
        OR (SELECT version_num FROM public.alembic_version)<>'0087' THEN
        RAISE EXCEPTION 'SOURCE_GROUPS_DOWN_PRECONDITION' USING ERRCODE='55000'; END IF;
      IF EXISTS(SELECT 1 FROM public.source_groups) OR EXISTS(SELECT 1 FROM public.source_group_members) THEN
        RAISE EXCEPTION 'SOURCE_GROUPS_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000'; END IF;
    END $$;
    DROP TABLE public.source_group_members;
    DROP TABLE public.source_groups;
    """)
