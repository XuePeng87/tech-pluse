"""去重引擎 + 聚类入库。

完整流程：
1. URL 去重 — 对比数据库已有 URL，过滤已入库的文章
2. 标题指纹去重 — 同批次内标题 Jaccard 相似度匹配，过滤近似重复
3. Cluster 匹配/创建 — 将去重后的文章归入已有 cluster 或创建新 cluster
4. Canonical article 选择 — 每个 cluster 中选信号分最高的文章作为主文章
5. 文章入库 — 将文章和 cluster 关联写入数据库
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.cluster import Cluster, ClusterArticle
from app.services.models import RawArticle

logger = logging.getLogger(__name__)

# 标题 Jaccard 相似度阈值：超过此值认为是同一篇文章
TITLE_SIMILARITY_THRESHOLD = 0.6


def _title_tokens(title: str) -> set[str]:
    """标题分词：转小写、去标点、取有意义的词（长度 >= 3）。"""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    words = s.split()
    # 过滤掉太短的词和停用词
    stop_words = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "has", "have", "will", "been", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "out", "how", "who", "what", "its", "new"}
    return {w for w in words if len(w) >= 3 and w not in stop_words}


def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个标题的 Jaccard 相似度。"""
    tokens_a = _title_tokens(a)
    tokens_b = _title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _compute_signal(article: RawArticle) -> float:
    """计算文章的初步信号分。

    基于源 weight + 标题长度 + 是否有摘要，综合打分。
    """
    # 基础分 0.5
    score = 0.5
    # 标题越长（信息量越大），加分（上限 0.2）
    score += min(0.2, len(article.title) * 0.005)
    # 有摘要加分（0.1）
    if article.excerpt:
        score += 0.1
    # 标题含技术关键词加分（0.2）
    tech_words = {"ai", "ml", "open", "release", "launch", "update", "security", "breach", "cloud", "data", "rust", "python", "kubernetes", "llm", "model", "api", "openai", "anthropic", "google", "microsoft", "apple"}
    title_lower = article.title.lower()
    for word in tech_words:
        if word in title_lower:
            score += 0.02
            break
    return min(1.0, score)


@dataclass
class ProcessedArticle:
    """去重处理后、准备入库的文章数据。"""
    raw: RawArticle
    signal_score: float = 0.0
    matched_cluster_id: uuid.UUID | None = None  # 匹配到的已有 cluster ID


class DedupEngine:
    """去重 + 聚类引擎。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def process_batch(self, articles: list[RawArticle]) -> list[ProcessedArticle]:
        """处理一批采集到的文章。

        完整流程：URL 去重 → 标题去重 → cluster 匹配 → 计算信号分 → 准备入库
        """
        if not articles:
            return []

        # Stage 1: URL 去重
        unique_by_url = await self._url_dedup(articles)

        # Stage 2: 标题指纹去重
        unique_by_title = await self._title_dedup(unique_by_url)

        # Stage 3: 匹配已有 cluster 或标记为新
        processed = []
        for article in unique_by_title:
            signal = _compute_signal(article)
            cluster_id = await self._match_cluster(article)
            pa = ProcessedArticle(
                raw=article,
                signal_score=signal,
                matched_cluster_id=cluster_id,
            )
            processed.append(pa)

        # Stage 4: 新文章之间聚类
        await self._cluster_new(processed)

        logger.info(f"去重完成: {len(articles)} -> {len(processed)} 篇文章")
        return processed

    async def _url_dedup(self, articles: list[RawArticle]) -> list[RawArticle]:
        """URL 去重：对比数据库已有 URL + 同批次内去重。"""
        urls = [a.url for a in articles]
        existing_urls = set()
        if urls:
            # 分批查询（MySQL IN 列表有长度限制）
            batch_size = 500
            for i in range(0, len(urls), batch_size):
                batch_urls = urls[i:i + batch_size]
                result = await self.db.execute(
                    select(Article.url).where(Article.url.in_(batch_urls))
                )
                existing_urls.update(row[0] for row in result.all())

        # 第一层：过滤数据库中已有的 URL
        unique = [a for a in articles if a.url not in existing_urls]
        dropped_db = len(articles) - len(unique)

        # 第二层：同批次内去重（多个源可能引用同一篇文章）
        seen_urls: set[str] = set()
        batch_unique: list[RawArticle] = []
        for a in unique:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                batch_unique.append(a)
        dropped_batch = len(unique) - len(batch_unique)

        if dropped_db:
            logger.info(f"URL 去重（数据库）: 过滤掉 {dropped_db} 篇已入库文章")
        if dropped_batch:
            logger.info(f"URL 去重（同批次）: 过滤掉 {dropped_batch} 篇重复文章")
        return batch_unique

    async def _title_dedup(self, articles: list[RawArticle]) -> list[RawArticle]:
        """标题指纹去重：同批次内标题相似度超过阈值就认为是重复的。

        保留第一篇出现的（通常是信号分更高的源）。
        """
        # 先查数据库中已有的标题指纹（同 cluster 的标题视为已有）
        result = await self.db.execute(select(Cluster.title))
        existing_titles = [row[0] for row in result.all()]

        unique: list[RawArticle] = []
        for article in articles:
            is_dup = False
            for existing_title in existing_titles:
                sim = _jaccard_similarity(article.title, existing_title)
                if sim >= TITLE_SIMILARITY_THRESHOLD:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(article)

        dropped = len(articles) - len(unique)
        if dropped:
            logger.info(f"标题去重: 过滤掉 {dropped} 篇近似重复文章")
        return unique

    async def _match_cluster(self, article: RawArticle) -> uuid.UUID | None:
        """将文章匹配到已有的 cluster。

        通过标题相似度对比最近活跃（72 小时内）的 cluster。
        """
        cutoff = datetime.utcnow()
        result = await self.db.execute(
            select(Cluster).where(
                Cluster.last_seen >= cutoff - timedelta(hours=72)
            ).order_by(Cluster.last_seen.desc()).limit(200)
        )
        clusters = result.scalars().all()

        for cluster in clusters:
            sim = _jaccard_similarity(article.title, cluster.title)
            if sim >= TITLE_SIMILARITY_THRESHOLD:
                return cluster.id

        return None

    async def _cluster_new(self, processed: list[ProcessedArticle]) -> None:
        """新文章之间的聚类：将标题相似的文章归入同一个 cluster。

        使用贪心聚类：遍历新文章，与已有新 cluster 对比标题相似度，
        超过阈值则归入，否则创建新 cluster。
        """
        new_articles = [p for p in processed if p.matched_cluster_id is None]
        if not new_articles:
            return

        # 新创建的 cluster 列表
        new_clusters: list[tuple[Cluster, list[ProcessedArticle]]] = []

        for pa in new_articles:
            matched = False
            # 尝试匹配已创建的新 cluster
            for cluster, members in new_clusters:
                sim = _jaccard_similarity(pa.raw.title, cluster.title)
                if sim >= TITLE_SIMILARITY_THRESHOLD:
                    pa.matched_cluster_id = cluster.id
                    members.append(pa)
                    matched = True
                    break

            # 没有匹配到，创建新 cluster
            if not matched:
                cluster = Cluster(
                    id=uuid.uuid4(),
                    title=pa.raw.title,
                    summary=pa.raw.excerpt,
                    topic=pa.raw.title[:50],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    source_count=1,
                    article_count=0,
                    avg_signal=pa.signal_score,
                )
                pa.matched_cluster_id = cluster.id
                new_clusters.append((cluster, [pa]))
                self.db.add(cluster)

        logger.info(f"批次内聚类: {len(new_articles)} 篇 -> {len(new_clusters)} 个 cluster")

    async def save_articles(self, processed: list[ProcessedArticle]) -> int:
        """将去重后的文章写入数据库，并建立 cluster 关联。

        返回实际入库的文章数量。
        """
        count = 0
        for pa in processed:
            article = Article(
                id=uuid.uuid4(),
                source_id=pa.raw.source_id,
                title=pa.raw.title,
                url=pa.raw.url,
                excerpt=pa.raw.excerpt,
                author=pa.raw.author,
                published_at=pa.raw.published_at,
                raw_data=pa.raw.raw_data,
            )
            self.db.add(article)

            # 建立 cluster 关联
            if pa.matched_cluster_id:
                link = ClusterArticle(
                    cluster_id=pa.matched_cluster_id,
                    article_id=article.id,
                    is_canonical=False,  # 默认不是 canonical，后续更新
                )
                self.db.add(link)

            count += 1

        # 更新 cluster 统计
        await self._update_cluster_stats()

        # 标记 canonical article（每个 cluster 信号分最高的那篇）
        await self._mark_canonical()

        await self.db.flush()
        logger.info(f"入库: {count} 篇文章")
        return count

    async def _update_cluster_stats(self):
        """更新所有 cluster 的统计信息（文章数、源数、平均分）。"""
        result = await self.db.execute(
            select(Cluster).where(Cluster.article_count == 0)
        )
        clusters = result.scalars().all()
        for cluster in clusters:
            # 查询该 cluster 下的文章
            art_result = await self.db.execute(
                select(Article)
                .join(ClusterArticle, Article.id == ClusterArticle.article_id)
                .where(ClusterArticle.cluster_id == cluster.id)
            )
            articles = art_result.scalars().all()
            if articles:
                cluster.article_count = len(articles)
                cluster.source_count = len(set(a.source_id for a in articles))
                cluster.avg_signal = sum(0.5 for _ in articles) / len(articles)  # 临时用 0.5，后续 LLM 处理后更新
                cluster.last_seen = datetime.utcnow()

    async def _mark_canonical(self):
        """标记每个 cluster 的 canonical article（信号分最高的那篇）。"""
        result = await self.db.execute(select(Cluster))
        clusters = result.scalars().all()
        for cluster in clusters:
            link_result = await self.db.execute(
                select(ClusterArticle)
                .join(Article, ClusterArticle.article_id == Article.id)
                .where(ClusterArticle.cluster_id == cluster.id)
                .order_by(Article.signal_score.desc())
            )
            links = link_result.scalars().all()
            if links:
                links[0].is_canonical = True
