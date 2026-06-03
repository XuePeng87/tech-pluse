"""采集流水线用的轻量数据类，在采集、去重、处理层之间传递。"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.utils.text import normalize_url


@dataclass
class RawArticle:
    """采集到的原始文章，尚未入库。

    URL 在初始化时自动规范化（去除跟踪参数、转小写）。
    """
    source_id: uuid.UUID     # 数据源 ID
    title: str               # 标题
    url: str                 # 文章链接（已规范化）
    content: str = ""        # 正文（可选）
    excerpt: str = ""        # RSS 自带的摘要
    author: str = ""         # 作者
    published_at: datetime | None = None  # 源站发布时间
    raw_data: dict = field(default_factory=dict)  # 原始数据，调试用

    def __post_init__(self):
        self.url = normalize_url(self.url)
