"""add return requests and esi event log

Revision ID: 8a7c2d1e5b90
Revises: c4aa7f2be991
Create Date: 2026-05-16 16:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8a7c2d1e5b90"
down_revision = "c4aa7f2be991"
branch_labels = None
depends_on = None


return_request_status = sa.Enum(
    "created",
    "locker_opened",
    "awaiting_close",
    "completed",
    "failed",
    name="return_request_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    return_request_status.create(bind, checkfirst=True)

    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rental_id", sa.Uuid(), nullable=False),
        sa.Column("locker_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
        sa.Column("pin", sa.String(length=64), nullable=False),
        sa.Column("status", return_request_status, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cell_id"], ["locker_cells.id"]),
        sa.ForeignKeyConstraint(["locker_id"], ["locker_locations.id"]),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_return_requests_rental_id"), "return_requests", ["rental_id"], unique=False)
    op.create_index(op.f("ix_return_requests_locker_id"), "return_requests", ["locker_id"], unique=False)
    op.create_index(op.f("ix_return_requests_cell_id"), "return_requests", ["cell_id"], unique=False)
    op.create_index(op.f("ix_return_requests_status"), "return_requests", ["status"], unique=False)
    op.create_index(
        op.f("ix_return_requests_provider_event_id"),
        "return_requests",
        ["provider_event_id"],
        unique=False,
    )

    op.create_table(
        "esi_event_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("locker_external_id", sa.String(length=128), nullable=True),
        sa.Column("cell_external_id", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_result", sa.String(length=128), nullable=True),
        sa.Column("matched_rental_id", sa.Uuid(), nullable=True),
        sa.Column("matched_return_request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["matched_rental_id"], ["rentals.id"]),
        sa.ForeignKeyConstraint(["matched_return_request_id"], ["return_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_event_id"),
    )
    op.create_index(op.f("ix_esi_event_log_provider_event_id"), "esi_event_log", ["provider_event_id"], unique=True)
    op.create_index(op.f("ix_esi_event_log_event_type"), "esi_event_log", ["event_type"], unique=False)
    op.create_index(op.f("ix_esi_event_log_locker_external_id"), "esi_event_log", ["locker_external_id"], unique=False)
    op.create_index(op.f("ix_esi_event_log_cell_external_id"), "esi_event_log", ["cell_external_id"], unique=False)
    op.create_index(op.f("ix_esi_event_log_processing_result"), "esi_event_log", ["processing_result"], unique=False)
    op.create_index(op.f("ix_esi_event_log_matched_rental_id"), "esi_event_log", ["matched_rental_id"], unique=False)
    op.create_index(
        op.f("ix_esi_event_log_matched_return_request_id"),
        "esi_event_log",
        ["matched_return_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_esi_event_log_matched_return_request_id"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_matched_rental_id"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_processing_result"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_cell_external_id"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_locker_external_id"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_event_type"), table_name="esi_event_log")
    op.drop_index(op.f("ix_esi_event_log_provider_event_id"), table_name="esi_event_log")
    op.drop_table("esi_event_log")

    op.drop_index(op.f("ix_return_requests_provider_event_id"), table_name="return_requests")
    op.drop_index(op.f("ix_return_requests_status"), table_name="return_requests")
    op.drop_index(op.f("ix_return_requests_cell_id"), table_name="return_requests")
    op.drop_index(op.f("ix_return_requests_locker_id"), table_name="return_requests")
    op.drop_index(op.f("ix_return_requests_rental_id"), table_name="return_requests")
    op.drop_table("return_requests")

    bind = op.get_bind()
    return_request_status.drop(bind, checkfirst=True)
