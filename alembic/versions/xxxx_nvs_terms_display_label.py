"""nvs_terms.display_label + generated nvs_terms.label.

The NVS ``skos:prefLabel`` is canonical but often unwieldy for a UI dropdown
or a NetCDF attribute -- e.g. "WET Labs {Sea-Bird WETLabs} ECO Puck
FLNTU-SLK fluorescence turbidity sensor". ``sync_nvs_terms.py`` refreshes
``pref_label`` from NVS on every run, so a hand-edit there doesn't survive.

- ``display_label`` (nullable) -- the facility's chosen short label. The
  sync script never writes it. Set it only where the NVS name is too long.
- ``label`` (generated, stored) -- ``COALESCE(display_label, pref_label)``.
  Everything user-facing (portal dropdowns/tables, the Slocum pipeline's
  generated deployment.yml -> NetCDF attrs) reads ``label``; ``pref_label``
  stays as the untouched NVS mirror for traceability.

Revision ID: xxxx_nvs_terms_display_label
Revises: xxxx_projects_acknowledgement
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "xxxx_nvs_terms_display_label"
down_revision = "xxxx_projects_acknowledgement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nvs_terms", sa.Column("display_label", sa.Text))
    op.add_column(
        "nvs_terms",
        sa.Column(
            "label", sa.Text,
            sa.Computed("COALESCE(display_label, pref_label)", persisted=True),
        ),
    )


def downgrade() -> None:
    op.drop_column("nvs_terms", "label")
    op.drop_column("nvs_terms", "display_label")
