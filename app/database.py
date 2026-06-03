"""数据库配置：异步引擎 + Session 工厂。"""
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，所有 Model 继承此类。"""
    pass


# 异步引擎：连接池 10 个常驻，最大溢出 20 个
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,  # 每次 borrow 前检查连接是否存活
    pool_size=10,
    max_overflow=20,
)

# Session 工厂：每个请求/任务创建独立 Session
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后不失效对象，方便后续使用
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入用的数据库 Session 生成器。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
