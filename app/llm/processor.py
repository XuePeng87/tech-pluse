"""LLM 处理器：批量处理文章，生成摘要、分类、信号分。

优先调用本地 Ollama（关闭思考模式），失败时回退到线上 DeepSeek。
"""
import httpx
import json
import logging
import re

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

# 每批处理的文章数
BATCH_SIZE = 5


class ArticleAnalysis(BaseModel):
    """LLM 结构化输出：单篇文章分析结果。"""
    summary: str = Field(description="2-3句核心摘要")
    category: str = Field(description="主分类")
    keywords: list[str] = Field(description="3-5个关键词")
    entities: list[str] = Field(description="2-4个命名实体")
    signal: str = Field(description="信号评级：high/medium/low")


class BatchAnalysisResult(BaseModel):
    """LLM 结构化输出：批量分析结果包装。"""
    results: list[ArticleAnalysis] = Field(description="文章分析结果列表")


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
    """从 LLM 原始响应中提取 JSON 数组。"""
    match = re.search(r'```json\s*(\[[\s\S]*?\])\s*```', text)
    if not match:
        match = re.search(r'```\s*(\[[\s\S]*?\])\s*```', text)
    if not match:
        match = re.search(r'\[[\s\S]*\]', text)

    if match:
        json_str = match.group(1) if match.lastindex else match.group(0)
        return json.loads(json_str)

    return json.loads(text)


class Processor:
    """LLM 处理器：批量处理未处理的文章。

    调用策略：先尝试本地 Ollama（关闭思考），失败后回退到线上 DeepSeek。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._local_ok = True

    async def _call_llm(self, messages: list) -> BatchAnalysisResult:
        """调用 LLM，优先本地，失败回退线上。"""
        if self._local_ok:
            try:
                raw_text = await self._invoke_local(messages)
                return self._parse_to_result(raw_text)
            except Exception as e:
                logger.warning(f"本地 LLM 调用失败，回退到线上: {e}")
                self._local_ok = False

        remote_llm = _build_remote_llm()
        structured_llm = remote_llm.with_structured_output(BatchAnalysisResult)
        result = await structured_llm.ainvoke(messages)
        return result

    async def _invoke_local(self, messages: list) -> str:
        """调用本地 Ollama 原生 API，关闭思考模式。"""
        base = settings.ollama_base_url.rstrip("/").removesuffix("/v1")
        ollama_url = f"{base}/api/chat"

        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": role, "content": content} for role, content in messages],
            "stream": False,
            "think": False,
            "temperature": 0.5,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(ollama_url, json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

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
            .limit(500)
        )
        return list(result.all())

    async def _process_batch(
        self, batch: list[tuple[Article, Source]]
    ) -> None:
        """处理一批文章。"""
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

        result = await self._call_llm(messages)

        for (article, source), analysis in zip(batch, result.results):
            article.summary = analysis.summary
            article.category = analysis.category
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
        """
        base = source.reliability * 0.5
        llm_score = SIGNAL_SCORES.get(llm_signal, 0.5) * 0.3
        return min(1.0, base + llm_score)
