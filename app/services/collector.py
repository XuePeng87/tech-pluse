"""采集器核心：协调多源并发抓取 + 语言过滤 + 错误追踪。"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.source import Source
from app.services.html_fetcher import HTMLFetcher
from app.services.models import RawArticle
from app.services.rss import RSSFetcher

logger = logging.getLogger(__name__)

# 保留的语言白名单
ALLOWED_LANGUAGES = {"en", "unknown"}  # langdetect 对短文本返回 'unknown'


def _filter_by_language(articles: list[RawArticle]) -> list[RawArticle]:
    """按语言过滤文章，只保留英文和无法识别的短文本。"""
    try:
        from langdetect import detect

        filtered = []
        for article in articles:
            text = article.title + " " + article.excerpt
            if len(text.strip()) < 10:
                # 文本太短，无法判断语言，保留
                filtered.append(article)
                continue
            try:
                lang = detect(text)
                if lang in ALLOWED_LANGUAGES:
                    filtered.append(article)
            except Exception:
                # langdetect 判断失败，保留
                filtered.append(article)
        return filtered
    except ImportError:
        return articles


class Collector:
    """多源异步采集器：RSS + HTML，并发控制 + 错误追踪。"""

    def __init__(self):
        self.rss_fetcher = RSSFetcher()
        self.html_fetcher = HTMLFetcher()

    async def collect_all(self, db: AsyncSession) -> list[RawArticle]:
        """从所有活跃源抓取文章。

        流程：
        1. 查活跃源
        2. 按 fetch_method 分组（rss / html）
        3. Semaphore 限制并发（默认 10）
        4. 并发抓取
        5. 记录成功/失败，连续 5 次失败自动停用源
        6. 语言过滤
        """
        sources = await self._get_active_sources(db)
        if not sources:
            logger.warning("没有活跃的源，跳过采集")
            return []

        rss_sources = [s for s in sources if s.fetch_method == "rss"]
        html_sources = [s for s in sources if s.fetch_method == "html"]

        semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

        async def safe_fetch(source: Source, fetch_method: str):
            async with semaphore:
                return await self._fetch_single(source, fetch_method)

        tasks = []
        for source in rss_sources:
            tasks.append(safe_fetch(source, "rss"))
        for source in html_sources:
            tasks.append(safe_fetch(source, "html"))

        # 并发执行，异常不中断
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles = []
        for source, result in zip(rss_sources + html_sources, results):
            if isinstance(result, Exception):
                await self._record_error(db, source)
            else:
                await self._record_success(db, source, len(result))
                all_articles.extend(result)

        # 语言过滤
        all_articles = _filter_by_language(all_articles)

        logger.info(f"本次采集: {len(all_articles)} 篇文章")
        return all_articles

    async def _fetch_single(self, source: Source, fetch_method: str) -> list[RawArticle]:
        """根据抓取方式分发到对应的抓取器。"""
        if fetch_method == "rss":
            return await self.rss_fetcher.fetch(source)
        elif fetch_method == "html":
            return await self.html_fetcher.fetch(source)
        return []

    async def _get_active_sources(self, db: AsyncSession) -> list[Source]:
        """查询所有活跃的源。"""
        result = await db.execute(
            select(Source).where(Source.is_active == True)
        )
        return list(result.scalars().all())

    async def _record_error(self, db: AsyncSession, source: Source):
        """记录抓取失败，连续 5 次自动停用。"""
        source.fetch_errors += 1
        if source.fetch_errors >= 5:
            source.is_active = False
            logger.warning(f"源 [{source.name}] 连续失败 5 次，已自动停用")
        source.last_fetch = datetime.utcnow()
        await db.flush()

    async def _record_success(self, db: AsyncSession, source: Source, count: int):
        """记录抓取成功，重置错误计数。"""
        source.fetch_errors = 0
        source.last_fetch = datetime.utcnow()
        await db.flush()

    async def close(self):
        """关闭 HTTP 客户端。"""
        await self.rss_fetcher.close()
        await self.html_fetcher.close()
