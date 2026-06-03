"""管理后台：数据源 CRUD + 手动触发采集。"""
import logging
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, desc, func, select
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
    """管理首页：数据源列表 + 操作按钮。"""
    sources = (await db.execute(select(Source).order_by(Source.name))).scalars().all()

    rows = ""
    for s in sources:
        status = '<span class="active">活跃</span>' if s.is_active else '<span class="inactive">已停用</span>'
        last = s.last_fetch.strftime("%Y-%m-%d %H:%M") if s.last_fetch else "从未"
        rows += f"""<tr>
            <td><strong>{s.name}</strong></td>
            <td>{s.fetch_method}</td>
            <td>{s.reliability}</td>
            <td>{s.weight}</td>
            <td>{status}</td>
            <td>{last}</td>
            <td>{s.fetch_errors}</td>
            <td>
                <a href="/admin/edit/{s.id}" style="font-size:12px">编辑</a>
                &middot;
                <a href="/admin/disable/{s.id}" style="color:#dc3545;font-size:12px">停用</a>
                &middot;
                <a href="/admin/enable/{s.id}" style="color:#2e7d32;font-size:12px">启用</a>
                &middot;
                <a href="/admin/delete/{s.id}" style="color:#dc3545;font-size:12px">删除</a>
            </td>
        </tr>"""

    content = f"""
    <div class="header">
        <h1>管理后台</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/">返回首页</a></p>
    </div>

    <div class="section">
        <a class="btn" href="/admin/collect" style="margin-right:8px">手动触发采集</a>
        <a class="btn" href="/admin/new">新增数据源</a>
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


def _source_form_html(action: str, name: str = "", url: str = "", fetch_method: str = "rss",
                     reliability: str = "0.5", weight: str = "1.0", is_active: bool = True,
                     config: str = "") -> str:
    """渲染数据源表单 HTML。"""
    active_checked = 'checked' if is_active else ''
    return f"""
    <form method="post" action="{action}">
        <div class="form-row">
            <label>名称</label>
            <input type="text" name="name" value="{name}" required style="width:300px" />
        </div>
        <div class="form-row">
            <label>URL</label>
            <input type="text" name="url" value="{url}" required style="width:500px" />
        </div>
        <div class="form-row">
            <label>抓取方式</label>
            <select name="fetch_method">
                <option value="rss"{" selected" if fetch_method == "rss" else ""}>RSS/Feed</option>
                <option value="api"{" selected" if fetch_method == "api" else ""}>API</option>
                <option value="html"{" selected" if fetch_method == "html" else ""}>HTML 抓取</option>
            </select>
        </div>
        <div class="form-row">
            <label>可信度</label>
            <input type="number" name="reliability" value="{reliability}" min="0" max="1" step="0.05" style="width:80px" />
            <span style="font-size:12px;color:#999;margin-left:8px">0-1，越高越可信</span>
        </div>
        <div class="form-row">
            <label>权重倍数</label>
            <input type="number" name="weight" value="{weight}" min="0.1" max="5" step="0.1" style="width:80px" />
            <span style="font-size:12px;color:#999;margin-left:8px">影响文章信号分</span>
        </div>
        <div class="form-row">
            <label>配置 (JSON)</label>
            <input type="text" name="config" value="{config}" style="width:500px" placeholder='{{"key": "value"}}' />
        </div>
        <div class="form-row">
            <label>状态</label>
            <label style="width:auto"><input type="checkbox" name="is_active" {active_checked} /> 启用</label>
        </div>
        <div class="form-row">
            <label></label>
            <button type="submit" class="btn">保存</button>
        </div>
    </form>"""


@router.get("/new", response_class=HTMLResponse)
async def source_new_page():
    """新增数据源页面。"""
    content = f"""
    <div class="header">
        <h1>新增数据源</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/admin">返回列表</a></p>
    </div>
    <div class="section">
        <h2>填写信息</h2>
        {_source_form_html("/admin/new")}
    </div>
    """
    return BASE.format(style=STYLE, content=content)


@router.post("/new")
async def source_create(
    name: str = Form(...),
    url: str = Form(...),
    fetch_method: str = Form("rss"),
    reliability: float = Form(0.5),
    weight: float = Form(1.0),
    is_active: bool = Form(False),
    config: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """创建数据源。"""
    import json

    cfg = {}
    if config.strip():
        try:
            cfg = json.loads(config)
        except json.JSONDecodeError:
            return _msg_page("新增失败", f"配置 JSON 格式有误: {config[:100]}", False)

    existing = (await db.execute(select(Source).where(Source.url == url))).scalar()
    if existing:
        return _msg_page("新增失败", f"URL 已存在: {existing.name}", False)

    source = Source(
        name=name,
        url=url,
        fetch_method=fetch_method,
        reliability=reliability,
        weight=weight,
        is_active=is_active,
        config=cfg,
    )
    db.add(source)
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/edit/{source_id}", response_class=HTMLResponse)
async def source_edit_page(source_id: str, db: AsyncSession = Depends(get_db)):
    """编辑数据源页面。"""
    source = (await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))).scalar()
    if not source:
        return _msg_page("未找到", "数据源不存在", False)

    import json
    config_str = json.dumps(source.config) if source.config else ""

    content = f"""
    <div class="header">
        <h1>编辑: {source.name}</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/admin">返回列表</a></p>
    </div>
    <div class="section">
        {_source_form_html(f"/admin/edit/{source_id}",
                          name=source.name, url=source.url,
                          fetch_method=source.fetch_method,
                          reliability=str(source.reliability),
                          weight=str(source.weight),
                          is_active=source.is_active,
                          config=config_str)}
    </div>
    """
    return BASE.format(style=STYLE, content=content)


@router.post("/edit/{source_id}")
async def source_update(
    source_id: str,
    name: str = Form(...),
    url: str = Form(...),
    fetch_method: str = Form("rss"),
    reliability: float = Form(0.5),
    weight: float = Form(1.0),
    is_active: bool = Form(False),
    config: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """更新数据源。"""
    import json

    source = (await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))).scalar()
    if not source:
        return _msg_page("未找到", "数据源不存在", False)

    cfg = {}
    if config.strip():
        try:
            cfg = json.loads(config)
        except json.JSONDecodeError:
            return _msg_page("更新失败", f"配置 JSON 格式有误: {config[:100]}", False)

    source.name = name
    source.url = url
    source.fetch_method = fetch_method
    source.reliability = reliability
    source.weight = weight
    source.is_active = is_active
    source.config = cfg
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/delete/{source_id}", response_class=HTMLResponse)
async def source_delete_page(source_id: str, db: AsyncSession = Depends(get_db)):
    """删除确认页面。"""
    source = (await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))).scalar()
    if not source:
        return _msg_page("未找到", "数据源不存在", False)

    content = f"""
    <div class="header">
        <h1>删除数据源</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/admin">返回列表</a></p>
    </div>
    <div class="section">
        <p>确定要删除 <strong>{source.name}</strong> 吗？</p>
        <p style="font-size:13px;color:#999;margin-top:8px">此操作会同时删除该源下的所有文章数据。</p>
        <form method="post" action="/admin/delete/{source_id}" style="margin-top:16px">
            <button type="submit" class="btn btn-danger">确认删除</button>
            <a href="/admin" style="margin-left:12px">取消</a>
        </form>
    </div>
    """
    return BASE.format(style=STYLE, content=content)


@router.post("/delete/{source_id}")
async def source_delete(source_id: str, db: AsyncSession = Depends(get_db)):
    """删除数据源及其关联数据。

    外键依赖链: cluster_articles → articles → source
    按从底到顶顺序清理。
    """
    source = (await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))).scalar()
    if not source:
        return _msg_page("未找到", "数据源不存在", False)

    from app.models.article import Article
    from app.models.cluster import ClusterArticle

    sid = uuid.UUID(source_id)

    # 1. 先删 cluster_articles（该源文章的聚类关联）
    sub_q = select(Article.id).where(Article.source_id == sid)
    await db.execute(
        delete(ClusterArticle).where(ClusterArticle.article_id.in_(sub_q))
    )

    # 2. 再删 articles
    await db.execute(delete(Article).where(Article.source_id == sid))

    # 3. 最后删 source
    await db.delete(source)
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


def _msg_page(title: str, msg: str, ok: bool) -> str:
    """渲染消息页面。"""
    cls = "msg-ok" if ok else "msg-err"
    content = f"""
    <div class="header">
        <h1>{title}</h1>
        <p style="font-size:13px;color:#666;margin-top:4px"><a href="/admin">返回管理</a></p>
    </div>
    <div class="section">
        <div class="msg {cls}">{msg}</div>
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
    result = await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
    source = result.scalar_one()
    source.is_active = False
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/enable/{source_id}")
async def enable_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """启用数据源。"""
    result = await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
    source = result.scalar_one()
    source.is_active = True
    source.fetch_errors = 0
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)
