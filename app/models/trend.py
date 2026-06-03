"""趋势模型 — 记录正在升温的技术话题。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Trend(Base):
    """趋势表：基于关键词词频的四维度趋势检测。"""
    __tablename__ = "trends"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)  # 话题/关键词名称
    category: Mapped[str] = mapped_column(String(32), default="")  # 所属主分类
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # 首次检测时间
    window_start: Mapped[datetime] = mapped_column(DateTime)  # 当前分析窗口起始
    window_end: Mapped[datetime] = mapped_column(DateTime)  # 当前分析窗口结束
    article_count: Mapped[int] = mapped_column(Integer, default=0)  # 当前窗口文章数
    source_count: Mapped[int] = mapped_column(Integer, default=0)  # 当前窗口涉及源数量
    velocity: Mapped[float] = mapped_column(Float, default=0.0)  # 增速（文章/小时）
    prev_article_count: Mapped[int] = mapped_column(Integer, default=0)  # 前一窗口文章数
    growth_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 周环比增长率
    burst_score: Mapped[float] = mapped_column(Float, default=0.0)  # 爆发分 (Z-score)
    cross_source_boost: Mapped[float] = mapped_column(Float, default=0.0)  # 跨源加权分
    signal: Mapped[float] = mapped_column(Float, default=0.0)  # 综合信号分
    status: Mapped[str] = mapped_column(String(16), default="hot")  # 趋势状态: hot/cooling/sustained
    days_active: Mapped[int] = mapped_column(Integer, default=0)  # 持续活跃天数
    last_check_at: Mapped[datetime] = mapped_column(DateTime)  # 上次状态检查时间
    summary: Mapped[str] = mapped_column(Text, default="")  # LLM 生成的趋势摘要
