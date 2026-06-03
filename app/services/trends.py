"""趋势检测服务：基于 Cluster 的四维度趋势分析。

从已聚类的事件中发现升温话题，不再依赖碎片化的关键词词频。

四维度：
a) 增长率 — Cluster 本周 vs 上周新增文章数
b) 爆发检测 — Cluster 近 7 天日入库量 Z-score
c) 跨源验证 — 直接使用 Cluster.source_count
d) 趋势衰减 — 冷却 / 持续热点状态管理
"""
import logging
import math
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.cluster import Cluster, ClusterArticle
from app.models.trend import Trend

logger = logging.getLogger(__name__)

# 爆发检测 Z-score 阈值，超过则标记为突发
BURST_ZSCORE_THRESHOLD = 2.0
# 跨源最少独立源数量
CROSS_SOURCE_MIN = 3
# 趋势状态判定天数
COOLING_DAYS = 3
SUSTAINED_DAYS = 14
# 冷却趋势保留天数
COOLING_DELETE_DAYS = 7
# 趋势候选门槛
MIN_ARTICLE_COUNT = 3
MIN_SOURCE_COUNT = 2
# 每轮最多新增趋势数
MAX_NEW_TRENDS_PER_RUN = 20


class TrendDetector:
    """基于 Cluster 的趋势检测器。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def detect(self) -> int:
        """执行四维度趋势检测，返回新增趋势数量。

        流程：
        1. 查询本周活跃的 Cluster
        2. 对每个 Cluster 计算四维评分
        3. 过滤 + 排序 + 去重
        4. 衰减状态更新
        5. 入库
        """
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        # ========== 0) 清理冷却趋势 ==========
        await self._cleanup_cooling_trends(now)

        # ========== a) 获取候选 Cluster ==========
        candidates = await self._cluster_candidates(week_ago)

        # ========== b) 四维评分 ==========
        new_trends = []
        for cluster in candidates:
            # 提前过滤
            if cluster.article_count < MIN_ARTICLE_COUNT:
                continue
            if cluster.source_count < MIN_SOURCE_COUNT:
                continue

            # 增长率：本周 vs 上周
            this_week = await self._cluster_window_count(cluster.id, week_ago, now)
            last_week = await self._cluster_window_count(cluster.id, two_weeks_ago, week_ago)
            growth_rate = this_week / max(1, last_week) if last_week > 0 else float("inf")
            if growth_rate > 100:
                growth_rate = 100.0

            # 爆发检测：7 天日入库 Z-score
            z = await self._cluster_burst(cluster.id, now)

            # 综合评分
            signal = self._composite_score(growth_rate, z, cluster.source_count, cluster.article_count)

            if signal < 0.3:
                continue

            topic_text = cluster.topic or cluster.title[:50]
            trend = Trend(
                id=uuid.uuid4(),
                topic=topic_text,
                category="",
                detected_at=now,
                window_start=week_ago,
                window_end=now,
                article_count=cluster.article_count,
                source_count=cluster.source_count,
                prev_article_count=last_week,
                growth_rate=growth_rate,
                burst_score=z,
                cross_source_boost=self._calc_cross_source_boost(cluster.source_count),
                signal=signal,
                status="hot" if z >= BURST_ZSCORE_THRESHOLD else "emerging",
                days_active=1,
                last_check_at=now,
            )
            new_trends.append(trend)

        # 按信号分排序，取 Top N
        new_trends.sort(key=lambda t: t.signal, reverse=True)
        new_trends = new_trends[:MAX_NEW_TRENDS_PER_RUN]

        # ========== c) 去重：匹配已有趋势 ==========
        existing = await self._get_existing_trends()
        final_new = []
        for t in new_trends:
            if t.topic in existing:
                old = existing[t.topic]
                old.article_count = t.article_count
                old.source_count = t.source_count
                old.prev_article_count = t.prev_article_count
                old.growth_rate = t.growth_rate
                old.burst_score = t.burst_score
                old.cross_source_boost = t.cross_source_boost
                old.signal = t.signal
                old.days_active += 1
                old.last_check_at = now
                old.window_end = now
            else:
                final_new.append(t)

        # ========== d) 趋势衰减检测 ==========
        await self._update_decay(existing, now)

        # ========== 入库 ==========
        for trend in final_new:
            trend.summary = (
                f"「{trend.topic}」本周新增 {trend.article_count} 篇，"
                f"涉及 {trend.source_count} 个源，均分 {trend.signal:.2f}"
            )
            self.db.add(trend)
        if final_new:
            await self.db.flush()

        logger.info(f"趋势检测完成: {len(final_new)} 个新增, {len(existing)} 个更新")
        return len(final_new)

    async def _cluster_candidates(self, since: datetime) -> list[Cluster]:
        """查询 since 以来活跃的 Cluster。"""
        result = await self.db.execute(
            select(Cluster)
            .where(Cluster.last_seen >= since)
            .order_by(desc(Cluster.article_count), desc(Cluster.avg_signal))
            .limit(200)
        )
        return list(result.scalars().all())

    async def _cluster_window_count(
        self, cluster_id: uuid.UUID, start: datetime, end: datetime
    ) -> int:
        """查询某 Cluster 在 [start, end) 时间段内新增的文章数。"""
        result = await self.db.execute(
            select(func.count(ClusterArticle.article_id))
            .join(Article, ClusterArticle.article_id == Article.id)
            .where(
                ClusterArticle.cluster_id == cluster_id,
                Article.fetched_at >= start,
                Article.fetched_at < end,
            )
        )
        return result.scalar() or 0

    async def _cluster_burst(self, cluster_id: uuid.UUID, now: datetime) -> float:
        """计算 Cluster 近 7 天日入库量的 Z-score。

        Z = (今日入库量 - 历史均值) / 历史标准差
        """
        days = 7
        daily_counts = []
        for d in range(days):
            day_start = now - timedelta(days=d + 1)
            day_end = now - timedelta(days=d)
            count = await self._cluster_window_count(cluster_id, day_start, day_end)
            daily_counts.append(count)

        if len(daily_counts) < 2:
            return 0.0

        today_count = daily_counts[0]
        mean = sum(daily_counts) / len(daily_counts)
        variance = sum((c - mean) ** 2 for c in daily_counts) / max(1, len(daily_counts) - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0

        return (today_count - mean) / max(1, std)

    def _calc_cross_source_boost(self, source_count: int) -> float:
        """跨源加权：3 源以上才开始加分。"""
        if source_count < CROSS_SOURCE_MIN:
            return 0.0
        return min(0.2, (source_count - CROSS_SOURCE_MIN + 1) * 0.05)

    def _composite_score(
        self, growth_rate: float, burst_z: float, source_count: int, count: int
    ) -> float:
        """综合信号：增长率 + 爆发 + 跨源 + 基础频次。"""
        g_score = min(0.35, math.log2(max(1, growth_rate)) * 0.1)
        b_score = min(0.35, burst_z * 0.15)
        s_score = self._calc_cross_source_boost(source_count)
        f_score = min(0.1, math.log2(max(1, count)) * 0.03)
        return min(1.0, g_score + b_score + s_score + f_score)

    async def _get_existing_trends(self) -> dict[str, Trend]:
        """获取所有已有趋势，按 topic 索引。"""
        result = await self.db.execute(select(Trend))
        trends = result.scalars().all()
        return {t.topic: t for t in trends}

    async def _update_decay(self, existing: dict[str, Trend], now: datetime) -> None:
        """更新已有趋势的衰减状态。"""
        for topic, trend in existing.items():
            days_since = (now - trend.last_check_at).days if trend.last_check_at else 999

            if trend.days_active >= SUSTAINED_DAYS and trend.growth_rate >= 1.0:
                trend.status = "sustained"
            elif days_since >= COOLING_DAYS or trend.growth_rate < 0.8:
                trend.status = "cooling"
            elif trend.burst_score >= BURST_ZSCORE_THRESHOLD:
                trend.status = "hot"

            trend.last_check_at = now
            await self.db.flush()

    async def _cleanup_cooling_trends(self, now: datetime) -> None:
        """删除持续冷却超过 COOLING_DELETE_DAYS 天的趋势。"""
        cutoff = now - timedelta(days=COOLING_DELETE_DAYS)
        result = await self.db.execute(
            delete(Trend).where(
                Trend.status == "cooling",
                Trend.last_check_at <= cutoff,
            )
        )
        deleted = result.rowcount
        if deleted:
            await self.db.flush()
            logger.info(f"清理冷却趋势: {deleted} 条")
