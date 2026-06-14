"""Add E-Way Bill configurable settings to company_profiles.

- eway_enabled: Enable/disable E-Way Bill module
- eway_local_threshold: Intra-state E-Way threshold amount
- eway_interstate_threshold: Inter-state E-Way threshold amount
- eway_always_show_button: Always show button regardless of threshold
"""

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        "company_profiles",
        sa.Column(
            "eway_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "company_profiles",
        sa.Column(
            "eway_local_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("100000"),
        ),
    )
    op.add_column(
        "company_profiles",
        sa.Column(
            "eway_interstate_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("50000"),
        ),
    )
    op.add_column(
        "company_profiles",
        sa.Column(
            "eway_always_show_button",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade():
    op.drop_column("company_profiles", "eway_always_show_button")
    op.drop_column("company_profiles", "eway_interstate_threshold")
    op.drop_column("company_profiles", "eway_local_threshold")
    op.drop_column("company_profiles", "eway_enabled")
