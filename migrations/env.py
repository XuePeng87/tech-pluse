"""Alembic 迁移环境配置。

Alembic 是同步操作，所以用 pymysql 替代 aiomysql。
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Source, Article, Cluster, ClusterArticle, Trend  # noqa: F401
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用所有模型的 MetaData，支持 autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    # Alembic 需同步驱动，将 aiomysql 替换为 pymysql
    section = config.get_section(config.config_ini_section, {})
    url = section.get("sqlalchemy.url", "")
    if "aiomysql" in url:
        section["sqlalchemy.url"] = url.replace("aiomysql", "pymysql")

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
