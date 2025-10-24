"""Add operation_type field to deployment_histories

Revision ID: 002
Revises: 001
Create Date: 2025-01-24 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add operation_type column to deployment_histories table
    op.add_column('deployment_histories', 
                  sa.Column('operation_type', sa.String(50), nullable=True, default='deploy'))
    
    # Update existing records to have 'deploy' as default
    op.execute("UPDATE deployment_histories SET operation_type = 'deploy' WHERE operation_type IS NULL")
    
    # Update rollback records to have 'rollback' operation type
    op.execute("UPDATE deployment_histories SET operation_type = 'rollback' WHERE is_rollback = true")


def downgrade() -> None:
    # Remove operation_type column
    op.drop_column('deployment_histories', 'operation_type')
