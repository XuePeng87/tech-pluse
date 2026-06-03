"""调度器：注册定时任务（采集 → 去重 → 入库 → LLM 处理）。"""
import logging

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.collector import Collector
from app.services.source_manager import seed_default_sources

logger = logging.getLogger(__name__)


def register_jobs(scheduler: AsyncIOScheduler, app):
    """注册所有定时任务。

    主任务流程：
    1. 采集：从所有活跃源抓取文章
    2. 去重：URL 去重 + 标题去重 + 聚类
    3. 入库：写入 articles + clusters + cluster_articles
    4. LLM 处理：摘要、分类、信号评分
    """

    async def collect_job():
        """采集 → 去重 → 入库完整流程。"""
        from app.database import async_session_factory
        from app.services.dedup import DedupEngine

        logger.info("=== 开始采集任务 ===")
        collector = Collector()
        try:
            async with async_session_factory() as db:
                # 第一步：采集
                articles = await collector.collect_all(db)
                if not articles:
                    logger.info("没有新文章，跳过后续处理")
                    return
                logger.info(f"采集完成: {len(articles)} 篇")

                # 第二步：去重 + 聚类
                dedup = DedupEngine(db)
                processed = await dedup.process_batch(articles)
                if not processed:
                    logger.info("去重后无新文章，跳过入库")
                    return

                # 第三步：入库
                count = await dedup.save_articles(processed)
                await db.commit()
                logger.info(f"入库完成: {count} 篇新文章")
        except Exception as e:
            logger.error(f"采集任务失败: {e}", exc_info=True)
        finally:
            await collector.close()
        logger.info("=== 采集任务结束 ===")

    scheduler.add_job(
        collect_job,
        "interval",
        minutes=app.state.settings.collection_interval_minutes,
        id="collection",
        name="采集 → 去重 → 入库",
        max_instances=1,        # 防止上次还没跑完又起新任务
        coalesce=True,          # 错过的几次合并成一次
        misfire_grace_time=300, # 5 分钟容忍度
        next_run_time=datetime.now(),  # 启动后立即执行第一次
    )

    # LLM 处理任务：每 30 分钟处理一次未处理的文章
    async def process_job():
        """LLM 处理：为未处理的文章生成摘要、分类、信号分。"""
        from app.database import async_session_factory
        from app.llm.processor import Processor

        logger.info("=== 开始 LLM 处理任务 ===")
        try:
            async with async_session_factory() as db:
                processor = Processor(db)
                count = await processor.process_all()
                logger.info(f"LLM 处理完成: {count} 篇文章")
        except Exception as e:
            logger.error(f"LLM 处理任务失败: {e}", exc_info=True)
        logger.info("=== LLM 处理任务结束 ===")

    scheduler.add_job(
        process_job,
        "interval",
        minutes=30,              # 每 30 分钟处理一次
        id="llm_processing",
        name="LLM 处理文章",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        next_run_time=datetime.now(),  # 启动后立即执行第一次
    )

    # 趋势检测任务：每 4 小时跑一次
    async def trend_job():
        """趋势检测：分析聚类数据，发现升温话题。"""
        from app.database import async_session_factory
        from app.services.trends import TrendDetector

        logger.info("=== 开始趋势检测任务 ===")
        try:
            async with async_session_factory() as db:
                detector = TrendDetector(db)
                count = await detector.detect()
                await db.commit()
                if count:
                    logger.info(f"发现 {count} 个新趋势")
                else:
                    logger.info("本轮未发现新趋势")
        except Exception as e:
            logger.error(f"趋势检测任务失败: {e}", exc_info=True)
        logger.info("=== 趋势检测任务结束 ===")

    scheduler.add_job(
        trend_job,
        "interval",
        hours=4,                 # 每 4 小时检测一次
        id="trend_detection",
        name="趋势检测",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        next_run_time=datetime.now(),  # 启动后立即执行第一次
    )
