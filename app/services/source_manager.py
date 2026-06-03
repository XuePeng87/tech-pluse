"""数据源管理：CRUD 操作 + 默认源预置。

首次启动时自动插入 30 个高信号源（分 6 个领域），后续不重复插入。
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source

logger = logging.getLogger(__name__)

# 预置的高信号数据源（按领域分组）
DEFAULT_SOURCES = [
    # 🔥 综合/资讯聚合
    {
        "name": "Hacker News (Best)",
        "url": "https://hnrss.org/best",
        "fetch_method": "rss",
        "weight": 1.3,        # 社区精选，质量最高
        "reliability": 0.85,
    },
    {
        "name": "Hacker News (New)",
        "url": "https://hnrss.org/newest?points=100",
        "fetch_method": "rss",
        "weight": 1.0,        # 新文章，points>=100 过滤低质
        "reliability": 0.7,
    },
    {
        "name": "Lobsters",
        "url": "https://lobste.rs/rss",
        "fetch_method": "rss",
        "weight": 1.1,
        "reliability": 0.8,
    },
    {
        "name": "InfoQ",
        "url": "https://www.infoq.com/feed",
        "fetch_method": "rss",
        "weight": 0.9,
        "reliability": 0.7,
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.7,
    },

    # 🛠️ 技术博客（经典必读）
    {
        "name": "Martin Fowler",
        "url": "https://martinfowler.com/feed.atom",
        "fetch_method": "rss",
        "weight": 1.4,        # 架构设计权威
        "reliability": 0.9,
    },
    {
        "name": "Coding Horror",
        "url": "https://blog.codinghorror.com/rss/",
        "fetch_method": "rss",
        "weight": 1.1,
        "reliability": 0.8,
    },
    {
        "name": "High Scalability",
        "url": "http://highscalability.com/rss/",
        "fetch_method": "rss",
        "weight": 1.3,        # 系统架构深度分析
        "reliability": 0.85,
    },
    {
        "name": "Smashing Magazine",
        "url": "https://www.smashingmagazine.com/feed/",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.75,
    },
    {
        "name": "Joel on Software",
        "url": "https://www.joelonsoftware.com/feed/",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.75,
    },
    {
        "name": "Scott Hanselman",
        "url": "https://feeds.hanselmanminutes.com/ScottHanselman",
        "fetch_method": "rss",
        "weight": 0.9,
        "reliability": 0.7,
    },

    # 🏗️ 大厂技术团队博客
    {
        "name": "Netflix Tech Blog",
        "url": "https://netflixtechblog.com/feed",
        "fetch_method": "rss",
        "weight": 1.3,        # 工程实践标杆
        "reliability": 0.85,
    },
    {
        "name": "AWS Blog",
        "url": "https://aws.amazon.com/blogs/aws/feed/",
        "fetch_method": "rss",
        "weight": 1.2,
        "reliability": 0.8,
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "fetch_method": "rss",
        "weight": 1.4,        # AI 前沿权威
        "reliability": 0.9,
    },
    {
        "name": "Meta Engineering",
        "url": "https://engineering.fb.com/feed/",
        "fetch_method": "rss",
        "weight": 1.2,
        "reliability": 0.8,
    },
    {
        "name": "Cloudflare Blog",
        "url": "https://blog.cloudflare.com/rss/",
        "fetch_method": "rss",
        "weight": 1.1,
        "reliability": 0.8,
    },
    {
        "name": "GitHub Blog",
        "url": "https://github.blog/feed/",
        "fetch_method": "rss",
        "weight": 1.1,
        "reliability": 0.8,
    },
    {
        "name": "Vercel Blog",
        "url": "https://vercel.com/blog/rss.xml",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.75,
    },
    {
        "name": "Uber Engineering",
        "url": "https://eng.uber.com/rss/",
        "fetch_method": "rss",
        "weight": 1.2,
        "reliability": 0.8,
    },

    # 🐧 Linux / 运维 / DevOps
    {
        "name": "Linux Kernel",
        "url": "https://www.kernel.org/feeds/kdist.xml",
        "fetch_method": "rss",
        "weight": 0.8,
        "reliability": 0.95,
    },
    {
        "name": "Ars Technica",
        "url": "https://arstechnica.com/feed/",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.75,
    },
    {
        "name": "Kubernetes Blog",
        "url": "https://kubernetes.io/feed.xml",
        "fetch_method": "rss",
        "weight": 1.1,
        "reliability": 0.8,
    },

    # 🎯 中文技术源
    {
        "name": "阮一峰的网络日志",
        "url": "https://www.ruanyifeng.com/blog/atom.xml",
        "fetch_method": "rss",
        "weight": 1.2,        # 中文技术科普标杆
        "reliability": 0.85,
    },
    {
        "name": "酷壳 - CoolShell",
        "url": "https://coolshell.cn/feed",
        "fetch_method": "rss",
        "weight": 1.2,
        "reliability": 0.85,
    },
    {
        "name": "HelloGitHub",
        "url": "https://hellogithub.com/rss",
        "fetch_method": "rss",
        "weight": 1.0,
        "reliability": 0.75,
    },
    {
        "name": "OSCHINA",
        "url": "https://www.oschina.net/news/rss",
        "fetch_method": "rss",
        "weight": 0.8,
        "reliability": 0.65,
    },
    {
        "name": "36氪",
        "url": "https://36kr.com/feed",
        "fetch_method": "rss",
        "weight": 0.9,
        "reliability": 0.65,
    },

    # 🔬 AI / 前沿
    {
        "name": "OpenAI Blog",
        "url": "https://openai.com/blog/rss.xml",
        "fetch_method": "rss",
        "weight": 1.5,        # AI 领域最高信号
        "reliability": 0.9,
    },
    {
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/news/rss",
        "fetch_method": "rss",
        "weight": 1.5,
        "reliability": 0.9,
    },
    {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "fetch_method": "rss",
        "weight": 1.3,
        "reliability": 0.85,
    },
    {
        "name": "DeepMind Blog",
        "url": "https://deepmind.google/blog/rss.xml",
        "fetch_method": "rss",
        "weight": 1.5,
        "reliability": 0.9,
    },
]


async def seed_default_sources(db: AsyncSession):
    """插入默认数据源（仅在表为空时执行）。"""
    result = await db.execute(select(Source))
    existing = result.scalars().all()
    if existing:
        logger.info(f"数据源已存在（{len(existing)} 个），跳过初始化")
        return

    for data in DEFAULT_SOURCES:
        source = Source(
            id=uuid.uuid4(),
            name=data["name"],
            url=data["url"],
            fetch_method=data["fetch_method"],
            weight=data.get("weight", 1.0),
            reliability=data.get("reliability", 0.5),
            config=data.get("config", {}),
        )
        db.add(source)
    await db.flush()
    logger.info(f"预置 {len(DEFAULT_SOURCES)} 个默认数据源")
