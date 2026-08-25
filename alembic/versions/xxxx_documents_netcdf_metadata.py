"""Add file-integrity and structural-metadata columns to `documents`, for
the automated OGDP -> ERDDAP ingest pipeline registering L1/L2 NetCDF
output files (document_type='l1_output'/'l2_output').

Three nullable columns, populated only for those two document_types --
everything else on `documents` (certificates, etc.) leaves them null:

- file_hash: sha256 hex digest of the file at registration time. The
  gap this closes: nothing in OGDB currently lets anyone tell whether
  the file `file_reference` points at still matches what was last
  recorded, or has silently drifted (reprocessed, replaced, corrupted)
  since. Not a general dedup key -- reprocessing legitimately produces
  a new row with the same document_type and a different hash.

- file_size_bytes: cheap sanity check the pipeline can compare against
  before trusting a transfer completed correctly, without re-reading
  the whole file to re-hash it every time.

- netcdf_metadata (jsonb): the dimensions/global-attributes/variable
  list the ingest pipeline already extracts (ogdp.erddap.inspect_netcdf)
  on its way to generating an ERDDAP dataset fragment. Stored as a
  read-optimized mirror for the portal/gateway to query directly,
  rather than round-tripping to ERDDAP's own .das endpoint (or
  re-opening the file) every time someone wants to see what a mission's
  L1/L2 actually contains. This does not replace anything -- checked
  against dataset_processing_stages / erddap_pushes / documents before
  adding it, and none of the existing tables capture file-content
  structure, only process facts (package/QC/OG1/push-status).

No new table: `documents` (mission_id, document_type, file_reference)
is the already-established convention for "where is mission X's L1/L2
output" (see xxxx_dataset_processing_status.py's own docstring), so
these are attributes of that same row, not a parallel structure.

Deliberately not adding a unique constraint on (mission_id,
document_type) -- documents already accumulates rows over time
elsewhere in the schema (e.g. certificates), and dataset_processing_
stages/erddap_pushes both use the same "always append, latest row is
current" pattern rather than upsert-in-place. Consistent with that:
reprocessing a mission's L1 inserts a new documents row rather than
overwriting the old one, so the history isn't lost.

Revision ID: xxxx_documents_netcdf_metadata
Revises: xxxx_erddap_pushes
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "xxxx_documents_netcdf_metadata"
down_revision = "xxxx_erddap_pushes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_hash", sa.String(64)))
    op.add_column("documents", sa.Column("file_size_bytes", sa.BigInteger))
    op.add_column(
        "documents", sa.Column("netcdf_metadata", postgresql.JSONB)
    )


def downgrade() -> None:
    op.drop_column("documents", "netcdf_metadata")
    op.drop_column("documents", "file_size_bytes")
    op.drop_column("documents", "file_hash")
