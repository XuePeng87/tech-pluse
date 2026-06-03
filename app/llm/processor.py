"""LLM 处理器：批量处理文章，生成摘要、分类、信号分。

优先调用本地 Ollama，失败时回退到线上 DeepSeek。
"""
import json
import logging
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.article import Article
from app.models.source import Source
from app.llm.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# 信号评级映射到数值分
SIGNAL_SCORES = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.2,
}

# 每批处理的文章数（控制 LLM 调用成本）
BATCH_SIZE = 5


class ArticleAnalysis(BaseModel):
    """LLM 结构化输出：单篇文章分析结果。"""
    summary: str = Field(description="2-3句核心摘要")
    category: str = Field(description="主分类")
    keywords: list[str] = Field(description="3-5个关键词（TF-IDF风格，代表核心主题）")
    entities: list[str] = Field(description="2-4个命名实体（具体技术名词）")
    signal: str = Field(description="信号评级：high/medium/low")


class BatchAnalysisResult(BaseModel):
    """LLM 结构化输出：批量分析结果包装。"""
    results: list[ArticleAnalysis] = Field(description="文章分析结果列表")


def _build_llm():
    """创建本地 Ollama LLM 实例。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        api_key="ollama",  # Ollama 不校验 API key
        temperature=0.5,
        timeout=120,
    )


def _build_remote_llm():
    """创建线上 DeepSeek LLM 实例（备用回退）。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0.5,
        timeout=30,
    )


def _parse_json_response(text: str) -> list[dict]:
    """从 LLM 原始响应中提取 JSON 数组。

    Ollama 模型可能返回 markdown 代码块包裹的 JSON，
    或直接在文本中包含 JSON。尝试多种解析方式。
    """
    # 尝试提取 ```json ... ``` 包裹的内容
    match = re.search(r'```json\s*(\[[\s\S]*?\])\s*```', text)
    if not match:
        # 尝试提取 ``` 包裹的内容
        match = re.search(r'```\s*(\[[\s\S]*?\])\s*```', text)
    if not match:
        # 尝试直接查找文本中的 JSON 数组
        match = re.search(r'\[[\s\S]*\]', text)

    if match:
        json_str = match.group(1) if match.lastindex else match.group(0)
        return json.loads(json_str)

    return json.loads(text)


class Processor:
    """LLM 处理器：批量处理未处理的文章。

    调用策略：先尝试本地 Ollama，失败后回退到线上 DeepSeek。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = _build_llm()
        self._local_ok = True  # 标记本地是否可用，避免每次都重试失败

    async def _call_llm(self, messages: list) -> BatchAnalysisResult:
        """调用 LLM，优先本地，失败回退线上。"""
        # 优先用本地 Ollama
        if self._local_ok:
            try:
                raw_text = await self._invoke_local(messages)
                return self._parse_to_result(raw_text)
            except Exception as e:
                logger.warning(f"本地 LLM 调用失败，回退到线上: {e}")
                self._local_ok = False

        # 回退到线上 DeepSeek（带结构化输出）
        remote_llm = _build_remote_llm()
        structured_llm = remote_llm.with_structured_output(BatchAnalysisResult)
        result = await structured_llm.ainvoke(messages)
        return result

    async def _invoke_local(self, messages: list) -> str:
        """调用本地 Ollama，返回原始文本。"""
        result = await self.llm.ainvoke(messages)
        return result.content

    def _parse_to_result(self, text: str) -> BatchAnalysisResult:
        """解析本地 Ollama 返回的 JSON 为结构化结果。"""
        items = _parse_json_response(text)
        analyses = [ArticleAnalysis(**item) for item in items]
        return BatchAnalysisResult(results=analyses)

    async def process_all(self) -> int:
        """处理所有未处理的文章。

        每批独立 commit，避免单批失败导致全部回滚。
        返回成功处理的文章数量。
        """
        articles = await self._get_unprocessed()
        if not articles:
            logger.info("没有待处理的文章")
            return 0

        logger.info(f"开始处理 {len(articles)} 篇文章")
        processed_count = 0

        # 分批处理（5 篇/次），每批独立 commit
        for i in range(0, len(articles), BATCH_SIZE):
            batch = articles[i:i + BATCH_SIZE]
            try:
                await self._process_batch(batch)
                await self.db.commit()
                processed_count += len(batch)
                logger.info(f"批次完成: {processed_count}/{len(articles)}")
            except Exception as e:
                await self.db.rollback()
                logger.error(f"批次处理失败 (批次 {i//BATCH_SIZE + 1}): {e}", exc_info=True)

        logger.info(f"处理完成: {processed_count} 篇文章")
        return processed_count

    async def _get_unprocessed(self) -> list[tuple[Article, Source]]:
        """查询所有未处理的文章及其数据源。"""
        result = await self.db.execute(
            select(Article, Source)
            .join(Source, Article.source_id == Source.id)
            .where(Article.is_processed == False)
            .limit(500)  # 每次最多处理 500 篇，防止内存爆炸
        )
        return list(result.all())

    async def _process_batch(
        self, batch: list[tuple[Article, Source]]
    ) -> None:
        """处理一批文章。

        1. 构建批量输入文本
        2. 调用 LLM 结构化输出
        3. 更新文章字段（summary, category, subcategories, signal_score）
        """
        # 构建输入文本
        articles_text = ""
        for idx, (article, source) in enumerate(batch, 1):
            articles_text += (
                f"文章 {idx}:\n"
                f"标题: {article.title}\n"
                f"摘要: {article.excerpt}\n"
                f"源: {source.name}\n"
                f"---\n"
            )

        prompt = USER_PROMPT_TEMPLATE.format(
            count=len(batch),
            articles_text=articles_text,
        )

        messages = [
            ("system", SYSTEM_PROMPT),
            ("user", prompt),
        ]

        # 调用 LLM（优先本地，失败回退线上）
        result = await self._call_llm(messages)

        # 更新文章
        for (article, source), analysis in zip(batch, result.results):
            article.summary = analysis.summary
            article.category = analysis.category
            # 合并关键词 + 实体（去重，取前8个）
            merged = list(dict.fromkeys(analysis.keywords + analysis.entities))
            article.subcategories = merged[:8]
            article.signal_score = self._calculate_signal(
                source, analysis.signal
            )
            article.is_processed = True

        await self.db.flush()

    def _calculate_signal(
        self, source: Source, llm_signal: str
    ) -> float:
        """计算信号分。

        公式: source_reliability × 0.5 + llm_signal × 0.3 + cross_source_boost × 0.2
        - source_reliability: 数据源可信度（0-1）
        - llm_signal: LLM 评级映射到数值（high=1.0, medium=0.5, low=0.2）
        - cross_source_boost: 跨源确认加分（后续计算）
        """
        base = source.reliability * 0.5
        llm_score = SIGNAL_SCORES.get(llm_signal, 0.5) * 0.3
        return min(1.0, base + llm_score)
