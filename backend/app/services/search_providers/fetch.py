"""Own-fetch fallback for sources the search API returns too thin.

Only used for pages the research loop already decided are worth the extra call —
a company's own site or an official filing — because every fetch is a page that
can hang, block, or return mojibake, and a failed fetch must degrade to "we only
have the snippet" rather than failing the sweep.
"""

from __future__ import annotations

import re
from urllib import error, request

FETCH_USER_AGENT = "Mozilla/5.0 (compatible; MatchMA-Research/1.0)"

MAX_FETCH_BYTES = 400_000

MAX_TEXT_CHARS = 20_000

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def fetch_page_text(url: str, *, timeout_seconds: int = 15) -> str | None:
    """Return readable page text, or None when the page cannot be used.

    Never raises: the caller treats a miss as "no extra content available".
    """
    if not url.lower().startswith(("http://", "https://")):
        return None
    req = request.Request(
        url,
        headers={
            "User-Agent": FETCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            if "html" not in content_type.lower() and "text" not in content_type.lower():
                return None
            raw = response.read(MAX_FETCH_BYTES)
            charset = response.headers.get_content_charset()
    except (error.HTTPError, error.URLError, ValueError, OSError):
        return None

    text_value = _decode(raw, charset)
    if not text_value:
        return None
    return html_to_text(text_value)[:MAX_TEXT_CHARS] or None


def _decode(raw: bytes, charset: str | None) -> str:
    # 中文站点常见 gbk/gb2312，且 Content-Type 未必声明正确。
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    without_scripts = _SCRIPT_STYLE.sub(" ", html)
    without_tags = _TAGS.sub("\n", without_scripts)
    unescaped = (
        without_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    collapsed = _WHITESPACE.sub(" ", unescaped)
    lines = [line.strip() for line in collapsed.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(line for line in lines if line))
