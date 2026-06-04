#!/usr/bin/env python3
"""Wikipedia 图片获取工具

用 Wikipedia REST API 获取地点/话题的代表性图片 URL 和简介。
Wikipedia-API 库用于文本摘要；图片 URL 走 MediaWiki pageimages API。
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Optional

import wikipediaapi

_UA = "local-life-butler/1.0 (openclaw-demo)"
_LANG = os.environ.get("WIKI_LANG", "zh")
_IMG_WIDTH = int(os.environ.get("WIKI_IMG_WIDTH", "800"))

_wiki = wikipediaapi.Wikipedia(_UA, _LANG)


def _mediawiki_image(title: str, width: int = _IMG_WIDTH) -> Optional[str]:
    """用 MediaWiki pageimages API 获取代表性图片 URL。"""
    encoded = urllib.parse.quote(title)
    url = (
        f"https://{_LANG}.wikipedia.org/w/api.php"
        f"?action=query&titles={encoded}&prop=pageimages"
        f"&pithumbsize={width}&format=json&redirects=1"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            src = page.get("thumbnail", {}).get("source")
            if src:
                return src
    except Exception:
        pass
    return None


def get_wiki_image(query: str) -> dict:
    """
    根据查询词获取 Wikipedia 图片 URL 和简介。

    返回:
        {
          "found": bool,
          "title": str,          # Wikipedia 页面标题
          "image_url": str,      # 图片直链（可空）
          "summary": str,        # 前两句简介
          "wiki_url": str,       # 页面链接
        }
    """
    page = _wiki.page(query)

    if not page.exists():
        return {"found": False, "title": query, "image_url": "", "summary": "", "wiki_url": ""}

    # 取摘要前 120 字
    summary = page.summary
    summary = summary[:120].rstrip("，。") + "…" if len(summary) > 120 else summary

    image_url = _mediawiki_image(page.title)

    return {
        "found": True,
        "title": page.title,
        "image_url": image_url or "",
        "summary": summary,
        "wiki_url": page.fullurl,
    }


def format_for_wechat(result: dict) -> str:
    """把 get_wiki_image 结果格式化成微信友好的文本。"""
    if not result["found"]:
        return ""
    lines = [f"📖 {result['title']}"]
    if result["summary"]:
        lines.append(result["summary"])
    if result["image_url"]:
        lines.append(f"🖼 {result['image_url']}")
    if result["wiki_url"]:
        lines.append(f"🔗 {result['wiki_url']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "趵突泉"
    r = get_wiki_image(q)
    print(format_for_wechat(r))
    print()
    print("raw:", json.dumps(r, ensure_ascii=False, indent=2))
