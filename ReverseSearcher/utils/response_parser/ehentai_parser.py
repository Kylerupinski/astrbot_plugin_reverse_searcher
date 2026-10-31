import json
import re
from pathlib import Path
from typing import Any

from pyquery import PyQuery
from typing_extensions import override

from ..ext_tools import parse_html
from .base_parser import BaseResParser, BaseSearchResponse

# ehViewer 标签翻译表按路径缓存：文件内容基本不变，避免每次 show_result 重读磁盘
_TRANSLATIONS_CACHE: dict[str, dict] = {}


def _load_translations(path: Path) -> dict:
    key = str(path)
    if key not in _TRANSLATIONS_CACHE:
        try:
            with open(path, encoding="utf-8") as f:
                _TRANSLATIONS_CACHE[key] = json.load(f)
        except Exception:
            _TRANSLATIONS_CACHE[key] = {}
    return _TRANSLATIONS_CACHE[key]


class EHentaiItem(BaseResParser):
    """
    E-Hentai搜索结果项解析器

    解析单个画廊结果，提取标题、URL、缩略图、类型、日期、页数和标签等信息
    """

    def __init__(self, data: PyQuery, **kwargs: Any):
        """
        初始化E-Hentai结果项解析器

        参数:
            data: 包含结果项HTML的PyQuery对象
            **kwargs: 其他解析参数
        """
        super().__init__(data, **kwargs)

    @override
    def _parse_data(self, data: PyQuery, **kwargs: Any) -> None:
        """
        解析E-Hentai结果数据

        参数:
            data: 包含结果项HTML的PyQuery对象
            **kwargs: 其他解析参数
        """
        self._arrange(data)

    def _arrange(self, data: PyQuery) -> None:
        """
        整理和提取E-Hentai结果项中的各项数据

        参数:
            data: 包含结果项HTML的PyQuery对象
        """
        self.title = ""
        self.url = ""
        self.thumbnail = ""
        self.type = ""
        self.date = ""
        self.pages = "解析失败"
        self.tags = []

        # ── 标题 + 作品链接 ────────────────────────────────
        # 现行 e-hentai 列表标题是 div.glink；旧实现误写成 .gllink，
        # 永远匹配不到 → 所有字段为空，卡片里只剩空行（表现为“搜索无结果”）。
        title_el = data.find("div.glink")
        if len(title_el) == 0:
            title_el = data.find("div.gllink")  # 旧版模板兜底
        if len(title_el) == 0:
            title_el = data.find("td.gl3c a, .glname a")
        title_el = title_el.eq(0)

        link_el = title_el.closest("a")
        if len(link_el) == 0:
            link_el = data.find("td.gl3c a, .glname a, a[href*='/g/']").eq(0)
        self.url = (link_el.attr("href") or "").strip()
        self.title = title_el.text().strip()
        if not self.title:
            # 兜底：缩略图 alt/title 也带完整标题
            img_el = data.find("img").eq(0)
            self.title = (img_el.attr("alt") or img_el.attr("title") or "").strip()

        # ── 缩略图 ────────────────────────────────────────
        thumbnail = data.find(".glthumb img")
        if len(thumbnail) == 0:
            thumbnail = data.find(".gl1e img, .gl3t img, .gl3m img")
        if len(thumbnail) == 0:
            thumbnail = data.find("img")
        thumbnail = thumbnail.eq(0)
        self.thumbnail = (
            thumbnail.attr("data-src") or thumbnail.attr("src") or ""
        ).strip()

        # ── 分类 / 上传时间 ───────────────────────────────
        self.type = data.find(".gl1c .cn, .glcat .cn, .cs, .cn").eq(0).text().strip()
        self.date = data.find("[id^='posted']").eq(0).text().strip()

        # ── 页数 ──────────────────────────────────────────
        # 注意：只匹配单元格里的 div，不要把 td.gl4c 本身放进选择器——
        # PyQuery 的并集选择器按文档顺序返回，td 会先于其子 div 命中，
        # 拿到的文本是“上传者 + 页数”，split()[0] 就会变成上传者名字。
        pages_re = re.compile(r"(\d+)\s*pages?", re.IGNORECASE)
        for cell in data.find("td.gl4c div, .gl4c div").items():
            match = pages_re.search(cell.text() or "")
            if match:
                self.pages = match.group(1)
                break
        else:
            match = pages_re.search(data.text() or "")
            if match:
                self.pages = match.group(1)

        # ── 标签（div.gt 的 title 属性形如 parody:xxx）──────
        for i in data.find("div.gt, div.gtl, .gt, .gtl").items():
            tag = (i.attr("title") or "").strip()
            if tag and tag not in self.tags:
                self.tags.append(tag)


class EHentaiResponse(BaseSearchResponse[EHentaiItem]):
    """
    E-Hentai搜索响应解析器

    解析完整的E-Hentai搜索响应，包含多个画廊结果
    """

    def __init__(self, resp_data: str, resp_url: str, **kwargs: Any):
        """
        初始化E-Hentai响应解析器

        参数:
            resp_data: 原始HTML响应数据
            resp_url: 响应URL
            **kwargs: 其他解析参数
        """
        super().__init__(resp_data, resp_url, **kwargs)

    @override
    def _parse_response(self, resp_data: str, **kwargs: Any) -> None:
        """
        解析E-Hentai响应数据

        参数:
            resp_data: 原始HTML响应数据
            **kwargs: 其他解析参数（可含 status_code）
        """
        self.error: str = ""
        status_code = kwargs.get("status_code")

        # 上传搜索接口在限流/被封/需要登录时会返回纯文本或错误页，
        # 此时既没有结果表也没有 HTML，旧实现会静默显示“0 条结果”。
        lowered = (resp_data or "").lower()
        if "please wait a bit longer" in lowered:
            self.error = "E-Hentai 限制了搜索频率（请等待几秒后重试）"
            self.raw: list[EHentaiItem] = []
            self.origin = parse_html(resp_data)
            return
        if "request forbidden by administrative rules" in lowered:
            self.error = (
                "E-Hentai 拒绝了本次请求（HTTP 403，可能 IP 被限制、触发风控，"
                "或该分区需要登录 Cookie）"
            )
            self.raw = []
            self.origin = parse_html(resp_data)
            return
        if "temporarily banned" in lowered or "your ip address has been" in lowered:
            self.error = "E-Hentai 暂时封禁了当前 IP（请更换网络/代理，或稍后再试）"
            self.raw = []
            self.origin = parse_html(resp_data)
            return
        if status_code is not None and int(status_code) >= 400:
            self.error = f"E-Hentai 返回 HTTP {status_code}"
            self.raw = []
            self.origin = parse_html(resp_data)
            return

        data = parse_html(resp_data)
        self.origin: PyQuery = data
        if "No unfiltered results" in resp_data:
            self.raw: list[EHentaiItem] = []
        else:
            # .items() 返回生成器，生成器永远 truthy，必须先转 list 再判空
            tr_items = list(data.find(".itg").children("tr").items())
            if tr_items:
                self.raw = [EHentaiItem(i) for i in tr_items if i.children("td")]
            else:
                gl1t_items = data.find(".itg").children(".gl1t").items()
                self.raw = [EHentaiItem(i) for i in gl1t_items]

    _TRANSLATIONS_FILE = "resource/translations/ehviewer_translations.json"

    def _translations(self, translations_file: str | None = None) -> dict:
        """加载（带缓存的）ehViewer 标签翻译表"""
        path = Path(__file__).parent.parent.parent / (
            translations_file or self._TRANSLATIONS_FILE
        )
        return _load_translations(path)

    @staticmethod
    def _valid_items(raw: list[EHentaiItem]) -> list[EHentaiItem]:
        """过滤掉空壳行（解析失败且没有任何信息）"""
        return [item for item in raw if item.title or item.url or item.tags]

    def _format_item(self, idx: int, item: EHentaiItem, translations: dict) -> str:
        """格式化单条画廊结果（含标签翻译）"""
        categorized_tags: dict[str, list[str]] = {}
        for tag in item.tags:
            if ":" in tag:
                category, tag_name = tag.split(":", 1)
                category_cn = translations.get("rows", {}).get(category, category)
                tag_name_cn = tag_name
                if category in translations:
                    tag_name_cn = translations[category].get(tag_name, tag_name)
                categorized_tags.setdefault(category_cn, []).append(tag_name_cn)
        tag_lines = [
            f"  {category}: {'; '.join(tags)}"
            for category, tags in categorized_tags.items()
        ]
        type_cn = translations.get("reclass", {}).get(item.type.lower(), item.type)
        lines = [
            f"━━━ 结果 #{idx} ━━━",
            f"链接: {item.url}",
            f"上传时间: {item.date}",
            f"标题: {item.title}",
            f"类型: {type_cn}",
            f"页数: {item.pages}",
            "标签:",
            *tag_lines,
        ]
        return "\n".join(lines)

    def item_entries(self, translations_file: str | None = None) -> list[dict]:
        """按画廊拆分文本（文本模式逐条发送，可带缩略图）"""
        translations = self._translations(translations_file)
        entries: list[dict] = []
        for idx, item in enumerate(self._valid_items(self.raw)[:5], 1):
            entries.append(
                {
                    "text": self._format_item(idx, item, translations),
                    "thumbnail": item.thumbnail,
                    "full_image": "",
                    "crop_box": None,
                }
            )
        return entries

    def show_result(
        self,
        translations_file: str | None = None,
    ) -> str | None:
        """
        生成可读的搜索结果文本

        支持使用翻译文件将标签翻译为本地语言

        参数:
            translations_file: 翻译文件路径（保留兼容，默认用内置翻译表）

        返回:
            str: 格式化的搜索结果文本
        """
        entries = self.item_entries(translations_file)
        if not entries:
            # 限流/封禁/需要登录等错误页：把原因带给调用方，避免“静默空结果”
            return getattr(self, "error", "") or None
        return "\n\n".join(entry["text"] for entry in entries) + "\n"
