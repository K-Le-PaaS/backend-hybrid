"""Add notifications and notification_reports tables

Revision ID: 003
Revises: 002
Create Date: 2025-01-29 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(50), nullable=False),
        sa.Column('source', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='firing'),
        sa.Column('labels', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )
    
    # Create indexes for notifications
    op.create_index('ix_notifications_id', 'notifications', ['id'])
    op.create_index('ix_notifications_severity', 'notifications', ['severity'])
    op.create_index('ix_notifications_status', 'notifications', ['status'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('idx_notification_severity_status', 'notifications', ['severity', 'status'])
    
    # Create notification_reports table
    op.create_table(
        'notification_reports',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('notification_id', sa.String(255), nullable=False),
        sa.Column('cluster', sa.String(255), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('snapshot_json', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    
    # Create foreign key constraint
    op.create_foreign_key(
        'fk_notification_reports_notification_id',
        'notification_reports', 'notifications',
        ['notification_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # Create indexes for notification_reports
    op.create_index('ix_notification_reports_id', 'notification_reports', ['id'])
    op.create_index('ix_notification_reports_notification_id', 'notification_reports', ['notification_id'])
    op.create_index('ix_notification_reports_cluster', 'notification_reports', ['cluster'])
    op.create_index('ix_notification_reports_created_at', 'notification_reports', ['created_at'])
    op.create_index('idx_report_notification_created', 'notification_reports', ['notification_id', 'created_at'])
    op.create_index('idx_report_cluster', 'notification_reports', ['cluster'])


def downgrade() -> None:
    # Drop indexes first
    op.drop_index('idx_report_cluster', 'notification_reports')
    op.drop_index('idx_report_notification_created', 'notification_reports')
    op.drop_index('ix_notification_reports_created_at', 'notification_reports')
    op.drop_index('ix_notification_reports_cluster', 'notification_reports')
    op.drop_index('ix_notification_reports_notification_id', 'notification_reports')
    op.drop_index('ix_notification_reports_id', 'notification_reports')
    
    # Drop notification_reports table
    op.drop_table('notification_reports')
    
    # Drop indexes for notifications
    op.drop_index('idx_notification_severity_status', 'notifications')
    op.drop_index('ix_notifications_created_at', 'notifications')
    op.drop_index('ix_notifications_status', 'notifications')
    op.drop_index('ix_notifications_severity', 'notifications')
    op.drop_index('ix_notifications_id', 'notifications')
    
    # Drop notifications table
    op.drop_table('notifications')

