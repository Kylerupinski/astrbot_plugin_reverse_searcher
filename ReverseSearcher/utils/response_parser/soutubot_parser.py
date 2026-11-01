"""Soutubot（soutubot.moe）nhentai 图源检索结果解析

接口：``POST https://soutubot.moe/api/search``（multipart: file/factor/metadata_mode）
返回 JSON（节选）::

    {
      "status": "ok" | "partial" | "error",
      "partial": false,
      "detail": "当前搜索任务较多，请稍后重试",     # 出错时（如 429）
      "results": [
        {
          "score": 87.5,                            # 0~100 相似度
          "path_segments": [
            {
              "page_no": 12,
              "language": "ja",
              "thumbnail_url": "https://img.../025.webp",
              "source_url": "https://nhentai.net/g/682359",
              "page_url": "https://nhentai.net/g/682359/25/",
              "metadata": {
                "source": {"key": "nhentai", "id": "682359", "url": "..."},
                "title": {"primary": "...", "japanese_or_alias": "..."},
                "creators": [{"name": "..."}],
                "tags": {"other": ["tag:yuri", ...]},
                "facts": {"page_count": 41, "category": "doujinshi", "language": "japanese"}
              }
            }
          ]
        }
      ]
    }

同一画廊可能命中多页，这里按画廊合并并保留最高相似度。
"""

from __future__ import annotations

import json
import re
from typing import Any, override

from astrbot.api import logger

from .base_parser import BaseResParser, BaseSearchResponse

# 标签前缀（"tag:yuri" → "yuri"），其余前缀原样保留可读性
_TAG_PREFIXES = ("tag:", "group:", "parody:", "character:", "artist:", "language:")


def _collapse(text: str, limit: int = 500) -> str:
    """压缩空白并截断，便于写日志"""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _html_title(text: str) -> str:
    """从 HTML 响应里取 <title>（Cloudflare 挑战页/维护页通常是 HTML）"""
    match = re.search(
        r"<title[^>]*>(.*?)</title>", str(text or ""), re.IGNORECASE | re.DOTALL
    )
    return _collapse(match.group(1), 80) if match else ""


class SoutubotItem(BaseResParser):
    """单条 nhentai 图源结果"""

    def __init__(self, data: dict, score: float = 0.0, **kwargs: Any):
        self.hit_pages: int = 1
        self._score: float = float(score or 0)
        super().__init__(data, **kwargs)

    @override
    def _parse_data(self, data: dict, **kwargs: Any) -> None:
        segment = data if isinstance(data, dict) else {}
        metadata = segment.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        title_info = metadata.get("title") or {}
        source_info = metadata.get("source") or {}
        facts = metadata.get("facts") or {}

        external_id = str(
            segment.get("external_id") or source_info.get("id") or ""
        ).strip()
        self.gallery_id: str = external_id
        self.title: str = str(
            title_info.get("primary")
            or title_info.get("japanese_or_alias")
            or title_info.get("romanized")
            or (f"nhentai #{external_id}" if external_id else "nhentai 作品")
        ).strip()
        self.source: str = "nhentai"
        self.url: str = str(
            segment.get("page_url")
            or segment.get("source_url")
            or source_info.get("url")
            or ""
        ).strip()
        self.gallery_url: str = str(
            source_info.get("url") or segment.get("source_url") or ""
        ).strip()
        self.thumbnail: str = str(segment.get("thumbnail_url") or "").strip()
        self.similarity: float = self._score

        creators = metadata.get("creators") or []
        self.author: str = " / ".join(
            str(c.get("name")).strip()
            for c in creators
            if isinstance(c, dict) and c.get("name")
        )[:80]

        self.page_no: int | None = None
        try:
            if segment.get("page_no") is not None:
                self.page_no = int(segment["page_no"])
        except (TypeError, ValueError):
            self.page_no = None

        self.language: str = str(
            segment.get("language") or facts.get("language") or ""
        ).strip()
        self.category: str = str(facts.get("category") or "").strip()
        try:
            self.page_count: int | None = (
                int(facts["page_count"]) if facts.get("page_count") else None
            )
        except (TypeError, ValueError):
            self.page_count = None

        raw_tags = (metadata.get("tags") or {}).get("other") or []
        tags: list[str] = []
        for tag in raw_tags:
            text = str(tag).strip()
            for prefix in _TAG_PREFIXES:
                if text.startswith(prefix):
                    text = text[len(prefix) :]
                    break
            if text and text not in tags:
                tags.append(text)
        self.tags: list[str] = tags[:6]


class SoutubotResponse(BaseSearchResponse[SoutubotItem]):
    """Soutubot 搜索响应"""

    def __init__(self, resp_data: str, resp_url: str, **kwargs: Any):
        self.max_results = int(kwargs.get("max_results") or 10)
        self.status_code: int | None = kwargs.get("status_code")
        self.content_type: str = str(kwargs.get("content_type") or "")
        super().__init__(resp_data, resp_url, **kwargs)

    def _parse_response(self, resp_data: str, **kwargs: Any) -> None:
        self.error: str = ""
        self.partial: bool = False

        try:
            data = json.loads(resp_data)
        except (json.JSONDecodeError, TypeError):
            self.error = self._describe_non_json(resp_data)
            return
        if not isinstance(data, dict):
            self.error = self._describe_non_json(
                resp_data, reason="不是预期的 JSON 对象"
            )
            return

        self.partial = bool(data.get("partial")) or data.get("status") == "partial"
        detail = str(data.get("detail") or data.get("message") or "").strip()
        results = data.get("results")
        if not isinstance(results, list) or not results:
            if detail:
                self.error = detail
                logger.warning(
                    "[Soutubot] 搜索未返回结果：status=%s detail=%r",
                    self.status_code,
                    _collapse(detail, 300),
                )
            elif self.status_code and self.status_code >= 400:
                self.error = f"HTTP {self.status_code}"
            else:
                logger.info(
                    "[Soutubot] 搜索无结果（HTTP %s，响应 %d 字节）",
                    self.status_code,
                    len(str(resp_data or "")),
                )
            return

        merged: dict[str, SoutubotItem] = {}
        for result in results:
            if not isinstance(result, dict):
                continue
            segments = result.get("path_segments") or []
            segment = next(
                (
                    seg
                    for seg in segments
                    if isinstance(seg, dict) and isinstance(seg.get("metadata"), dict)
                ),
                None,
            )
            if segment is None:
                segment = next((seg for seg in segments if isinstance(seg, dict)), None)
            if segment is None:
                continue
            try:
                score = float(result.get("score") or 0)
            except (TypeError, ValueError):
                score = 0.0

            item = SoutubotItem(segment, score=score)
            key = item.gallery_id or item.url or item.title
            existing = merged.get(key)
            if existing is not None:
                existing.hit_pages += 1
                existing.similarity = max(existing.similarity, item.similarity)
                continue
            merged[key] = item

        self.raw = sorted(merged.values(), key=lambda i: i.similarity, reverse=True)[
            : max(1, self.max_results)
        ]

    def _describe_non_json(self, resp_data: str, reason: str = "不是合法 JSON") -> str:
        """记录详细告警并生成可读错误（测试环境常见：Cloudflare 挑战页/维护页）"""
        text = str(resp_data or "")
        length = len(text)
        snippet = _collapse(text)
        title = _html_title(text)
        logger.warning(
            "[Soutubot] 响应%s：HTTP %s | content-type=%s | 长度=%d 字节 | "
            "URL=%s | 页面标题=%r | 内容片段=%r",
            reason,
            self.status_code if self.status_code is not None else "未知",
            self.content_type or "未知",
            length,
            self.url,
            title,
            snippet,
        )
        if not length:
            return (
                "Soutubot 返回了空响应（HTTP {}，可能被限流）。详细日志见控制台".format(
                    self.status_code if self.status_code is not None else "未知"
                )
            )

        detail = f"HTTP {self.status_code}" if self.status_code else "无状态码"
        if self.content_type:
            detail += f" · {self.content_type}"
        if title:
            detail += f" · 页面标题「{title}」"
        hint = self._cf_hint(text)
        return (
            f"Soutubot 返回内容{reason}（{detail}，长度 {length} 字节）"
            f"——可能被限流或网站改版，详细响应已写入控制台日志{hint}"
        )

    def _cf_hint(self, text: str) -> str:
        """Cloudflare 挑战页时给出可操作的过盾建议"""
        lowered = str(text or "").lower()
        if self.status_code not in (403, 429, 503):
            return ""
        if not any(
            marker in lowered
            for marker in ("just a moment", "attention required", "cf-chl")
        ):
            return ""
        return (
            "；这通常是 Cloudflare 人机验证（当前出口 IP 被拦）：可在 "
            "default_params.soutubot.cookies 填入浏览器过盾后的 cf_clearance，"
            "或配置 default_params.soutubot.flaresolverr（如 http://127.0.0.1:8191）自动过盾"
        )

    @override
    def show_result(self) -> str | None:
        if not self.raw:
            return self.error or "Soutubot 未在 nhentai 图源中找到匹配"

        blocks: list[str] = []
        for item in self.raw[: self.max_results]:
            lines = [f"标题: {item.title}"]
            if item.author:
                lines.append(f"作者: {item.author}")
            facts = []
            if item.page_count:
                facts.append(f"{item.page_count}P")
            if item.language:
                facts.append(item.language)
            if item.category:
                facts.append(item.category)
            if facts:
                lines.append("信息: " + " · ".join(facts))
            if item.tags:
                lines.append("标签: " + ", ".join(item.tags))
            if item.url:
                lines.append(f"链接: {item.url}")
            similarity = self._format_similarity(item.similarity)
            if similarity:
                lines.append(f"相似度: {similarity}")
            blocks.append("\n".join(lines))

        text = ("\n" + "-" * 30 + "\n").join(blocks)
        if self.partial:
            text += "\n（结果可能不完整：本次搜索只完成了一部分）"
        return text

    @override
    def item_entries(self) -> list[dict]:
        """按结果拆分文本（文本模式逐条发送，带缩略图）"""
        entries: list[dict] = []
        for idx, item in enumerate(self.raw[:5], 1):
            header = f"结果 #{idx}"
            similarity = self._format_similarity(item.similarity)
            if similarity:
                header += f"（相似度 {similarity}）"
            lines = [header, f"标题: {item.title}"]
            if item.author:
                lines.append(f"作者: {item.author}")
            facts = []
            if item.page_count:
                facts.append(f"{item.page_count}P")
            if item.language:
                facts.append(item.language)
            if item.category:
                facts.append(item.category)
            if facts:
                lines.append("信息: " + " · ".join(facts))
            if item.tags:
                lines.append("标签: " + ", ".join(item.tags[:5]))
            if item.url:
                lines.append(f"链接: {item.url}")
            entries.append(
                {
                    "text": "\n".join(lines),
                    "thumbnail": item.thumbnail,
                    "full_image": "",
                    "crop_box": None,
                }
            )
        return entries
