"""LLM Prompt 模板。"""

# 系统提示词：定义 LLM 的角色和输出格式
SYSTEM_PROMPT = """你是科技情报分析师。你的任务是分析科技文章，提取核心价值。

请为每篇文章输出以下信息：
- summary: 2-3句核心摘要，聚焦技术实质（功能、原理、影响），不要营销话术
- category: 从以下14个类别中选择一个：
  AI/ML, DevTools, Security, Infrastructure, Cloud, Programming Languages,
  Web Development, Data Engineering, Quantum Computing, Robotics, Biotech,
  Fintech, Open Source, DevOps/SRE
- keywords: 3-5个关键词（TF-IDF风格，代表文章核心主题的高信息量词汇）
- entities: 2-4个命名实体（具体技术名词，如 "Kubernetes", "Rust", "RAG", "LoRA"）
- signal: 信号评级，high（重大进展/突破）/ medium（有价值更新）/ low（日常新闻/营销内容）

合并规则：subcategories = keywords + entities（去重后取前8个），去重合并为统一标签列表。

只关注技术实质，忽略 PR 包装和炒作语言。"""

# 用户提示词模板：批量输入多篇文章
USER_PROMPT_TEMPLATE = """分析以下{count}篇文章：

{articles_text}

请以 JSON 数组形式返回，每个对象包含：
{{
  "summary": "2-3句摘要",
  "category": "分类",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "entities": ["技术实体1", "技术实体2"],
  "signal": "high|medium|low"
}}

必须返回正好{count}个对象，顺序与输入一致。"""

# 趋势摘要 Prompt
TREND_SUMMARY_PROMPT = """以下{source_count}个独立信源在讨论同一话题："{topic}"。

请用2-3句话总结这个趋势：
1. 正在发生什么
2. 为什么现在值得关注
3. 关键技术影响

相关文章：
{articles_text}
"""
