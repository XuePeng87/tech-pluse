"""去重聚类模型 — 同一事件的多篇文章归入一个 cluster。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Cluster(Base):
    """聚类表：同一新闻事件的文章聚合在一起。"""
    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, default="")  # 该事件的标题（取最优质文章的标题）
    summary: Mapped[str] = mapped_column(Text, default="")  # 合并后的事件摘要
    topic: Mapped[str] = mapped_column(String(128), default="")  # 话题名称，用于趋势分析
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 最早文章出现时间
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 最晚文章出现时间
    source_count: Mapped[int] = mapped_column(Integer, default=0)  # 涉及的不同源数量
    article_count: Mapped[int] = mapped_column(Integer, default=0)  # 文章总数
    avg_signal: Mapped[float] = mapped_column(Float, default=0.0)  # 平均信号评分
    is_trending: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否正在升温（趋势）

    articles = relationship(
        "ClusterArticle", back_populates="cluster", lazy="selectin"
    )


class ClusterArticle(Base):
    """聚类-文章关联表。"""
    __tablename__ = "cluster_articles"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id"), primary_key=True
    )
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否为该 cluster 的主文章（信号分最高）

    cluster = relationship("Cluster", back_populates="articles")
    article = relationship("Article", back_populates="cluster_links")
