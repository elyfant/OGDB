"""documents.battery_model_id: safety data sheets per battery model.

A safety data sheet (SDS) is published by the manufacturer per product, so
it belongs to a battery MODEL (battery_models), not to an individual pack
(an asset) -- every pack of a model shares it.

documents already attaches files to different owners through one nullable
FK column each (asset_id, mission_id, service_event_id, fault_id,
rma_event_id) and the ck_documents_has_owner check. battery_model_id is the
6th owner, same pattern as rma_event_id (xxxx_rma_tracking).

Why not a battery_models.sds_document_id pointer instead: that would make
a circular FK (documents -> battery_models -> documents), and could only
ever point at ONE file, so a manufacturer's revised SDS would orphan the
old one. With the owner on documents, every upload is a new row and the
current SDS is simply the latest document_type = 'safety_data_sheet' row
for the model -- the same "current = latest" convention as
current_asset_status and current_battery_measurement. Superseded versions
stay on record (and on disk) for compliance.

No data changes here, and no rows are seeded: uploading a model's SDS is
normal data entry through the app.

Revision ID: xxxx_battery_model_safety_data_sheets
Revises: xxxx_best_files_latest_run_per_stage
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "xxxx_battery_model_safety_data_sheets"
down_revision = "xxxx_best_files_latest_run_per_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("battery_model_id", sa.Integer, sa.ForeignKey("battery_models.id")),
    )
    op.create_index("ix_documents_battery_model_id", "documents", ["battery_model_id"])
    op.drop_constraint("ck_documents_has_owner", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_has_owner",
        "documents",
        "asset_id is not null or mission_id is not null or service_event_id is not null "
        "or fault_id is not null or rma_event_id is not null or battery_model_id is not null",
    )


def downgrade() -> None:
    # Rows owned only by a battery model would violate the restored check,
    # so they go first. Their files stay on the storage volume (nothing in
    # a migration should touch it) -- re-upload after re-upgrading.
    op.execute("DELETE FROM documents WHERE battery_model_id IS NOT NULL")
    op.drop_constraint("ck_documents_has_owner", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_has_owner",
        "documents",
        "asset_id is not null or mission_id is not null or service_event_id is not null "
        "or fault_id is not null or rma_event_id is not null",
    )
    op.drop_index("ix_documents_battery_model_id", table_name="documents")
    op.drop_column("documents", "battery_model_id")
