"""重建趋势表：四维度检测字段

新增: prev_article_count, burst_score, cross_source_boost, status, days_active, last_check_at
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trends', sa.Column('prev_article_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('trends', sa.Column('burst_score', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('trends', sa.Column('cross_source_boost', sa.Float(), nullable=True, server_default='0.0'))
    # signal 列已存在，跳过
    op.add_column('trends', sa.Column('status', sa.String(16), nullable=True, server_default='hot'))
    op.add_column('trends', sa.Column('days_active', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('trends', sa.Column('last_check_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('trends', 'last_check_at')
    op.drop_column('trends', 'days_active')
    op.drop_column('trends', 'status')
    op.drop_column('trends', 'cross_source_boost')
    op.drop_column('trends', 'burst_score')
    op.drop_column('trends', 'prev_article_count')
