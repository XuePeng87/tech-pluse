# Tech Pluse

Daily Tech Intelligence Aggregator — 自动采集、去重、聚类、LLM 分析、趋势检测。

## Features

- **多源采集** — 31+ 个 RSS/Feed 源（GitHub Blog, TechCrunch, 36氪, Hacker News, Lobsters 等）
- **智能去重** — URL 去重 + Jaccard 标题相似度 + 语义聚类
- **LLM 分析** — 自动摘要生成、14 类分类、关键词/实体抽取、信号评分（0-1）
- **趋势检测** — 四维评分（增长率 + 爆发 Z-score + 跨源验证 + 基础频次）
- **零 JS 前端** — 纯服务端渲染，内联 SVG 图表

## Architecture

```
RSS/Feed Sources
      │
      ▼
  Collector ──→ Dedup Engine ──→ Cluster (事件级聚合)
                                      │
                                      ▼
                                LLM Processor (Ollama / DeepSeek)
                                      │
                                      ▼
                                Trend Detector (四维度评分)
                                      │
                                      ▼
                                Dashboard (FastAPI + SVG)
```

## Tech Stack

| Layer | Stack |
|---|---|
| Web | FastAPI, uvicorn |
| Database | MySQL 8.0 + aiomysql (async) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Scheduler | APScheduler (15min 采集 / 30min LLM / 4h 趋势) |
| LLM | DeepSeek via DashScope / Ollama (本地回退) |
| Frontend | 纯 HTML + 内联 SVG 图表，零 JS 依赖 |

## Data Models

| 表 | 说明 |
|---|---|
| `sources` | RSS/Feed 数据源配置 |
| `articles` | 文章（标题、摘要、LLM 分类、信号分） |
| `clusters` | 话题聚类（语义聚合的同类文章） |
| `cluster_articles` | Cluster 与 Article 的关联 |
| `trends` | 趋势（四维评分 + 状态机） |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/XuePeng87/tech-pluse.git
cd tech-pluse

# 2. Install
pip install -e .

# 3. Config
cp .env.example .env
# Edit .env: set DATABASE_URL and DEEPSEEK_API_KEY

# 4. Create database
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS \`tech-pluse\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

# 5. Migrate
alembic upgrade head

# 6. Run
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 to view the dashboard.

## Local LLM (Optional)

Supports local Ollama as primary LLM with automatic fallback to remote DeepSeek API:

```bash
# Install Ollama and run a local model
ollama run deepseek-r1:7b

# The processor will use Ollama automatically (think disabled for speed).
# If Ollama is unavailable, it falls back to DeepSeek API.
```

## Dashboard

- **趋势** — 趋势列表（含评分算法说明），点击查看详情
- **文章** — 按信号分/分类/关键词搜索
- **话题** — 聚类话题，点击进入详情查看相关文章
- **统计** — 全局数据可视化（分类分布、话题 Top 10、日新增趋势、源贡献、信号分布）

## License

MIT
