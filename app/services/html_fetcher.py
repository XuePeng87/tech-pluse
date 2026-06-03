"""HTML 页面抓取器：httpx + BeautifulSoup，针对不同源写解析逻辑。"""
import logging
import uuid
from datetime import datetime

from bs4 import BeautifulSoup
import httpx

from app.config import settings
from app.models.source import Source
from app.services.models import RawArticle

logger = logging.getLogger(__name__)


class HTMLFetcher:
    """HTML 页面抓取器。

    每个源在 config.parser 中指定解析器名称，Fetcher 按名称分发。
    """

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
        )

    async def fetch(self, source: Source) -> list[RawArticle]:
        """抓取单个 HTML 源，按 parser 名称分发到具体解析器。"""
        resp = await self.client.get(source.url)
        resp.raise_for_status()

        parser_name = source.config.get("parser", "github_trending")
        parsers = {
            "github_trending": self._parse_github_trending,
        }

        parser = parsers.get(parser_name)
        if not parser:
            logger.warning(f"源 [{source.name}] 无对应解析器: {parser_name}")
            return []

        return parser(resp.text, source)

    def _parse_github_trending(self, html: str, source: Source) -> list[RawArticle]:
        """解析 GitHub Trending 页面，提取 trending repos 信息。"""
        soup = BeautifulSoup(html, "html.parser")
        articles = []

        repos = soup.select("article.Box-row")
        for repo in repos:
            h2 = repo.select_one("h2 h3 a")
            if not h2:
                continue

            repo_path = h2.get("href", "").strip()
            title = repo_path.strip("/").split("/")[-1]  # 取 repo 名
            description_el = repo.select_one("p.col-9")
            description = description_el.get_text(strip=True) if description_el else ""

            article = RawArticle(
                source_id=source.id,
                title=title,
                url=f"https://github.com{repo_path}",
                excerpt=description,
                raw_data={"repo": repo_path},
            )
            articles.append(article)

        logger.info(f"从 GitHub Trending 抓取到 {len(articles)} 个 repo")
        return articles

    async def close(self):
        await self.client.aclose()
