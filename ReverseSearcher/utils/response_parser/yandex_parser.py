import json
from typing import Any

from astrbot.api import logger
from pyquery import PyQuery
from typing_extensions import override

from .base_parser import BaseResParser, BaseSearchResponse


class YandexItem(BaseResParser):
    """Yandex 单个搜索结果项"""

    def __init__(self, data: dict, **kwargs: Any):
        super().__init__(data, **kwargs)

    @override
    def _parse_data(self, data: dict, **kwargs: Any) -> None:
        self.title: str = data.get("title", "")
        self.url: str = data.get("url", "")
        self.thumbnail: str = data.get("thumbnail", "")
        # 原始大图，「原图」档位使用
        self.full_image: str = data.get("full_image", "")
        self.author: str = data.get("author", "")
        # Yandex 不走分数机制，设 0 避免相似度栏出现
        self.similarity: float = 0.0
        self.source: str = data.get("domain", "") or data.get("author", "")
        self.other_info: str = data.get("other_info", "")


class YandexResponse(BaseSearchResponse[YandexItem]):
    """
    Yandex 搜索结果解析类
    """

    def __init__(self, resp_data: str, resp_url: str, **kwargs: Any):
        super().__init__(resp_data, resp_url, **kwargs)
        self.max_results = kwargs.get("max_results", 10)

    @override
    def _parse_response(self, resp_data: str, **kwargs: Any) -> None:
        self.raw: list[YandexItem] = []
        # 空结果的原因（风控/CAPTCHA/图片不可访问），供卡片与文本输出提示
        self.error: str = ""
        status_code = kwargs.get("status_code")

        if status_code is not None and int(status_code) >= 400:
            self.error = (
                f"Yandex 返回 HTTP {status_code}（可能被风控，或需要配置 Cookie）"
            )
            return

        dom = PyQuery(resp_data)

        # Yandex 结果通常存储在 div.Root 的 data-state 属性中 (JSON)
        data_div = dom('div.Root[id^="ImagesApp-"]')
        data_state = data_div.attr("data-state")

        if not data_state:
            # 无 data-state：可能是被 CAPTCHA 拦截、未登录或页面结构变化
            lowered = (resp_data or "").lower()
            if "captcha" in lowered or "showcaptcha" in lowered:
                self.error = (
                    "Yandex 要求人机验证（CAPTCHA）：可在插件配置的 "
                    "default_params.yandex.cookies 中填写 Yandex Cookie，"
                    "或更换代理/稍后重试"
                )
                logger.warning(
                    "[Yandex] 响应疑似 CAPTCHA 验证页，建议在插件配置的 "
                    "default_params.yandex.cookies 中填写 Yandex Cookie"
                )
            else:
                self.error = (
                    "Yandex 返回页面结构异常（未找到 data-state），"
                    "可能被风控或页面接口已变更"
                )
                logger.warning(
                    "[Yandex] 响应缺少 data-state（页面结构可能已变化或需登录），解析结果为空"
                )
            return

        try:
            data_json = json.loads(data_state)
        except json.JSONDecodeError:
            self.error = "Yandex 返回的 data-state 不是合法 JSON，可能接口已变更"
            return

        initial_state = data_json.get("initialState", {}) or {}
        cbir_sites = initial_state.get("cbirSites", {}) or {}
        sites = cbir_sites.get("sites", []) or []
        if not sites:
            # 页面结构正常但没有结果：最常见原因是第三方抓取不到源图
            self.error = (
                "Yandex 未返回相似图片（请确认图片可被公网访问；"
                "本地图搜会先上传到临时图床，图床直链失效时会无结果）"
            )

        for site in sites:
            try:
                url = site.get("url", "")
                title = site.get("title", "")
                content = site.get("description", "")
                domain = site.get("domain", "")

                thumb_info = site.get("thumb", {})
                thumb_url = thumb_info.get("url", "")
                if thumb_url and thumb_url.startswith("//"):
                    thumb_url = "https:" + thumb_url

                original_image = site.get("originalImage", {}) or {}
                width = original_image.get("width", 0)
                height = original_image.get("height", 0)
                size_str = f"{width}x{height}"
                full_image = str(original_image.get("url") or "")
                if full_image.startswith("//"):
                    full_image = "https:" + full_image

                item = YandexItem(
                    {
                        "title": title,
                        "url": url,
                        "thumbnail": thumb_url,
                        "full_image": full_image,
                        "author": domain,
                        "other_info": f"{size_str} {content[:50]}..."
                        if content
                        else size_str,
                    }
                )
                self.raw.append(item)
            except Exception:
                continue

    @override
    def show_result(self) -> str:
        if not self.raw:
            return getattr(self, "error", "") or "Yandex 未找到相关结果"

        return "\n".join(
            [
                f"标题: {item.title}\n"
                f"来源: {item.author}\n"
                f"链接: {item.url}\n"
                f"信息: {item.other_info}\n"
                f"{'-' * 30}"
                for item in self.raw[: self.max_results]
            ]
        )

    @override
    def item_entries(self) -> list[dict]:
        """按结果拆分文本（文本模式逐条发送，可带缩略图）"""
        entries: list[dict] = []
        for idx, item in enumerate(self.raw[:5], 1):
            lines = [f"结果 #{idx}"]
            if item.title:
                lines.append(f"标题: {item.title}")
            if item.author:
                lines.append(f"来源: {item.author}")
            if item.other_info:
                lines.append(f"信息: {item.other_info}")
            if item.url:
                lines.append(f"链接: {item.url}")
            entries.append(
                {
                    "text": "\n".join(lines),
                    "thumbnail": item.thumbnail,
                    "full_image": item.full_image,
                    "crop_box": None,
                }
            )
        return entries
