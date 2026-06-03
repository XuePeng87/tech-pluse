"""文章模型 — 存储抓取到的原始文章及 LLM 处理结果。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, Index
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Article(Base):
    """文章表。"""
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)  # 来源 ID
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 文章标题
    url: Mapped[str] = mapped_column(String(768), nullable=False, unique=True)  # 文章链接（去重键）
    content: Mapped[str] = mapped_column(Text, default="")  # 正文内容（如抓取到全文）
    excerpt: Mapped[str] = mapped_column(Text, default="")  # RSS/Feed 自带的摘要
    author: Mapped[str] = mapped_column(Text, default="")  # 作者
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 源站发布时间
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 我们抓取的时间
    embedding: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 向量嵌入（预留，后续去重用）
    summary: Mapped[str] = mapped_column(Text, default="")  # LLM 生成的 2-3 句摘要
    category: Mapped[str] = mapped_column(String(32), default="")  # LLM 分类的主分类
    subcategories: Mapped[list] = mapped_column(JSON, default=list)  # LLM 分类的子标签
    signal_score: Mapped[float] = mapped_column(Float, default=0.0)  # 信号评分 0-1，越高越有价值
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已 LLM 处理
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)  # 原始 feed/API 数据（调试用）

    source = relationship("Source", back_populates="articles", lazy="selectin")
    cluster_links = relationship(
        "ClusterArticle", back_populates="article", lazy="selectin"
    )

    # 索引：url 去重索引、分类筛选、处理队列过滤
    __table_args__ = (
        Index("ix_articles_url", "url", unique=True),
        Index("ix_articles_published", "published_at", mysql_length=None),
        Index("ix_articles_category", "category"),
        Index("ix_articles_processed", "is_processed"),
    )
