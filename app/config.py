"""应用配置：通过 pydantic-settings 从环境变量/.env 读取。"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """所有配置项，支持环境变量和 .env 文件。"""

    # ===== 数据库 =====
    database_url: str = "mysql+aiomysql://root:Snow103082..@localhost:3306/tech-pluse"

    # ===== LLM：本地 Ollama（优先） =====
    ollama_model: str = "deepseek-r1:7b"
    ollama_base_url: str = "http://localhost:11434/v1"

    # ===== LLM：线上 DeepSeek（备用回退） =====
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

    # ===== Embeddings（预留，后续去重用） =====
    embedding_provider: str = "openai"  # openai | local
    embedding_dimensions: int = 512

    # ===== 采集配置 =====
    collection_interval_minutes: int = 15   # 采集间隔（分钟）
    collection_start_hour: int = 6          # 每天开始时间（6 点）
    collection_end_hour: int = 22           # 每天结束时间（22 点）
    max_concurrent_requests: int = 10       # 最大并发请求数
    request_timeout_seconds: int = 15       # 单个请求超时（秒）

    # ===== 去重配置 =====
    similarity_threshold: float = 0.85      # embedding 相似度阈值（预留）
    dedup_window_hours: int = 48            # 去重对比窗口（小时）

    # ===== 趋势检测 =====
    trend_window_hours: int = 12            # 趋势分析窗口（小时）
    trend_velocity_threshold: float = 3.0   # 触发趋势的最低速度（篇/小时）
    trend_min_sources: int = 2              # 最少需要多少个独立源

    # ===== Dashboard =====
    articles_per_page: int = 20             # 每页文章数
    default_min_signal_score: float = 0.3   # 默认最低信号分

    # ===== LLM 成本控制 =====
    llm_daily_budget_usd: float = 5.0       # 每日 LLM API 预算上限

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
