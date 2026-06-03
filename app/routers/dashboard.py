"""Dashboard 路由：极简风格的 Web 界面。"""
import uuid as uuid_mod
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.article import Article
from app.models.cluster import Cluster, ClusterArticle
from app.models.source import Source
from app.models.trend import Trend

router = APIRouter()

PAGE_SIZE = 20

STATUS_LABELS = {
    "hot": "爆发",
    "emerging": "上升",
    "sustained": "持续热点",
    "cooling": "已冷却",
    "new": "新发现",
}


def _article_search_filter(q: str):
    """返回文章搜索过滤条件（不区分大小写模糊匹配）。"""
    return or_(
        Article.title.ilike(f"%{q}%"),
        Article.summary.ilike(f"%{q}%"),
        Article.excerpt.ilike(f"%{q}%"),
        Article.content.ilike(f"%{q}%"),
    )


def _cluster_search_filter(q: str):
    """返回话题搜索过滤条件（不区分大小写模糊匹配）。"""
    return or_(
        Cluster.topic.ilike(f"%{q}%"),
        Cluster.title.ilike(f"%{q}%"),
        Cluster.summary.ilike(f"%{q}%"),
    )


def _render_template(title: str, content: str, tab: str = "trends", search_q: str = "", search_action: str = "/") -> str:
    """渲染极简 HTML 模板。

    Args:
        title: 页面标题
        content: 主体内容 HTML
        tab: 当前激活的 tab
        search_q: 当前搜索关键词
        search_action: 搜索表单提交地址
    """
    search_box_html = f"""<div class="search-box">
        <form method="get" action="{search_action}">
            <input type="hidden" name="tab" value="{tab}" />
            <input type="text" name="q" value="{search_q}" placeholder="搜索文章或话题..." />
            <button type="submit">搜索</button>
        </form>
    </div>""" if tab != "cluster_detail" else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
            background: #f5f5f7;
            color: #1a1a1a;
            min-height: 100vh;
        }}

        /* ===== Header ===== */
        .header {{
            background: #fff;
            border-bottom: 1px solid #e5e5e5;
            padding: 16px 20px;
        }}
        .header-inner {{
            max-width: 960px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .header-left {{ display: flex; align-items: baseline; gap: 12px; }}
        .header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
        .header .updated {{ font-size: 12px; color: #999; }}

        /* ===== Search Box ===== */
        .search-box {{ margin-left: auto; }}
        .search-box form {{ display: flex; gap: 6px; }}
        .search-box input {{
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            width: 220px;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-box input:focus {{ border-color: #0066cc; }}
        .search-box button {{
            padding: 6px 16px;
            background: #0066cc;
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
        }}
        .search-box button:hover {{ background: #0055aa; }}

        /* ===== Search Notice ===== */
        .search-notice {{
            background: #e8f0fe;
            border: 1px solid #b8d4f8;
            border-radius: 8px;
            padding: 10px 16px;
            margin-bottom: 16px;
            font-size: 14px;
            color: #333;
        }}
        .search-notice strong {{ color: #0066cc; }}

        /* ===== Stats Cards ===== */
        .stats-bar {{
            max-width: 960px;
            margin: 20px auto 0;
            padding: 0 20px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }}
        .stat-card {{
            background: #fff;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            border: 1px solid #e8e8e8;
        }}
        .stat-card .num {{
            font-size: 28px;
            font-weight: 700;
            color: #1a1a1a;
        }}
        .stat-card .label {{
            font-size: 12px;
            color: #888;
            margin-top: 2px;
        }}

        /* ===== Tabs ===== */
        .tabs {{
            max-width: 960px;
            margin: 16px auto 0;
            padding: 0 20px;
            display: flex;
            gap: 0;
            border-bottom: 1px solid #e5e5e5;
        }}
        .tab-link {{
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 500;
            color: #888;
            text-decoration: none;
            border-bottom: 2px solid transparent;
            margin-bottom: -1px;
        }}
        .tab-link:hover {{ color: #1a1a1a; }}
        .tab-link.active {{
            color: #0066cc;
            border-bottom-color: #0066cc;
        }}

        /* ===== Content ===== */
        .content {{
            max-width: 960px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* ===== Trend Cards ===== */
        .trend-card {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
            transition: box-shadow 0.15s;
        }}
        .trend-card:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .trend-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}
        .trend-header .topic {{ font-size: 15px; font-weight: 600; }}
        .trend-summary {{
            font-size: 13px;
            color: #555;
            margin-bottom: 10px;
            line-height: 1.5;
        }}
        .trend-meta {{
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: #999;
        }}

        /* ===== Status Badges ===== */
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .badge-hot {{ background: #fff3e0; color: #e65100; }}
        .badge-emerging {{ background: #e8f5e9; color: #2e7d32; }}
        .badge-sustained {{ background: #fce4ec; color: #c62828; }}
        .badge-cooling {{ background: #e3f2fd; color: #1565c0; }}
        .badge-new {{ background: #f3e5f5; color: #7b1fa2; }}

        /* ===== Trend Topic Link ===== */
        .topic-link {{
            color: #1a1a1a;
            text-decoration: none;
        }}
        .topic-link:hover {{ color: #0066cc; text-decoration: none; }}

        /* ===== Trend Methodology ===== */
        .trend-methodology {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 12px;
        }}
        .trend-methodology h3 {{
            font-size: 13px;
            font-weight: 600;
            color: #888;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .trend-methodology-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }}
        .trend-methodology-item {{
            padding: 10px;
            background: #f9f9f9;
            border-radius: 6px;
        }}
        .trend-methodology-item .name {{
            font-size: 13px;
            font-weight: 600;
            color: #1a1a1a;
            margin-bottom: 4px;
        }}
        .trend-methodology-item .desc {{
            font-size: 11px;
            color: #888;
            line-height: 1.4;
        }}
        .trend-methodology-item .formula {{
            font-size: 11px;
            color: #0066cc;
            font-family: "SF Mono", "Fira Code", monospace;
            margin-top: 4px;
        }}
        .trend-methodology-footer {{
            font-size: 11px;
            color: #999;
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid #f0f0f0;
        }}
        .trend-state-legend {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #f0f0f0;
        }}
        .trend-state-legend-item {{
            font-size: 11px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .trend-state-dot {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}

        /* ===== Trend Detail ===== */
        .trend-detail {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 16px;
        }}
        .trend-detail-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }}
        .trend-detail-header h2 {{
            font-size: 18px;
            font-weight: 600;
            margin: 0;
        }}
        .trend-detail-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }}
        .trend-stat {{
            text-align: center;
            padding: 12px;
            background: #f9f9f9;
            border-radius: 6px;
        }}
        .trend-stat .num {{
            font-size: 24px;
            font-weight: 700;
            color: #1a1a1a;
        }}
        .trend-stat .label {{
            font-size: 11px;
            color: #999;
            margin-top: 4px;
        }}
        .trend-chart-section {{
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid #f0f0f0;
        }}
        .trend-chart-section h3 {{
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 12px;
            color: #333;
        }}
        .trend-chart-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }}
        .trend-chart-box {{
            background: #fafafa;
            border: 1px solid #eee;
            border-radius: 6px;
            padding: 12px;
        }}
        .trend-chart-box h4 {{
            font-size: 12px;
            font-weight: 600;
            color: #888;
            margin-bottom: 8px;
        }}

        /* ===== Signal Badge ===== */
        .signal {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }}
        .signal-high {{ background: #e8f5e9; color: #2e7d32; }}
        .signal-medium {{ background: #fff3e0; color: #e65100; }}
        .signal-low {{ background: #fce4ec; color: #c62828; }}

        /* ===== Article List ===== */
        .article-item {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 8px;
        }}
        .article-title {{
            font-size: 15px;
            font-weight: 500;
            margin-bottom: 6px;
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
        }}
        .article-title a {{ color: #1a1a1a; text-decoration: none; }}
        .article-title a:hover {{ color: #0066cc; }}
        .article-summary {{
            font-size: 13px;
            color: #555;
            margin-bottom: 10px;
            line-height: 1.5;
        }}
        .article-info {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .article-meta {{
            font-size: 12px;
            color: #999;
        }}
        .article-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }}
        .tag {{
            display: inline-block;
            padding: 1px 7px;
            background: #f0f0f0;
            border-radius: 3px;
            font-size: 11px;
            color: #666;
        }}

        /* ===== Filter Bar ===== */
        .filter-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
            margin-bottom: 16px;
        }}
        .filter-label {{
            font-size: 12px;
            font-weight: 600;
            color: #888;
            margin-right: 4px;
        }}
        .filter-chip {{
            padding: 3px 10px;
            border: 1px solid #ddd;
            border-radius: 12px;
            font-size: 12px;
            color: #555;
            text-decoration: none;
        }}
        .filter-chip:hover {{
            border-color: #0066cc;
            color: #0066cc;
            text-decoration: none;
        }}
        .filter-chip.active {{
            background: #0066cc;
            border-color: #0066cc;
            color: #fff;
        }}
        .filter-select {{
            padding: 3px 10px;
            border: 1px solid #ddd;
            border-radius: 12px;
            font-size: 12px;
            color: #555;
            background: #fff;
            outline: none;
            cursor: pointer;
        }}
        .filter-select:hover {{
            border-color: #0066cc;
            color: #0066cc;
        }}

        /* ===== Pagination ===== */
        .pagination {{
            display: flex;
            gap: 6px;
            align-items: center;
            padding: 20px 0 0;
            font-size: 13px;
            color: #666;
        }}
        .pagination a {{
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            text-decoration: none;
            color: #555;
        }}
        .pagination a:hover {{
            border-color: #0066cc;
            color: #0066cc;
        }}
        .pagination .current {{
            padding: 6px 12px;
            border: 1px solid #0066cc;
            color: #fff;
            background: #0066cc;
            border-radius: 6px;
        }}
        .pagination .dots {{ color: #999; }}

        /* ===== Topic List ===== */
        .topic-list-item {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            text-decoration: none;
            color: inherit;
            transition: box-shadow 0.15s;
        }}
        .topic-list-item:hover {{
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            text-decoration: none;
        }}
        .topic-list-left {{ flex: 1; min-width: 0; }}
        .topic-list-title {{
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .topic-list-meta {{
            font-size: 12px;
            color: #999;
        }}
        .topic-list-count {{
            text-align: right;
            margin-left: 16px;
            flex-shrink: 0;
        }}
        .topic-list-count .num {{
            font-size: 22px;
            font-weight: 700;
            color: #1a1a1a;
            line-height: 1;
        }}
        .topic-list-count .label {{
            font-size: 11px;
            color: #999;
            margin-top: 2px;
        }}

        /* ===== Topic Detail Header ===== */
        .topic-header {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .topic-header h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 8px; }}
        .topic-header .summary {{ font-size: 13px; color: #555; margin-bottom: 12px; line-height: 1.5; }}
        .topic-header .meta {{ display: flex; gap: 16px; font-size: 12px; color: #999; }}
        .back-link {{ display: inline-block; margin-bottom: 16px; font-size: 13px; }}

        /* ===== Stats Page ===== */
        .stats-section {{
            background: #fff;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .stats-section h3 {{
            font-size: 14px;
            font-weight: 600;
            color: #333;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #f0f0f0;
        }}
        .stats-chart-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .stats-chart-box {{
            background: #fafafa;
            border: 1px solid #eee;
            border-radius: 6px;
            padding: 12px;
        }}
        .stats-chart-box h4 {{
            font-size: 12px;
            font-weight: 600;
            color: #888;
            margin-bottom: 8px;
        }}
        .stats-chart-full {{
            background: #fafafa;
            border: 1px solid #eee;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
        }}
        .stats-chart-full h4 {{
            font-size: 12px;
            font-weight: 600;
            color: #888;
            margin-bottom: 8px;
        }}
        .stat-bar-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .stat-bar-label {{
            width: 100px;
            font-size: 12px;
            color: #555;
            text-align: right;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            flex-shrink: 0;
        }}
        .stat-bar-track {{
            flex: 1;
            height: 20px;
            background: #f0f0f0;
            border-radius: 3px;
            overflow: hidden;
        }}
        .stat-bar-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}
        .stat-bar-value {{
            width: 40px;
            font-size: 12px;
            font-weight: 600;
            color: #333;
            flex-shrink: 0;
        }}

        @media (max-width: 600px) {{
            .stats-bar {{ grid-template-columns: repeat(3, 1fr); gap: 8px; }}
            .stat-card {{ padding: 12px 8px; }}
            .stat-card .num {{ font-size: 22px; }}
            .search-box {{ display: none; }}
            .trend-chart-row {{ grid-template-columns: 1fr; }}
            .trend-detail-stats {{ grid-template-columns: repeat(2, 1fr); }}
            .trend-methodology-grid {{ grid-template-columns: 1fr 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-inner">
            <div class="header-left">
                <h1>Tech Pluse</h1>
                <span class="updated">每日科技情报聚合</span>
            </div>
            {search_box_html}
        </div>
    </div>
    {content}
</body>
</html>"""


def _pagination_html(current_page: int, total_pages: int, url_template: str) -> str:
    """生成分页导航 HTML。

    url_template 中使用 {{page}} 作为页码占位符。
    """
    if total_pages <= 1:
        return ""

    parts = ['<div class="pagination">']

    if current_page > 1:
        parts.append(f'<a href="{url_template.replace("{page}", str(current_page - 1))}">上一页</a>')

    start_p = max(1, current_page - 2)
    end_p = min(total_pages, current_page + 2)

    if start_p > 1:
        parts.append(f'<a href="{url_template.replace("{page}", "1")}">1</a>')
        if start_p > 2:
            parts.append('<span class="dots">…</span>')

    for p in range(start_p, end_p + 1):
        if p == current_page:
            parts.append(f'<span class="current">{p}</span>')
        else:
            parts.append(f'<a href="{url_template.replace("{page}", str(p))}">{p}</a>')

    if end_p < total_pages:
        if end_p < total_pages - 1:
            parts.append('<span class="dots">…</span>')
        parts.append(f'<a href="{url_template.replace("{page}", str(total_pages))}">{total_pages}</a>')

    if current_page < total_pages:
        parts.append(f'<a href="{url_template.replace("{page}", str(current_page + 1))}">下一页</a>')

    parts.append('</div>')
    return "".join(parts)


def _bar_chart_svg(labels: list[str], values: list[float], width: int = 400, height: int = 160, color: str = "#0066cc") -> str:
    """生成 SVG 柱状图。"""
    if not values or len(values) < 1:
        return ""

    max_val = max(values) if values else 1
    if max_val == 0:
        max_val = 1

    padding_top = 10
    padding_bottom = 30
    padding_left = 10
    padding_right = 10
    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    bar_count = len(values)
    bar_gap = max(2, chart_w / (bar_count * 4))
    bar_w = max(4, (chart_w - bar_gap * (bar_count + 1)) / bar_count)

    bars_html = ""
    for i, v in enumerate(values):
        bar_h = (v / max_val) * chart_h
        x = padding_left + bar_gap + i * (bar_w + bar_gap)
        y = padding_top + chart_h - bar_h
        bars_html += f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="2"/>'

    # X 轴标签
    labels_html = ""
    for i, label in enumerate(labels):
        x = padding_left + bar_gap + i * (bar_w + bar_gap) + bar_w / 2
        y = height - 6
        labels_html += f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="9" fill="#888">{label}</text>'

    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="display:block">' \
           f'{bars_html}{labels_html}</svg>'


def _line_chart_svg(labels: list[str], values: list[float], width: int = 400, height: int = 160, color: str = "#0066cc") -> str:
    """生成 SVG 折线图（带面积填充）。"""
    if not values or len(values) < 2:
        return ""

    max_val = max(values) if values else 1
    if max_val == 0:
        max_val = 1

    padding_top = 10
    padding_bottom = 30
    padding_left = 10
    padding_right = 10
    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    points = []
    for i, v in enumerate(values):
        x = padding_left + (i / max(1, len(values) - 1)) * chart_w
        y = padding_top + chart_h - (v / max_val) * chart_h
        points.append((x, y))

    # 折线
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    # 面积（从最后一个点垂直到底部，再从第一个点底部闭合）
    area_points = line_points + f" {points[-1][0]:.1f},{padding_top + chart_h:.1f} {points[0][0]:.1f},{padding_top + chart_h:.1f}"

    path_html = f'<polygon points="{area_points}" fill="{color}" opacity="0.08"/>' \
                f'<polyline points="{line_points}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'

    # 数据点
    dots_html = ""
    for x, y in points:
        dots_html += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'

    # X 轴标签
    labels_html = ""
    for i, label in enumerate(labels):
        x = padding_left + (i / max(1, len(labels) - 1)) * chart_w
        y = height - 6
        labels_html += f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="9" fill="#888">{label}</text>'

    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="display:block">' \
           f'{path_html}{dots_html}{labels_html}</svg>'


def _horizontal_bar_svg(items: list[tuple[str, int]], color: str = "#0066cc", max_width: int = 300, height: int = 20, gap: int = 6) -> str:
    """生成水平条形图（纯 HTML/CSS 实现）。"""
    if not items:
        return ""

    max_val = max(v for _, v in items) if items else 1
    if max_val == 0:
        max_val = 1

    html = ""
    for label, value in items:
        pct = max(2, (value / max_val) * 100)
        html += f"""<div class="stat-bar-item">
            <span class="stat-bar-label" title="{label}">{label}</span>
            <div class="stat-bar-track">
                <div class="stat-bar-fill" style="width:{pct}%;background:{color}"></div>
            </div>
            <span class="stat-bar-value">{value}</span>
        </div>"""

    return html


def _trend_card(t: Trend) -> str:
    """渲染单条趋势卡片。"""
    label = STATUS_LABELS.get(t.status, t.status)
    badge_class = f"badge-{t.status}" if t.status else "badge-new"
    growth = f"+{int((t.growth_rate - 1) * 100)}%" if t.growth_rate > 1 else f"{int(t.growth_rate * 100)}%"

    topic_link = f'<a href="/trend/{t.id}" class="topic-link">{t.topic}</a>'

    return f"""<div class="trend-card">
        <div class="trend-header">
            <span class="topic">{topic_link}</span>
            <span class="badge {badge_class}">{label}</span>
        </div>
        <div class="trend-summary">{t.summary}</div>
        <div class="trend-meta">
            <span>{t.source_count} 个源</span>
            <span>{t.article_count} 篇文章</span>
            <span>周环比 {growth}</span>
            <span>爆发分 {t.burst_score:.1f}</span>
            <span>持续 {t.days_active} 天</span>
        </div>
    </div>"""


def _article_card(article: Article, source: Source) -> str:
    """渲染单篇文章卡片。"""
    score = article.signal_score
    signal_class = "high" if score >= 0.7 else ("medium" if score >= 0.4 else "low")
    signal_label = "高信号" if score >= 0.7 else ("中" if score >= 0.4 else "低")

    tags = ""
    if article.subcategories:
        tags = "".join(f'<span class="tag">{tag}</span>' for tag in article.subcategories)

    pub_date = ""
    if article.published_at:
        pub_date = str(article.published_at)[:10]

    return f"""<div class="article-item">
        <div class="article-title">
            <a href="{article.url}" target="_blank" rel="noopener">{article.title}</a>
            <span class="signal signal-{signal_class}">{score:.2f} {signal_label}</span>
        </div>
        <div class="article-summary">{article.summary}</div>
        <div class="article-info">
            <div class="article-meta">
                {source.name} · {article.category} · {pub_date}
            </div>
            <div class="article-tags">{tags}</div>
        </div>
    </div>"""


@router.get("/", response_class=HTMLResponse)
async def index(page: int = 1, category: str = "", source: str = "", q: str = "", tab: str = "trends", db: AsyncSession = Depends(get_db)):
    """主页面：tab 切换趋势 / 文章。"""
    if page < 1:
        page = 1

    # 统计
    article_count = (await db.execute(select(func.count(Article.id)))).scalar() or 0
    cluster_count = (await db.execute(select(func.count(Cluster.id)))).scalar() or 0
    trend_count = (await db.execute(select(func.count(Trend.id)))).scalar() or 0

    # ===== 趋势 =====
    trends = (await db.execute(
        select(Trend)
        .order_by(desc(Trend.signal), desc(Trend.burst_score))
        .limit(20)
    )).scalars().all()

    # ===== 分类过滤 =====
    cat_rows = (await db.execute(
        select(Article.category, func.count(Article.id))
        .where(Article.is_processed == True, Article.category != "")
        .group_by(Article.category)
        .order_by(func.count(Article.id).desc())
    )).all()

    # ===== 渠道过滤（列出所有源，含文章数） =====
    all_sources = (await db.execute(
        select(Source).order_by(Source.is_active.desc(), Source.name)
    )).scalars().all()

    # 批量查询各源文章数
    src_count_result = await db.execute(
        select(Source.name, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .where(Article.is_processed == True)
        .group_by(Source.name)
    )
    src_count_map = {row[0]: row[1] for row in src_count_result}

    source_rows = [(s.name, src_count_map.get(s.name, 0)) for s in all_sources]
    source_rows.sort(key=lambda x: x[1], reverse=True)

    # ===== 文章列表（分页 + 搜索） =====
    base_q = select(func.count(Article.id)).where(Article.is_processed == True)
    if category:
        base_q = base_q.where(Article.category == category)
    if source:
        base_q = base_q.join(Source, Article.source_id == Source.id).where(Source.name == source)
    if q:
        base_q = base_q.where(_article_search_filter(q))
    total_processed = (await db.execute(base_q)).scalar() or 0
    total_pages = max(1, (total_processed + PAGE_SIZE - 1) // PAGE_SIZE)

    offset = (page - 1) * PAGE_SIZE
    article_q = (
        select(Article, Source)
        .join(Source, Article.source_id == Source.id)
        .where(Article.is_processed == True)
    )
    if category:
        article_q = article_q.where(Article.category == category)
    if source:
        article_q = article_q.where(Source.name == source)
    if q:
        article_q = article_q.where(_article_search_filter(q))
    articles = (await db.execute(
        article_q.order_by(desc(Article.signal_score), desc(Article.published_at))
        .offset(offset)
        .limit(PAGE_SIZE)
    )).all()

    # ===== 渲染 =====
    # 趋势 tab
    if trends:
        trends_html = "".join(_trend_card(t) for t in trends)
    else:
        trends_html = '<div class="empty">暂无趋势数据，等待更多文章...</div>'

    # 分类过滤
    from urllib.parse import quote

    cat_html = '<div class="filter-bar"><span class="filter-label">分类</span>'
    cat_q_base = "/?tab=articles"
    if q:
        cat_q_base += f"&q={q}"
    if source:
        cat_q_base += f"&source={source}"
    all_active = " active" if not category else ""
    cat_html += f'<a href="{cat_q_base}" class="filter-chip{all_active}">全部</a>'
    for cat, cnt in cat_rows:
        active = " active" if category == cat else ""
        cat_html += f'<a href="{cat_q_base}&category={quote(cat)}" class="filter-chip{active}">{cat} ({cnt})</a>'
    cat_html += "</div>"

    # 渠道过滤（下拉选择）
    src_html = '<div class="filter-bar"><span class="filter-label">渠道</span>'
    src_html += f'<select onchange="window.location.href=this.value" class="filter-select">'
    src_html += f'<option value="/?tab=articles{f"&q={q}" if q else ""}{"&category=" + quote(category) if category else ""}">全部</option>'
    for src_name, src_cnt in source_rows:
        selected = " selected" if source == src_name else ""
        src_html += f'<option value="/?tab=articles{f"&q={q}" if q else ""}{"&category=" + quote(category) if category else ""}&source={quote(src_name)}"{selected}>{src_name} ({src_cnt})</option>'
    src_html += "</select></div>"

    # 搜索提示
    search_notice_html = ""
    if q:
        search_notice_html = f'<div class="search-notice">搜索「<strong>{q}</strong>」— 找到 <strong>{total_processed}</strong> 篇相关文章</div>'

    # 文章 tab
    if articles:
        articles_html = "".join(_article_card(a, s) for a, s in articles)
        pag_params = f"tab=articles"
        if q:
            pag_params += f"&q={q}"
        if category:
            pag_params += f"&category={category}"
        if source:
            pag_params += f"&source={source}"
        pag_url = f"/?{pag_params}&page={{page}}"
        articles_html += _pagination_html(page, total_pages, pag_url)
    else:
        label = f'搜索「{q}」' if q else ""
        articles_html = f'<div class="empty">暂无{label}文章数据</div>'

    # 话题 tab（首页缩略版：Top 10 话题，点击跳转话题列表页）
    cluster_q = select(Cluster)
    if q:
        cluster_q = cluster_q.where(_cluster_search_filter(q))
    top_clusters = (await db.execute(
        cluster_q.order_by(desc(Cluster.article_count), desc(Cluster.avg_signal)).limit(10)
    )).scalars().all()
    topic_list_html = ""
    if top_clusters:
        topic_list_html = ""
        for c in top_clusters:
            topic_list_html += f"""<a href="/cluster/{c.id}" class="topic-list-item">
                <div class="topic-list-left">
                    <div class="topic-list-title">{c.topic or c.title[:60]}</div>
                    <div class="topic-list-meta">{c.source_count} 个源 · 均分 {c.avg_signal:.2f}</div>
                </div>
                <div class="topic-list-count">
                    <div class="num">{c.article_count}</div>
                    <div class="label">篇文章</div>
                </div>
            </a>"""
        topic_link = f'/topics?q={q}' if q else "/topics"
        topic_list_html += f'<div style="text-align:center;padding:16px 0"><a href="{topic_link}" style="font-size:13px;color:#0066cc">查看全部话题 →</a></div>'
    else:
        topic_list_html = '<div class="empty">暂无话题数据</div>'

    # ===== 统计 tab 数据 =====
    # 分类分布
    cat_rows_all = (await db.execute(
        select(Article.category, func.count(Article.id))
        .where(Article.category != "")
        .group_by(Article.category)
        .order_by(func.count(Article.id).desc())
    )).all()

    # 话题 Top 10（按文章数）
    top_clusters_all = (await db.execute(
        select(Cluster.topic, Cluster.title, Cluster.article_count)
        .order_by(desc(Cluster.article_count))
        .limit(10)
    )).all()

    # 近 14 天每日新增文章
    daily_labels = []
    daily_values = []
    for d in range(13, -1, -1):
        day_start = datetime.utcnow() - timedelta(days=d + 1)
        day_end = datetime.utcnow() - timedelta(days=d)
        day_label = f"{day_end.month}/{day_end.day}"
        daily_labels.append(day_label)
        count = (await db.execute(
            select(func.count(Article.id))
            .where(Article.fetched_at >= day_start, Article.fetched_at < day_end)
        )).scalar() or 0
        daily_values.append(count)

    # 源贡献排行
    source_rows = (await db.execute(
        select(Source.name, func.count(Article.id))
        .join(Article, Source.id == Article.source_id, isouter=True)
        .group_by(Source.name)
        .order_by(func.count(Article.id).desc())
        .limit(15)
    )).all()

    # 信号分分布
    signal_high = (await db.execute(
        select(func.count(Article.id))
        .where(Article.signal_score >= 0.7)
    )).scalar() or 0
    signal_mid = (await db.execute(
        select(func.count(Article.id))
        .where(Article.signal_score >= 0.4, Article.signal_score < 0.7)
    )).scalar() or 0
    signal_low = (await db.execute(
        select(func.count(Article.id))
        .where(Article.signal_score < 0.4)
    )).scalar() or 0

    # 趋势状态分布
    trend_status_rows = (await db.execute(
        select(Trend.status, func.count(Trend.id))
        .group_by(Trend.status)
    )).all()

    # tab 导航 + 内容
    tab_trend_active = " active" if tab == "trends" else ""
    tab_article_active = " active" if tab == "articles" else ""
    tab_topic_active = " active" if tab == "topics" else ""
    tab_stats_active = " active" if tab == "stats" else ""

    # 统计 tab 内容
    cat_bar_html = _horizontal_bar_svg([(cat or "未分类", cnt) for cat, cnt in cat_rows_all[:12]], "#0066cc")

    topic_bar_items = []
    for topic, title, count in top_clusters_all:
        label = (topic or title[:40])[:35]
        topic_bar_items.append((label, count))
    topic_bar_html = _horizontal_bar_svg(topic_bar_items, "#2e7d32")

    source_bar_html = _horizontal_bar_svg([(name, cnt) for name, cnt in source_rows], "#e65100")

    daily_chart_html = _line_chart_svg(
        labels=daily_labels,
        values=daily_values,
        width=600,
        height=180,
        color="#0066cc",
    )

    signal_bar_html = _horizontal_bar_svg(
        [("高信号 (≥0.7)", signal_high), ("中信号 (0.4-0.7)", signal_mid), ("低信号 (<0.4)", signal_low)],
        "#2e7d32",
    )

    status_bar_items = [(STATUS_LABELS.get(s, s), c) for s, c in trend_status_rows]
    status_bar_html = _horizontal_bar_svg(status_bar_items, "#7b1fa2")

    stats_content = f"""
    <div class="stats-section">
        <h3>近 14 天每日新增文章</h3>
        <div class="stats-chart-full">{daily_chart_html}</div>
    </div>
    <div class="stats-chart-row">
        <div class="stats-section">
            <h3>文章分类分布</h3>
            {cat_bar_html}
        </div>
        <div class="stats-section">
            <h3>话题文章数 Top 10</h3>
            {topic_bar_html}
        </div>
    </div>
    <div class="stats-chart-row">
        <div class="stats-section">
            <h3>数据源贡献排行</h3>
            {source_bar_html}
        </div>
        <div class="stats-section">
            <h3>信号分分布</h3>
            {signal_bar_html}
        </div>
    </div>
    <div class="stats-section">
        <h3>趋势状态分布</h3>
        {status_bar_html}
    </div>
    """

    content = f"""
    <div class="stats-bar">
        <div class="stat-card"><div class="num">{article_count}</div><div class="label">文章</div></div>
        <div class="stat-card"><div class="num">{cluster_count}</div><div class="label">话题</div></div>
        <div class="stat-card"><div class="num">{trend_count}</div><div class="label">趋势</div></div>
    </div>
    <div class="tabs">
        <a href="/?tab=trends" class="tab-link{tab_trend_active}">趋势</a>
        <a href="/?tab=articles" class="tab-link{tab_article_active}">文章</a>
        <a href="/?tab=topics" class="tab-link{tab_topic_active}">话题</a>
        <a href="/?tab=stats" class="tab-link{tab_stats_active}">统计</a>
    </div>
    <div class="content">
        {"""<div class="trend-methodology">
        <h3>趋势评分算法</h3>
        <div class="trend-methodology-grid">
            <div class="trend-methodology-item">
                <div class="name">增长率</div>
                <div class="desc">本周 vs 上周文章数对比</div>
                <div class="formula">log₂(增长率) × 0.1</div>
            </div>
            <div class="trend-methodology-item">
                <div class="name">爆发检测</div>
                <div class="desc">近 7 天日入库量 Z-score</div>
                <div class="formula">Z-score × 0.15</div>
            </div>
            <div class="trend-methodology-item">
                <div class="name">跨源验证</div>
                <div class="desc">3 源以上开始加分</div>
                <div class="formula">每多 1 源 +0.05</div>
            </div>
            <div class="trend-methodology-item">
                <div class="name">基础频次</div>
                <div class="desc">话题总文章数的权重</div>
                <div class="formula">log₂(文章数) × 0.03</div>
            </div>
        </div>
        <div class="trend-state-legend">
            <span class="trend-state-legend-item"><span class="trend-state-dot" style="background:#e65100"></span> 爆发（Z≥2.0）</span>
            <span class="trend-state-legend-item"><span class="trend-state-dot" style="background:#2e7d32"></span> 上升</span>
            <span class="trend-state-legend-item"><span class="trend-state-dot" style="background:#c62828"></span> 持续热点（14 天+）</span>
            <span class="trend-state-legend-item"><span class="trend-state-dot" style="background:#1565c0"></span> 已冷却（7 天后删除）</span>
        </div>
        <div class="trend-methodology-footer">综合信号 = 四项加权之和，满分 1.0。低于 0.3 分不显示。</div>
    </div>""" if tab == "trends" else ""}
        {"<div>" + trends_html + "</div>" if tab == "trends" else ""}
        {"<div>" + search_notice_html + cat_html + src_html + articles_html + "</div>" if tab == "articles" else ""}
        {topic_list_html if tab == "topics" else ""}
        {stats_content if tab == "stats" else ""}
    </div>
    """

    search_action = "/topics" if tab == "topics" else "/"
    return _render_template("Tech Pluse", content, tab, search_q=q, search_action=search_action)


@router.get("/topics", response_class=HTMLResponse)
async def topic_list(page: int = 1, q: str = "", db: AsyncSession = Depends(get_db)):
    """话题列表页：按文章数排序，点击可进入详情。"""
    if page < 1:
        page = 1

    # 总数 + 搜索
    count_q = select(func.count(Cluster.id))
    if q:
        count_q = count_q.where(_cluster_search_filter(q))
    total_clusters = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total_clusters + PAGE_SIZE - 1) // PAGE_SIZE)

    offset = (page - 1) * PAGE_SIZE
    cluster_q = select(Cluster)
    if q:
        cluster_q = cluster_q.where(_cluster_search_filter(q))
    clusters = (await db.execute(
        cluster_q
        .order_by(desc(Cluster.article_count), desc(Cluster.avg_signal))
        .offset(offset)
        .limit(PAGE_SIZE)
    )).scalars().all()

    # 搜索提示
    search_notice_html = ""
    if q:
        search_notice_html = f'<div class="search-notice">搜索「<strong>{q}</strong>」— 找到 <strong>{total_clusters}</strong> 个相关话题</div>'

    items_html = ""
    for c in clusters:
        items_html += f"""<a href="/cluster/{c.id}" class="topic-list-item">
            <div class="topic-list-left">
                <div class="topic-list-title">{c.topic or c.title[:60]}</div>
                <div class="topic-list-meta">{c.source_count} 个源 · 均分 {c.avg_signal:.2f}</div>
            </div>
            <div class="topic-list-count">
                <div class="num">{c.article_count}</div>
                <div class="label">篇文章</div>
            </div>
        </a>"""

    if not clusters:
        label = f'「{q}」的' if q else ""
        items_html = f'<div class="empty">暂无{label}话题数据</div>'

    pag_params = "/topics?"
    if q:
        pag_params += f"q={q}&"
    pag_params += "page={page}"
    pagination = _pagination_html(page, total_pages, pag_params)

    content = f"""
    <div class="tabs">
        <a href="/?tab=trends" class="tab-link">趋势</a>
        <a href="/?tab=articles" class="tab-link">文章</a>
        <a href="/?tab=topics" class="tab-link active">话题</a>
        <a href="/?tab=stats" class="tab-link">统计</a>
    </div>
    <div class="content">
        {search_notice_html}
        <div>{items_html}</div>
        {pagination}
    </div>
    """
    return _render_template("话题列表", content, "topics", search_q=q, search_action="/topics")


@router.get("/cluster/{cluster_id}", response_class=HTMLResponse)
async def cluster_detail(cluster_id: str, page: int = 1, db: AsyncSession = Depends(get_db)):
    """话题详情页：展示该话题下的文章列表。"""
    import uuid

    if page < 1:
        page = 1

    try:
        cluster_uuid = uuid.UUID(cluster_id)
    except ValueError:
        return _render_template("话题不存在", '<div class="content"><div class="empty">话题 ID 无效</div></div>')

    cluster = (await db.execute(
        select(Cluster).where(Cluster.id == cluster_uuid)
    )).scalar()
    if not cluster:
        return _render_template("话题不存在", '<div class="content"><div class="empty">话题不存在</div></div>')

    # 该话题下的文章
    total_articles = (await db.execute(
        select(func.count(ClusterArticle.article_id))
        .where(ClusterArticle.cluster_id == cluster_uuid)
    )).scalar() or 0
    total_pages = max(1, (total_articles + PAGE_SIZE - 1) // PAGE_SIZE)

    offset = (page - 1) * PAGE_SIZE
    result = (await db.execute(
        select(Article, Source)
        .join(ClusterArticle, Article.id == ClusterArticle.article_id)
        .join(Source, Article.source_id == Source.id)
        .where(ClusterArticle.cluster_id == cluster_uuid)
        .order_by(desc(Article.signal_score), desc(Article.published_at))
        .offset(offset)
        .limit(PAGE_SIZE)
    )).all()

    articles_html = ""
    for article, source in result:
        articles_html += _article_card(article, source)

    pagination = _pagination_html(page, total_pages, f"/cluster/{cluster_id}?page={{page}}")

    content = f"""
    <div class="tabs">
        <a href="/?tab=trends" class="tab-link">趋势</a>
        <a href="/?tab=articles" class="tab-link">文章</a>
        <a href="/?tab=topics" class="tab-link">话题</a>
        <a href="/?tab=stats" class="tab-link">统计</a>
    </div>
    <div class="content">
        <a href="/?tab=topics" class="back-link">← 返回话题列表</a>
        <div class="topic-header">
            <h2>{cluster.topic or cluster.title[:60]}</h2>
            <div class="summary">{cluster.summary or cluster.title}</div>
            <div class="meta">
                <span>{cluster.article_count} 篇文章</span>
                <span>{cluster.source_count} 个源</span>
                <span>均分 {cluster.avg_signal:.2f}</span>
                <span>最早 {str(cluster.first_seen)[:10]}</span>
                <span>最近 {str(cluster.last_seen)[:10]}</span>
            </div>
        </div>
        <div>{articles_html}</div>
        {pagination}
    </div>
    """
    return _render_template(cluster.topic or "话题详情", content, "cluster_detail")


@router.get("/trend/{trend_id}", response_class=HTMLResponse)
async def trend_detail(trend_id: str, db: AsyncSession = Depends(get_db)):
    """趋势详情页：展示趋势指标和信号走势。"""
    try:
        trend_uuid = uuid_mod.UUID(trend_id)
    except ValueError:
        return _render_template("趋势不存在", '<div class="content"><div class="empty">趋势 ID 无效</div></div>')

    trend = (await db.execute(
        select(Trend).where(Trend.id == trend_uuid)
    )).scalar()
    if not trend:
        return _render_template("趋势不存在", '<div class="content"><div class="empty">趋势不存在</div></div>')

    label = STATUS_LABELS.get(trend.status, trend.status)
    badge_class = f"badge-{trend.status}" if trend.status else "badge-new"
    growth = f"+{int((trend.growth_rate - 1) * 100)}%" if trend.growth_rate > 1 else f"{int(trend.growth_rate * 100)}%"

    content = f"""
    <div class="tabs">
        <a href="/?tab=trends" class="tab-link active">趋势</a>
        <a href="/?tab=articles" class="tab-link">文章</a>
        <a href="/?tab=topics" class="tab-link">话题</a>
        <a href="/?tab=stats" class="tab-link">统计</a>
    </div>
    <div class="content">
        <div class="trend-detail">
            <div class="trend-detail-header">
                <a href="/?tab=trends" class="back-link" style="margin:0">← 返回</a>
                <h2>{trend.topic}</h2>
                <span class="badge {badge_class}">{label}</span>
            </div>
            <div class="trend-summary">{trend.summary}</div>
            <div class="trend-detail-stats">
                <div class="trend-stat"><div class="num">{trend.article_count}</div><div class="label">文章数</div></div>
                <div class="trend-stat"><div class="num">{trend.source_count}</div><div class="label">涉及源</div></div>
                <div class="trend-stat"><div class="num">{growth}</div><div class="label">周环比</div></div>
                <div class="trend-stat"><div class="num">{trend.burst_score:.1f}</div><div class="label">爆发分</div></div>
                <div class="trend-stat"><div class="num">{trend.signal:.2f}</div><div class="label">综合信号</div></div>
                <div class="trend-stat"><div class="num">{trend.days_active}</div><div class="label">持续天数</div></div>
            </div>
        </div>
    </div>
    """
    return _render_template(f"趋势: {trend.topic}", content, "trends")
