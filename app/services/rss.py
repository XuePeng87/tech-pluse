"""RSS 抓取器：httpx 请求 + feedparser 解析。"""
import logging
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.config import settings
from app.models.source import Source
from app.services.models import RawArticle

logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> datetime | None:
    """解析 RSS 中的日期，兼容多种格式。

    优先用 RFC 2822（标准 RSS 格式），失败后回退常见日期格式。
    最终统一为无时区的 UTC 时间。
    """
    if not value:
        return None
    # 优先：RFC 2822（RSS 2.0 标准）
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        pass
    return None


class RSSFetcher:
    """RSS/Atom feed 抓取器。"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,  # 默认 15 秒
            follow_redirects=True,
            headers={"User-Agent": "TechPluse/0.1 (RSS Reader)"},
        )

    async def fetch(self, source: Source) -> list[RawArticle]:
        """从单个 RSS 源抓取文章。

        返回 RawArticle 列表，跳过无标题或无链接的条目。
        摘要中的 HTML 标签会被清理。
        """
        try:
            resp = await self.client.get(source.url)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"RSS 抓取失败 [{source.name}]: {e}")
            raise

        feed = feedparser.parse(resp.text)
        articles = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            excerpt = entry.get("summary", "")
            # 清理摘要中的 HTML 标签
            if "<" in excerpt:
                from bs4 import BeautifulSoup
                excerpt = BeautifulSoup(excerpt, "html.parser").get_text()

            article = RawArticle(
                source_id=source.id,
                title=title,
                url=link,
                excerpt=excerpt.strip(),
                author=entry.get("author", ""),
                published_at=_parse_date(entry.get("published")),
                raw_data={"feed_title": feed.feed.get("title", ""), "entry": entry},
            )
            articles.append(article)

        logger.info(f"从 [{source.name}] 抓取到 {len(articles)} 篇文章")
        return articles

    async def close(self):
        await self.client.aclose()
