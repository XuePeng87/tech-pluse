"""文本处理工具：URL 规范化 + 标题指纹。"""
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


# 需要去除的跟踪参数
URL_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref",
}


def normalize_url(url: str) -> str:
    """规范化 URL：去除跟踪参数、锚点和尾部斜杠，转小写。

    例：https://example.com/path/?utm_source=hacker_news → https://example.com/path
    """
    if not url:
        return url
    parsed = urlsplit(url)
    # 过滤掉跟踪参数
    qs = parse_qs(parsed.query)
    filtered = {k: v for k, v in qs.items() if k not in URL_STRIP_PARAMS}
    cleaned = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc.rstrip("/"),
            parsed.path.rstrip("/") or "/",
            urlencode(filtered, doseq=True),
            "",  # 去除 fragment
        )
    )
    return cleaned.lower()


def title_fingerprint(title: str) -> str:
    """生成标题指纹：转小写、去标点、合并空格，用于快速去重。

    例："OpenAI Releases GPT-5!" → "openai releases gpt5"
    """
    import re
    s = title.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)  # 去标点
    s = re.sub(r"\s+", " ", s)      # 合并空格
    return s
