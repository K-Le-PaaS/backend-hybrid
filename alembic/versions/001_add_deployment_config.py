"""Add deployment_config table and replica_count to deployment_history

Revision ID: 001
Revises:
Create Date: 2025-01-24

This migration adds:
1. deployment_configs table for persistent replica configuration
2. replica_count column to deployment_histories table
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create deployment_configs table
    op.create_table(
        'deployment_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('github_owner', sa.String(), nullable=False),
        sa.Column('github_repo', sa.String(), nullable=False),
        sa.Column('replica_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_scaled_at', sa.DateTime(), nullable=True),
        sa.Column('last_scaled_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('github_owner', 'github_repo', name='uq_owner_repo')
    )

    # Create indexes
    op.create_index('ix_deployment_configs_id', 'deployment_configs', ['id'])
    op.create_index('ix_deployment_configs_github_owner', 'deployment_configs', ['github_owner'])
    op.create_index('ix_deployment_configs_github_repo', 'deployment_configs', ['github_repo'])

    # Add replica_count to deployment_histories table (if it exists)
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('deployment_histories', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('replica_count', sa.Integer(), nullable=True, server_default='1')
        )


def downgrade() -> None:
    # Remove replica_count from deployment_histories
    with op.batch_alter_table('deployment_histories', schema=None) as batch_op:
        batch_op.drop_column('replica_count')

    # Drop indexes
    op.drop_index('ix_deployment_configs_github_repo', table_name='deployment_configs')
    op.drop_index('ix_deployment_configs_github_owner', table_name='deployment_configs')
    op.drop_index('ix_deployment_configs_id', table_name='deployment_configs')

    # Drop deployment_configs table
    op.drop_table('deployment_configs')
