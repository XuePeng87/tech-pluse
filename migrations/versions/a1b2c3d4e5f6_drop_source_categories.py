"""删除 sources.categories 列

分类标签不再使用，文章分类由 LLM 自行判断。
"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'eb3e424d44f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('sources', 'categories')


def downgrade() -> None:
    from sqlalchemy.dialects.mysql import JSON
    op.add_column('sources', op.column('categories', JSON, nullable=True))
