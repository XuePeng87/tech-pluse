"""管理后台：数据源管理 + 手动触发采集。"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.source import Source
from app.services.collector import Collector
from app.services.dedup import DedupEngine

router = APIRouter(prefix="/admin")
logger = logging.getLogger(__name__)

# 极简管理页面模板
STYLE = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: -apple-system, "SF Pro Text", sans-serif;
        background: #fafafa;
        color: #1a1a1a;
        max-width: 900px;
        margin: 0 auto;
        padding: 40px 20px;
        line-height: 1.6;
    }
    a { color: #0066cc; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .header {
        border-bottom: 1px solid #e5e5e5;
        padding-bottom: 16px;
        margin-bottom: 24px;
    }
    .header h1 { font-size: 20px; font-weight: 600; }
    .section { margin-bottom: 32px; }
    .section h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; }
    .btn {
        display: inline-block;
        padding: 8px 16px;
        background: #0066cc;
        color: #fff;
        border: none;
        border-radius: 6px;
        font-size: 14px;
        cursor: pointer;
        text-decoration: none;
    }
    .btn:hover { background: #0055aa; }
    .btn-danger { background: #dc3545; }
    .btn-danger:hover { background: #c82333; }
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }
    th, td {
        text-align: left;
        padding: 8px 12px;
        border-bottom: 1px solid #eee;
    }
    th { color: #666; font-weight: 500; }
    .active { color: #2e7d32; }
    .inactive { color: #c62828; }
    input, select {
        padding: 6px 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
        font-size: 13px;
    }
    .form-row { margin-bottom: 8px; }
    .form-row label { display: inline-block; width: 100px; font-size: 13px; color: #666; }
    .msg { padding: 8px 12px; border-radius: 4px; margin-bottom: 16px; font-size: 13px; }
    .msg-ok { background: #e8f5e9; color: #2e7d32; }
    .msg-err { background: #fce4ec; color: #c62828; }
</style>
"""

BASE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>管理后台 - Tech Pluse</title>
{style}
</head>
<body>{content}</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def admin_index(db: AsyncSession = Depends(get_db)):
    """管理首页：数据源列表 + 手动触发采集按钮。"""
    sources = (await db.execute(select(Source).order_by(Source.name))).scalars().all()

    rows = ""
    for s in sources:
        status = '<span class="active">活跃</span>' if s.is_active else '<span class="inactive">已停用</span>'
        last = s.last_fetch.strftime("%Y-%m-%d %H:%M") if s.last_fetch else "从未"
        rows += f"""<tr>
            <td>{s.name}</td>
            <td>{s.fetch_method}</td>
            <td>{s.reliability}</td>
            <td>{s.weight}</td>
            <td>{status}</td>
            <td>{last}</td>
            <td>{s.fetch_errors}</td>
            <td>
                <a href="/admin/disable/{s.id}" style="color:#dc3545;font-size:12px">停用</a>
                &middot;
                <a href="/admin/enable/{s.id}" style="color:#2e7d32;font-size:12px">启用</a>
            </td>
        </tr>"""

    content = f"""
    <div class="header">
        <h1>管理后台</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/">返回首页</a></p>
    </div>

    <div class="section">
        <h2>操作</h2>
        <a class="btn" href="/admin/collect">手动触发采集</a>
    </div>

    <div class="section">
        <h2>数据源 ({len(sources)})</h2>
        <table>
            <tr><th>名称</th><th>方式</th><th>可信度</th><th>权重</th><th>状态</th><th>最后采集</th><th>错误数</th><th>操作</th></tr>
            {rows}
        </table>
    </div>
    """

    return BASE.format(style=STYLE, content=content)


@router.get("/collect")
async def trigger_collect(db: AsyncSession = Depends(get_db)):
    """手动触发一次采集任务。"""
    try:
        collector = Collector()
        articles = await collector.collect_all(db)
        if not articles:
            msg = '<div class="msg msg-ok">没有新文章</div>'
        else:
            dedup = DedupEngine(db)
            processed = await dedup.process_batch(articles)
            if processed:
                count = await dedup.save_articles(processed)
                await db.commit()
                msg = f'<div class="msg msg-ok">采集成功: 新增 {count} 篇文章</div>'
            else:
                msg = '<div class="msg msg-ok">去重后无新文章</div>'
        await collector.close()
    except Exception as e:
        logger.error(f"手动采集失败: {e}", exc_info=True)
        msg = f'<div class="msg msg-err">采集失败: {str(e)[:200]}</div>'

    content = f"""
    <div class="header">
        <h1>采集结果</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/admin">返回管理</a></p>
    </div>
    <div class="section">{msg}</div>
    """

    return BASE.format(style=STYLE, content=content)


@router.get("/disable/{source_id}")
async def disable_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """停用数据源。"""
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one()
    source.is_active = False
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/enable/{source_id}")
async def enable_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """启用数据源。"""
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one()
    source.is_active = True
    source.fetch_errors = 0
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)
