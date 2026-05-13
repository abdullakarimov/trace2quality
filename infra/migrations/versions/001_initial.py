"""Initial schema creation

Revision ID: 001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create initial tables"""
    # integration_configs table
    op.create_table(
        'integration_configs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('type', sa.String(50), unique=True, nullable=False),
        sa.Column('config_encrypted', sa.Text, nullable=False),
        sa.Column('last_tested', sa.DateTime, nullable=True),
        sa.Column('status', sa.String(50), default='unconfigured'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
    )

    # workflow_runs table
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_key', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), default='queued'),
        sa.Column('parameters', sa.JSON, default={}),
        sa.Column('dry_run', sa.String(1), default='0'),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('celery_task_id', sa.String(100), unique=True, nullable=True),
    )

    # workflow_run_logs table
    op.create_table(
        'workflow_run_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('timestamp', sa.DateTime, default=sa.func.now()),
        sa.Column('level', sa.String(20), default='INFO'),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('correlation_id', sa.String(36), nullable=True),
    )

    # artifacts table
    op.create_table(
        'artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), default='application/json'),
        sa.Column('size_bytes', sa.String(20), default='0'),
        sa.Column('storage_path', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
    )

    # dataset_snapshots table
    op.create_table(
        'dataset_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('dataset_name', sa.String(100), nullable=False),
        sa.Column('source_url', sa.Text, nullable=True),
        sa.Column('data_hash', sa.String(64), nullable=True),
        sa.Column('storage_path', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
        sa.Column('metadata', sa.JSON, default={}),
    )

    # user_preferences table
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(100), unique=True, nullable=False),
        sa.Column('preferences', sa.JSON, default={}),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
    )


def downgrade():
    """Drop all tables"""
    op.drop_table('user_preferences')
    op.drop_table('dataset_snapshots')
    op.drop_table('artifacts')
    op.drop_table('workflow_run_logs')
    op.drop_table('workflow_runs')
    op.drop_table('integration_configs')
