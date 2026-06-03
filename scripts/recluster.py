"""从已有文章重新生成话题（关键词聚类）。

算法：
1. 按文章 subcategories（LLM 提取的关键词+实体）做聚类
2. 有共同关键词的文章归入同一话题（贪心匹配）
3. 每个话题名取关键词交集 + 首篇文章标题摘要
"""
import asyncio
import logging
import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from app.database import async_session_factory
from app.models.article import Article
from app.models.source import Source
from app.models.cluster import Cluster, ClusterArticle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 聚类参数
COMMON_KEYWORD_MIN = 2       # 至少几个共同关键词才归入同一话题
TOPIC_KEYWORDS_MAX = 3       # 话题名最多取几个关键词
MIN_CLUSTER_SIZE = 1         # 最小话题大小（1=单篇也成话题）


def _common_keywords(a_tags: list[str], b_tags: list[str]) -> list[str]:
    """返回两个标签列表的共同关键词（不区分大小写）。"""
    a_set = {t.lower() for t in (a_tags or [])}
    b_set = {t.lower() for t in (b_tags or [])}
    return [t for t in (a_tags or []) if t.lower() in (a_set & b_set)]


async def recluster():
    async with async_session_factory() as db:
        # 1. 清空旧话题
        await db.execute(ClusterArticle.__table__.delete())
        await db.execute(Cluster.__table__.delete())
        await db.flush()

        # 2. 读取所有已处理文章
        result = await db.execute(
            select(Article, Source)
            .join(Source, Article.source_id == Source.id)
            .where(Article.is_processed == True)
        )
        rows = result.all()
        logger.info(f"读取到 {len(rows)} 篇已处理文章")

        # 3. 关键词聚类
        # clusters_data: list of (Cluster, [(Article, Source)])
        clusters_data: list[tuple[Cluster, list[tuple[Article, Source]], list[str]]] = []

        for article, source in rows:
            tags = article.subcategories or []
            matched_idx = None
            matched_common = []

            # 尝试匹配已有话题
            for idx, (cluster, members, member_tags) in enumerate(clusters_data):
                common = _common_keywords(tags, member_tags)
                if len(common) >= COMMON_KEYWORD_MIN:
                    # 可能有多个话题都匹配，选共同词最多的
                    if matched_idx is None or len(common) > len(matched_common):
                        matched_idx = idx
                        matched_common = common

            if matched_idx is not None:
                cluster, members, all_tags = clusters_data[matched_idx]
                members.append((article, source))
                # 更新话题的全部标签（去重）
                existing = {t.lower() for t in all_tags}
                for t in tags:
                    if t.lower() not in existing:
                        all_tags.append(t)
                        existing.add(t.lower())
            else:
                # 创建新话题
                cluster = Cluster(
                    id=uuid.uuid4(),
                    title=article.title,
                    summary=article.summary or article.excerpt or "",
                    topic="",  # 后面用关键词填充
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    source_count=1,
                    article_count=0,
                    avg_signal=article.signal_score or 0.5,
                )
                clusters_data.append((cluster, [(article, source)], list(tags)))

        # 4. 设置话题名 + 统计
        for cluster, members, all_tags in clusters_data:
            # 话题名：取出现频率最高的前 N 个关键词
            tag_counts = Counter(t.lower() for t in all_tags)
            top_tags = [tag for tag, _ in tag_counts.most_common(TOPIC_KEYWORDS_MAX)]
            cluster.topic = " / ".join(top_tags) if top_tags else cluster.title[:50]
            cluster.title = members[0][0].title  # 取第一篇标题

            cluster.article_count = len(members)
            cluster.source_count = len(set(s.id for _, s in members))
            cluster.avg_signal = sum(
                (a.signal_score or 0.5) for a, _ in members
            ) / len(members)
            cluster.last_seen = datetime.utcnow()

        # 过滤太小的话题（可选）
        if MIN_CLUSTER_SIZE > 1:
            clusters_data = [
                (c, m, t) for c, m, t in clusters_data
                if len(m) >= MIN_CLUSTER_SIZE
            ]

        logger.info(f"聚类完成: {len(rows)} 篇 -> {len(clusters_data)} 个话题")

        # 5. 写入数据库
        for cluster, members, _ in clusters_data:
            db.add(cluster)
            await db.flush()

            max_score = max((a.signal_score or 0.5) for a, _ in members)
            for article, source in members:
                link = ClusterArticle(
                    cluster_id=cluster.id,
                    article_id=article.id,
                    is_canonical=(article.signal_score or 0) >= max_score,
                )
                db.add(link)

        await db.commit()
        logger.info(f"已入库 {len(clusters_data)} 个话题")

        # 输出统计
        sorted_clusters = sorted(
            clusters_data, key=lambda x: len(x[1]), reverse=True
        )
        sizes = [len(m) for _, m, _ in clusters_data]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        singletons = sum(1 for s in sizes if s == 1)

        print(f"\n=== 聚类统计 ===")
        print(f"  总文章: {len(rows)}")
        print(f"  话题数: {len(clusters_data)}")
        print(f"  平均每个话题: {avg_size:.1f} 篇")
        print(f"  单篇话题: {singletons} 个")
        print(f"  最大话题: {max(sizes)} 篇")

        print(f"\n=== Top 15 话题 ===")
        for cluster, members, all_tags in sorted_clusters[:15]:
            tag_counts = Counter(t.lower() for t in all_tags)
            top_tags = [t for t, _ in tag_counts.most_common(5)]
            print(f"\n  [{len(members)}篇] 话题: {cluster.topic}")
            print(f"    标签: {', '.join(top_tags)}")
            for a, s in members[:3]:
                print(f"    - [{s.name[:15]}] {a.title[:70]}")
            if len(members) > 3:
                print(f"    ... 还有 {len(members) - 3} 篇")


if __name__ == "__main__":
    asyncio.run(recluster())
