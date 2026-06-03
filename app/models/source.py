"""数据源模型 — 配置要抓取的信息源。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    """数据源配置表。"""
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # 源名称，如 "Hacker News"
    url: Mapped[str] = mapped_column(String(512), nullable=False)  # RSS 地址或网页 URL
    fetch_method: Mapped[str] = mapped_column(String(16), nullable=False, default="rss")  # 抓取方式：rss / api / html
    reliability: Mapped[float] = mapped_column(Float, default=0.5)  # 可信度评分 0-1，每周自动评估调整
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # 信号权重倍数，影响文章最终评分
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否启用，连续失败 5 次自动停用
    last_fetch: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 上次成功抓取时间
    fetch_errors: Mapped[int] = mapped_column(Integer, default=0)  # 连续失败次数
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # 扩展配置，如 API key、parser 类型等

    articles = relationship("Article", back_populates="source", lazy="selectin")
