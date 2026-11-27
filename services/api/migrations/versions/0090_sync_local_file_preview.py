"""Allow a metadata-only local file to enter the existing sync approval flow."""

from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None

_ITEM_TABLES = ("sync_preview_items", "sync_manifest_items")
_REGISTERED_VERSIONS = """
    (item_kind = 'source_version' AND source_version_id IS NOT NULL AND output_version_id IS NULL)
    OR (item_kind = 'output_version' AND source_version_id IS NULL AND output_version_id IS NOT NULL)
"""
_LOCAL_FILE = """
    OR (item_kind = 'local_file' AND source_version_id IS NULL AND output_version_id IS NULL
        AND base_cloud_version_id IS NULL AND base_cloud_digest IS NULL
        AND cardinality(dependency_item_ids) = 0
        AND byte_size BETWEEN 1 AND 524288
        AND content_type IN ('text/plain', 'text/markdown', 'application/pdf'))
"""


def _replace_item_constraints(*, local_files: bool) -> None:
    item_kinds = "'source_version', 'output_version'" + (", 'local_file'" if local_files else "")
    versions = _REGISTERED_VERSIONS + (_LOCAL_FILE if local_files else "")
    for table in _ITEM_TABLES:
        op.execute(f"""
            ALTER TABLE public.{table}
              DROP CONSTRAINT {table}_item_kind_check,
              DROP CONSTRAINT {table}_version_exact_one_check,
              ADD CONSTRAINT {table}_item_kind_check CHECK (item_kind IN ({item_kinds})),
              ADD CONSTRAINT {table}_version_exact_one_check CHECK ({versions});
        """)


def _replace_preview_trigger(*, local_files: bool) -> None:
    condition = "WHEN (NEW.item_kind <> 'local_file')" if local_files else ""
    op.execute(f"""
        DROP TRIGGER sync_preview_retention_inventory_lock ON public.sync_preview_items;
        CREATE TRIGGER sync_preview_retention_inventory_lock
          BEFORE INSERT ON public.sync_preview_items FOR EACH ROW {condition}
          EXECUTE FUNCTION public.lock_retention_source_inventory_mutation();
    """)


def upgrade() -> None:
    _replace_item_constraints(local_files=True)
    _replace_preview_trigger(local_files=True)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM public.sync_preview_items WHERE item_kind='local_file')
             OR EXISTS (SELECT 1 FROM public.sync_manifest_items WHERE item_kind='local_file') THEN
            RAISE EXCEPTION 'SYNC_LOCAL_FILE_FORWARD_RECOVERY_REQUIRED' USING ERRCODE='55000';
          END IF;
        END $$;
    """)
    _replace_item_constraints(local_files=False)
    _replace_preview_trigger(local_files=False)
