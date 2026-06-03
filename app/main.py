"""FastAPI 应用入口 + 生命周期管理。

启动命令：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

启动流程：
1. 初始化数据库
2. 预置默认数据源
3. 启动定时调度器（启动后立即采集一次，之后每 15 分钟一次）
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import settings
from app.routers.admin import router as admin_router
from app.routers.dashboard import router as dashboard_router
from app.scheduler import register_jobs
from app.services.source_manager import seed_default_sources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化，关闭时清理资源。"""
    # ===== 启动 =====
    logger.info("启动 Tech Pluse...")

    # 预置默认数据源
    from app.database import async_session_factory

    async with async_session_factory() as db:
        await seed_default_sources(db)
        await db.commit()

    # 启动定时调度器（采集 + LLM 处理）
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, app)
    scheduler.start()
    app.state.scheduler = scheduler

    logger.info("Tech Pluse 启动完成")

    yield

    # ===== 关闭 =====
    scheduler.shutdown(wait=False)
    logger.info("Tech Pluse 已关闭")


app = FastAPI(
    title="Tech Pluse",
    description="每日科技情报聚合器",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.settings = settings

app.include_router(dashboard_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    """健康检查接口。"""
    return {"status": "ok", "version": app.version}
