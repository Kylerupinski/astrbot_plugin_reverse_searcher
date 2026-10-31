import asyncio
import base64
import io
import re
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageDraw, ImageFont
from astrbot.api import logger

from .engine_registry import ENGINE_REGISTRY, inject_request_classes
from .utils import Network
from .utils.render_card import ResultCardRenderer
from .utils.security import is_safe_image_ref, is_safe_image_url
from .utils.types import FileContent

inject_request_classes()  # 注入请求类到注册表

ENGINE_MAP: dict[str, type] = {
    name: def_.req_class
    for name, def_ in ENGINE_REGISTRY.items()
    if def_.req_class is not None
}


class BaseSearchModel:
    """
    图像反向搜索基础模型类

    提供多种搜索引擎的统一接口，支持本地文件和URL搜索，
    可以输出文本结果或生成可视化图像结果，支持GIF格式自动转换
    """

    # 纯文本输出的正文上限（平台单条消息长度有限，超长会被拒发）
    MAX_TEXT_LENGTH = 2000

    # 结果配图档位：档位 -> (最长边像素, JPEG 质量)
    #   low      超低清：直接用引擎缩略图（最省流量）
    #   standard 标清：优先原始大图，缩放到最长边 640（默认）
    #   original 原图：优先原始大图，仅对超大图做兜底缩放（防内存/消息超限）
    IMAGE_SIZE_PROFILES: ClassVar[dict[str, tuple[int, int]]] = {
        "low": (256, 70),
        "standard": (640, 85),
        "original": (4096, 92),
    }

    def __init__(
        self,
        proxies: str | None = None,
        cookies: dict | None = None,
        timeout: int = 60,
        default_params: dict | None = None,
        allow_third_party_image_host: bool = True,
        result_image_size: str = "standard",
    ):
        """
        初始化搜索模型

        参数:
            proxies: 代理服务器配置
            cookies: Cookie配置（兜底，各引擎 Cookie 优先在 default_params 对应栏目配置）
            timeout: 请求超时时间(秒)
            default_params: 各引擎的默认参数（含 yandex/ehentai 的 cookies）
            allow_third_party_image_host: 是否允许把本地图上传到第三方临时图床（Google/Yandex 本地图搜需要）
            result_image_size: 结果配图档位（low/standard/original）
        """
        self.proxies = proxies
        self.cookies = cookies
        self.timeout = timeout
        self.default_params = default_params or {}
        self.allow_third_party_image_host = allow_third_party_image_host
        size = str(result_image_size or "standard").strip().lower()
        self.result_image_size = (
            size if size in self.IMAGE_SIZE_PROFILES else "standard"
        )

    def _prepare_engine_params(self, api: str, search_params: dict) -> dict:
        """从搜索参数中提取引擎专属配置。

        每个引擎有各自的特殊参数（如 saucenao 的 dbmask、ehentai 的 is_ex），
        本方法将它们从 search_params 中 pop 出来，组装为引擎构造参数。

        参数:
            api: 搜索引擎名
            search_params: 合并了默认参数+kwargs 的搜索参数字典 (会被修改)

        返回:
            dict: 引擎专属参数字典，用于传递给引擎类的 __init__
        """
        engine_params = {}

        if api == "animetrace":
            engine_params = {
                "is_multi": search_params.pop("is_multi", None),
                "ai_detect": search_params.pop("ai_detect", None),
            }
        elif api == "ehentai":
            engine_params = {
                "is_ex": search_params.pop("is_ex", False),
                "covers": search_params.pop("covers", False),
                "similar": search_params.pop("similar", True),
                "exp": search_params.pop("exp", False),
                "cookies": search_params.pop("cookies", None),
            }
        elif api == "saucenao":
            engine_params = {
                "api_key": search_params.pop("api_key", None),
                "hide": search_params.pop("hide", 3),
                "numres": search_params.pop("numres", 5),
                "minsim": search_params.pop("minsim", 30),
                "output_type": search_params.pop("output_type", 2),
                "testmode": search_params.pop("testmode", 0),
                "dbmask": search_params.pop("dbmask", None),
                "dbmaski": search_params.pop("dbmaski", None),
                "db": search_params.pop("db", 999),
                "dbs": search_params.pop("dbs", None),
            }
        elif api == "google":
            # API key 优先取顶层字段，兼容嵌套 api_keys dict
            serpapi_key = search_params.get("serpapi_key")
            zenserp_key = search_params.get("zenserp_key")

            if not serpapi_key and not zenserp_key:
                api_keys = search_params.get("api_keys", {})
                serpapi_key = api_keys.get("serpapi")
                zenserp_key = api_keys.get("zenserp")

            engine_params = {
                "serpapi_key": serpapi_key,
                "zenserp_key": zenserp_key,
                "country": search_params.get("country", "HK"),
                "hl": search_params.get("hl", "zh-CN"),
                "max_results": search_params.get("max_results", 10),
            }
        elif api == "yandex":
            engine_params = {
                "max_results": search_params.get("max_results", 10),
                "use_ru_fallback": search_params.get("use_ru_fallback", True),
                "cookies": search_params.pop("cookies", None),
            }

        return engine_params

    def _is_gif(self, file: FileContent) -> bool:
        """
        检查文件是否为GIF格式

        参数:
            file: 待检查的文件内容

        返回:
            bool: 如果是GIF格式返回True，否则返回False
        """
        if isinstance(file, (str, Path)):
            return str(file).lower().endswith(".gif")
        elif isinstance(file, bytes):
            return file.startswith((b"GIF87a", b"GIF89a"))
        return False

    async def _convert_gif_to_jpeg(self, file: FileContent) -> bytes:
        """
        将GIF图像转换为JPEG格式（异步方法，在单独线程中执行）

        参数:
            file: GIF格式的文件内容

        返回:
            bytes: 转换后的JPEG格式图像数据
        """

        def convert_image():
            if isinstance(file, bytes):
                img_data = file
            else:
                with open(file, "rb") as f:
                    img_data = f.read()
            img = Image.open(io.BytesIO(img_data))
            img.seek(0)
            jpeg_io = io.BytesIO()
            img.convert("RGB").save(jpeg_io, "JPEG", quality=85)
            return jpeg_io.getvalue()

        return await asyncio.to_thread(convert_image)

    async def search(
        self,
        api: str,
        file: FileContent = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        """
        执行图像反向搜索

        参数:
            api: 搜索引擎API名称
            file: 本地文件内容
            url: 图像URL
            **kwargs: 其他搜索参数

        返回:
            Optional[str]: 搜索结果文本，搜索失败时返回None

        异常:
            ValueError: 当API不支持或参数错误时抛出
        """
        if api not in ENGINE_MAP:
            available = ", ".join(ENGINE_MAP.keys())
            raise ValueError(f"不支持的引擎: {api}，支持的引擎: {available}")
        if not file and not url and not kwargs.get("base64"):
            raise ValueError("必须提供 file 或 url 参数")
        if file and url:
            raise ValueError("file 和 url 参数不能同时提供")
        # SSRF/本地文件读取防护：url 必须为公网图片地址（覆盖所有引擎，
        # 包括会直接下载 url 的 ehentai 等）。DNS 校验放线程池避免阻塞事件循环。
        if url and not await asyncio.to_thread(is_safe_image_ref, url):
            raise ValueError("图片地址不安全：仅支持公网图片 URL 或消息内图片")
        if file and not url and self._is_gif(file):
            file = await self._convert_gif_to_jpeg(file)

        response = await self._search_engine(api, file=file, url=url, **kwargs)
        return response.show_result()

    async def _search_engine(
        self,
        api: str,
        file: FileContent = None,
        url: str | None = None,
        **kwargs: Any,
    ):
        """执行搜索并返回完整的引擎响应对象。

        管道流程:
            1. 获取引擎类 & 合并默认参数 + kwargs
            2. 按引擎类型提取引擎专属参数 (如 saucenao 的 dbmask)
            3. 解析 Cookie (yandex 动态获取 / ehentai 从参数取 / 全局默认)
            4. base64 → bytes 转换 (animetrace 除外，它直接接受 base64)
            5. 创建 Network 会话 → 实例化引擎 → 执行搜索

        返回:
            BaseSearchResponse: 引擎返回的完整响应对象
        """
        engine_class = ENGINE_MAP[api]
        # 合并默认参数：default_params < kwargs，后者覆盖前者
        default_params = self.default_params.get(api, {})
        search_params = {**default_params, **kwargs}
        # 提取引擎专属参数 (api_key, dbmask 等)，从 search_params 中弹出
        engine_params = self._prepare_engine_params(api, dict(search_params))

        # ── Cookie 解析（从 default_params 的 yandex/ehentai 栏目取）──
        network_kwargs = {}
        if self.proxies:
            network_kwargs["proxies"] = self.proxies
        effective_cookies = engine_params.get("cookies")
        if not effective_cookies:
            effective_cookies = self.cookies
        if effective_cookies:
            network_kwargs["cookies"] = effective_cookies
        if self.timeout:
            network_kwargs["timeout"] = self.timeout

        # base64 → bytes: animetrace 原生支持 base64，其他引擎需要解码为 bytes
        if search_params.get("base64") and api != "animetrace":
            file = base64.b64decode(search_params.pop("base64"))

        # 第三方图床合规：Google/Yandex 本地图搜需把图片上传到临时图床。
        # 若用户在配置中关闭了“允许上传第三方图床”，则此处直接拒绝，避免图片外泄。
        if (
            api in ("google", "yandex")
            and file is not None
            and not self.allow_third_party_image_host
        ):
            raise ValueError(
                "本地图搜 Google/Yandex 需要把图片上传到第三方临时图床，"
                "当前已在配置中禁用。请开启“允许上传第三方图床”，或改用图片 URL。"
            )

        async with Network(**network_kwargs) as network:
            engine_instance = engine_class(network=network, **engine_params)
            # animetrace 特殊路径：传 base64 + model 参数
            if api == "animetrace" and search_params.get("base64"):
                response = await engine_instance.search(
                    base64=search_params.pop("base64"),
                    model=search_params.pop("model", None),
                    **search_params,
                )
            else:
                response = await engine_instance.search(
                    file=file, url=url, **search_params
                )
            return response

    async def search_and_draw(
        self,
        api: str,
        file: FileContent = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> Image.Image:
        """
        执行搜索并将结果渲染为图像

        参数:
            api: 搜索引擎API名称
            file: 本地文件内容
            url: 图像URL
            **kwargs: 其他搜索参数

        返回:
            Image.Image: 渲染后的结果图像
        """
        try:
            response = await self._search_engine(api=api, file=file, url=url, **kwargs)
            raw_items = getattr(response, "raw", []) or []

            network_kwargs = self._network_kwargs()

            # 源图必须先加载：AnimeTrace 的缩略图按检测框从源图裁剪，
            # 依赖源图做切图（否则那些结果行只能显示空白图片位）。
            source_image = await self._load_source_image(file, url, network_kwargs)

            items = self._build_items_from_raw(raw_items, source_image=source_image)

            # 引擎明确给出失败原因且没有任何结果时，直接渲染原因，
            # 而不是展示一张“0 条匹配”的空卡片（用户无法据此排查）。
            if not items:
                error = (getattr(response, "error", "") or "").strip()
                if error:
                    return await self.draw_error(api, error)

            # 下载缩略图
            async def download_all_thumbs():
                # 各缩略图下载相互独立、失败各自返回 None，并发执行；
                # 无缩略图位以 asyncio.sleep(0) 占位保持与 items 对齐
                async with Network(**network_kwargs) as client:
                    tasks = []
                    for item in items:
                        if item.get("thumbnail_image") is not None:
                            # 已经由源图裁剪生成（AnimeTrace），无需再下载
                            tasks.append(
                                asyncio.sleep(0, result=item["thumbnail_image"])
                            )
                            continue
                        thumb_url = item.get("thumbnail_url", "")
                        if thumb_url:
                            tasks.append(self._download_thumbnail(client, thumb_url))
                        else:
                            tasks.append(asyncio.sleep(0, result=None))
                    return list(await asyncio.gather(*tasks))

            thumb_images = await download_all_thumbs()
            for i, thumb in enumerate(thumb_images):
                if i < len(items) and (
                    thumb is not None or not items[i].get("thumbnail_image")
                ):
                    items[i]["thumbnail_image"] = thumb

            # AnimeTrace: 提取 AI 检测结果
            ai_detect = getattr(response, "ai", None)
            return await self.draw_results(
                api, items, source_image, ai_detect=ai_detect
            )
        except Exception as e:
            # 错误卡片透出具体原因（渲染层已有转义）；
            # 先脱敏，防止 httpx 异常把含 api_key 的请求 URL 画进卡片
            detail = self._sanitize_error(e)
            logger.warning(f"[ReverseSearcher] {api} 搜索失败: {type(e).__name__}: {e}")
            return await self.draw_error(api, detail[:200] or "搜索失败")

    # ── 文本模式：按结果分条输出（每条 = 文本 + 图片）──────────────

    MAX_TEXT_RESULTS = 5

    def _network_kwargs(self) -> dict:
        """构造 Network 连接参数（代理/超时）"""
        kwargs: dict = {}
        if self.proxies:
            kwargs["proxies"] = self.proxies
        if self.timeout:
            kwargs["timeout"] = self.timeout
        return kwargs

    async def _load_source_image(
        self, file: FileContent, url: str | None, network_kwargs: dict
    ) -> Image.Image | None:
        """加载源图（本地 bytes 或 URL），供卡片展示与检测框裁剪使用"""
        if file is not None:

            def load_image():
                if isinstance(file, (str, Path)):
                    return Image.open(file)
                if isinstance(file, bytes):
                    return Image.open(io.BytesIO(file))
                return None

            return await asyncio.to_thread(load_image)
        if url is not None:
            # 与 search() 的 url 入口对齐：下载源图前同样过安全校验
            if not await asyncio.to_thread(is_safe_image_ref, url):
                raise ValueError(f"不安全的图片地址: {url[:80]}")
            async with Network(**network_kwargs) as client:
                resp = await client.download(url)

            def load_from_url_bytes(d: bytes):
                return Image.open(io.BytesIO(d))

            return await asyncio.to_thread(load_from_url_bytes, resp)
        return None

    @staticmethod
    def _encode_image_bytes(
        img: Image.Image, quality: int = 85, max_side: int | None = None
    ) -> bytes | None:
        """PIL 图片 → JPEG 字节（发送前统一格式，兼容 webp/png 等）

        参数:
            img: 图片
            quality: JPEG 质量
            max_side: 最长边上限；超出时等比缩放（None 表示不缩放）
        """
        try:
            im = img
            if max_side and max(im.size) > max_side:
                im = im.copy()
                im.thumbnail((max_side, max_side), Image.LANCZOS)
            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
        except Exception:
            return None

    async def _entry_image_bytes(
        self, client: Network, entry: dict, source_image: Image.Image | None
    ) -> bytes | None:
        """获取单条结果配图（按配置档位决定分辨率与原图优先）

        优先按检测框裁剪源图（AnimeTrace）；否则下载结果图：
        ``original`` 档位优先取引擎的原始大图（`full_image`），其余档位优先缩略图，
        任一 URL 失败时自动尝试另一个，全部失败返回 None。
        """
        max_side, quality = self.IMAGE_SIZE_PROFILES[self.result_image_size]

        crop = self._crop_thumbnail(
            source_image, entry.get("crop_box"), max_size=max_side
        )
        if crop is not None:
            return await asyncio.to_thread(
                self._encode_image_bytes, crop, quality, max_side
            )

        thumbnail = entry.get("thumbnail") or ""
        full_image = entry.get("full_image") or ""
        # 超低清只取引擎缩略图（最省流量）；标清/原图优先取原始大图保证清晰度，
        # 原图下载失败时再回退缩略图。
        if self.result_image_size == "low":
            candidates = [thumbnail, full_image]
        else:
            candidates = [full_image, thumbnail]
        for url in dict.fromkeys(u for u in candidates if u):
            image = await self._download_thumbnail(client, url)
            if image is None:
                continue
            data = await asyncio.to_thread(
                self._encode_image_bytes, image, quality, max_side
            )
            if data:
                return data
        return None

    def _entries_from_response(self, response: Any) -> list[dict]:
        """取引擎的分条文本；老/自定义响应对象退回通用字段排版"""
        item_entries = getattr(response, "item_entries", None)
        if callable(item_entries):
            try:
                entries = item_entries()
                if isinstance(entries, list):
                    return [e for e in entries if isinstance(e, dict)]
            except Exception as e:
                logger.debug(f"[ReverseSearcher] item_entries 失败，使用通用排版: {e}")
        items = self._build_items_from_raw(getattr(response, "raw", []) or [])
        return self._entries_from_items(items)

    def _entries_from_items(self, items: list[dict]) -> list[dict]:
        """把统一卡片结构转成分条文本（引擎无分条实现时的兜底）"""
        entries: list[dict] = []
        for idx, item in enumerate(items[:5], 1):
            lines = [f"结果 #{idx}"]
            if source := (item.get("source") or ""):
                lines.append(f"来源: {source}")
            if title := item.get("title"):
                lines.append(f"标题: {title}")
            if author := item.get("author"):
                lines.append(f"作者: {author}")
            if similarity := item.get("similarity"):
                lines.append(f"相似度: {similarity}")
            if url := item.get("url"):
                lines.append(f"链接: {url}")
            entries.append(
                {
                    "text": "\n".join(lines),
                    "thumbnail": item.get("thumbnail_url") or "",
                    "crop_box": None,
                }
            )
        return entries

    async def search_text_messages(
        self,
        api: str,
        file: FileContent = None,
        url: str | None = None,
        max_items: int = MAX_TEXT_RESULTS,
        **kwargs: Any,
    ) -> list[dict]:
        """执行搜索并返回「按结果分条」的文本消息列表

        每条消息形如 ``{"text": str, "image": bytes | None}``：
        第 1 条是引擎/数量的汇总头，其后每条结果一条消息（文本 + 该结果的配图）。
        配图优先按检测框从源图裁剪（AnimeTrace），否则下载结果缩略图。

        参数:
            api: 搜索引擎API名称
            file: 本地文件内容
            url: 图像URL
            max_items: 最多输出多少条结果
            **kwargs: 其他搜索参数

        返回:
            list[dict]: 可直接逐条发送的消息列表
        """
        label = self._engine_label(api)
        try:
            response = await self._search_engine(api=api, file=file, url=url, **kwargs)
        except Exception as e:
            detail = self._sanitize_error(e)
            logger.warning(f"[ReverseSearcher] {api} 搜索失败: {type(e).__name__}: {e}")
            return [
                {
                    "text": f"🔍「{label}」搜索失败\n{detail[:300] or '未知错误'}",
                    "image": None,
                }
            ]

        entries = [
            entry
            for entry in self._entries_from_response(response)
            if (entry.get("text") or "").strip()
        ][: max(1, max_items)]

        error = (getattr(response, "error", "") or "").strip()
        ai_detect = getattr(response, "ai", None)

        header = f"🔍「{label}」搜索结果"
        if entries:
            header += f" · 共 {len(entries)} 条"
        if ai_detect is not None:
            header += "\n" + ("⚠️ 疑似 AI 生成" if ai_detect else "✅ 非 AI 生成")
        if error:
            header += f"\n⚠️ {error}"

        if not entries:
            header += "\n\n" + (error or "未找到相关结果")
            return [{"text": header, "image": None}]

        messages: list[dict] = [{"text": header, "image": None}]
        network_kwargs = self._network_kwargs()
        source_image = None
        # 只有需要从源图裁剪的引擎（AnimeTrace）才加载源图，避免无谓下载
        if any(entry.get("crop_box") for entry in entries):
            try:
                source_image = await self._load_source_image(file, url, network_kwargs)
            except Exception as e:
                logger.debug(f"[ReverseSearcher] 源图加载失败，跳过裁剪配图: {e}")

        async with Network(**network_kwargs) as client:
            for entry in entries:
                image = await self._entry_image_bytes(client, entry, source_image)
                messages.append({"text": entry["text"], "image": image})
        return messages

    async def search_and_text(
        self,
        api: str,
        file: FileContent = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> str:
        """执行搜索并返回单条纯文本结果（多条结果用空行拼接）

        与 search_text_messages 共用同一条请求/解析链路；需要「每条结果单独
        发送、并带上该结果配图」时请改用 search_text_messages。

        参数:
            api: 搜索引擎API名称
            file: 本地文件内容
            url: 图像URL
            **kwargs: 其他搜索参数

        返回:
            str: 可直接发送的纯文本结果（失败时包含失败原因）
        """
        messages = await self.search_text_messages(
            api=api, file=file, url=url, **kwargs
        )
        body = "\n\n".join(message["text"] for message in messages)

        # 部分平台对单条消息长度有限制（如 QQ 官方 4000 字），超出时截断并提示
        if len(body) > self.MAX_TEXT_LENGTH:
            body = body[: self.MAX_TEXT_LENGTH] + "\n…（结果过长，已截断）"
        return body

    @staticmethod
    def _sanitize_error(exc: BaseException) -> str:
        """错误信息脱敏：隐藏 api_key 等敏感查询参数"""
        return re.sub(r"(api[_-]?key=)[^&\s]+", r"\1***", str(exc), flags=re.I).strip()

    @staticmethod
    def _engine_label(api: str) -> str:
        """引擎展示名（未注册时退回大写名）"""
        engine_def = ENGINE_REGISTRY.get(api)
        return engine_def.label if engine_def else api.upper()

    def _format_items_text(self, items: list[dict]) -> str:
        """把统一的卡片数据结构格式化为纯文本列表"""
        entries = self._entries_from_items(items)
        return "\n\n".join(entry["text"] for entry in entries)

    async def draw_results(
        self,
        api: str,
        items: list[dict],
        source_image: Image.Image | None = None,
        ai_detect: bool | None = None,
    ) -> Image.Image:
        """绘制搜索结果图像

        主路径：HTML 模板 + 云端文转图（astrbot.app 风格卡片）；
        云端不可达/超时时自动降级为 PIL 手绘卡片。
        """
        try:
            renderer = ResultCardRenderer()
            img_path = await renderer.render_html_async(
                api, items, source_image, ai_detect=ai_detect
            )
            if img_path:
                return await asyncio.to_thread(Image.open, img_path)
        except Exception:
            pass
        return await asyncio.to_thread(
            self._draw_results_pil, api, items, source_image, ai_detect=ai_detect
        )

    def _draw_results_pil(
        self,
        api: str,
        items: list[dict],
        source_image: Image.Image | None = None,
        ai_detect: bool | None = None,
    ) -> Image.Image:
        """PIL 手绘卡片（HTML 渲染不可用时的回退）"""
        try:
            renderer = ResultCardRenderer()
            return renderer.render_pil(api, items, source_image, ai_detect=ai_detect)
        except Exception:
            return self._draw_results_legacy(api, "渲染失败", source_image)

    def _build_items_from_raw(
        self, raw_items: list, source_image: Image.Image | None = None
    ) -> list[dict]:
        """将引擎返回的原始解析结果转为统一的卡片数据结构。

        特殊处理:
            - AnimeTrace: 按角色拆分，每个角色一张卡片 (最多 10 张)，
              并用返回的检测框 box 从源图裁出角色区域作为缩略图
            - 其他引擎: 提取 title/url/similarity/source/author/thumbnail

        参数:
            raw_items: 引擎返回的解析后对象列表
            source_image: 源图（AnimeTrace 裁剪缩略图用，可为 None）

        返回:
            list[dict]: 结构化字典列表，供 render_card 使用
        """
        items = []
        for item in raw_items[:5]:
            # AnimeTrace: 一个结果可能含多个角色，逐个展开
            if hasattr(item, "characters") and hasattr(item, "box"):
                crop = self._crop_thumbnail(source_image, getattr(item, "box", None))
                for c in item.characters:
                    if len(items) >= 10:
                        break
                    items.append(
                        {
                            "title": f"角色: {c.name}",
                            "url": "",
                            "similarity": "",
                            "source": f"作品: {c.work}" if c.work else "AnimeTrace",
                            "author": "",
                            "thumbnail_url": "",
                            # 从源图按检测框裁出的角色缩略图（没有框时为 None）
                            "thumbnail_image": crop,
                        }
                    )
                if len(items) >= 10:
                    break
            else:
                sim = getattr(item, "similarity", 0)
                source = getattr(item, "source", "") or getattr(item, "index_name", "")
                author = getattr(item, "author", "") or ""
                # 作者与来源重复时（Yandex 的 domain 即来源）只保留一处，避免卡片重复两行
                if author and author == source:
                    author = ""
                items.append(
                    {
                        "title": getattr(item, "title", "") or "",
                        "url": getattr(item, "url", "") or "",
                        "similarity": self._format_similarity(sim),
                        "source": source or "",
                        "author": author,
                        "thumbnail_url": getattr(item, "thumbnail", "") or "",
                    }
                )
        return items

    @staticmethod
    def _crop_thumbnail(
        source_image: Image.Image | None, box, max_size: int = 256
    ) -> Image.Image | None:
        """按 AnimeTrace 的检测框从源图裁出角色缩略图

        box 可能是归一化坐标（0~1）或像素坐标，这里按数值范围判断；
        坐标明显越界（说明与当前源图不是同一张图）时放弃裁剪，避免裁出垃圾图。

        参数:
            source_image: 源图
            box: [x1, y1, x2, y2]
            max_size: 缩略图最长边

        返回:
            Optional[Image.Image]: 裁剪结果；无法裁剪时为 None
        """
        if source_image is None or not box or len(box) < 4:
            return None
        try:
            x1, y1, x2, y2 = (float(v) for v in box[:4])
        except (TypeError, ValueError):
            return None
        try:
            width, height = source_image.size
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None

        # 归一化坐标（AnimeTrace 也可能返回 0~1 的比例值）
        if max(x1, y1, x2, y2) <= 1.0:
            x1, x2 = x1 * width, x2 * width
            y1, y2 = y1 * height, y2 * height
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        # 容差 5%：明显超出源图范围的框视为不可用
        if x1 < -width * 0.05 or y1 < -height * 0.05:
            return None
        if x2 > width * 1.05 or y2 > height * 1.05:
            return None

        left, top = max(0, int(x1)), max(0, int(y1))
        right, bottom = min(width, int(x2)), min(height, int(y2))
        if right - left < 8 or bottom - top < 8:
            return None
        try:
            crop = source_image.crop((left, top, right, bottom)).convert("RGB")
            crop.thumbnail((max_size, max_size), Image.LANCZOS)
            return crop
        except Exception:
            return None

    @staticmethod
    def _format_similarity(sim) -> str:
        """将相似度数值格式化为字符串"""
        if isinstance(sim, (int, float)) and sim > 0:
            return f"{sim:.1f}%"
        return str(sim) if sim else ""

    async def _download_thumbnail(
        self, client: Network, url: str
    ) -> Image.Image | None:
        """
        异步下载缩略图并返回 PIL Image

        参数:
            client: Network 客户端实例
            url: 缩略图 URL

        返回:
            Optional[Image.Image]: 下载的缩略图，失败时返回 None
        """
        if not url:
            return None
        # 缩略图 URL 来自引擎响应，下载前重新校验（防第三方 API 被投毒返回内网地址）
        if not await asyncio.to_thread(is_safe_image_url, url):
            return None
        try:
            data = await client.download(url)
            if data:

                def load_from_bytes(d: bytes):
                    return Image.open(io.BytesIO(d))

                return await asyncio.to_thread(load_from_bytes, data)
        except Exception:
            pass
        return None

    def _draw_results_legacy(
        self, api: str, result: str | list, source_image: Image.Image | None = None
    ) -> Image.Image:
        """旧版文字渲染（回退用）"""
        margin = 20
        if isinstance(result, list):
            text_lines = []
            for item in result:
                parts = [
                    f"标题: {item.get('title', '')}",
                    f"来源: {item.get('source', '')}",
                ]
                if item.get("similarity"):
                    parts.append(f"相似度: {item['similarity']}")
                text_lines.append(" | ".join(parts))
                text_lines.append(item.get("url", ""))
                text_lines.append("---")
            result = "\n".join(text_lines)
        lines = result.split("\n")
        base_dir = Path(__file__).parent
        font_path = str(base_dir / "resource/font/NotoSansSC-Regular.otf")
        try:
            font = ImageFont.truetype(font_path, 18)
            title_font = ImageFont.truetype(font_path, 24)
        except OSError:
            font = ImageFont.load_default()
            title_font = ImageFont.load_default()
        title_text = f"{api.upper()} search results"
        if hasattr(title_font, "getbbox"):
            title_width = title_font.getbbox(title_text)[2] + margin * 2
        else:
            title_width = title_font.getsize(title_text)[0] + margin * 2
        max_text_width = 0
        for line in lines:
            if hasattr(font, "getbbox"):
                line_width = font.getbbox(line)[2] + margin * 2
            else:
                line_width = font.getsize(line)[0] + margin * 2
            max_text_width = max(max_text_width, line_width)
        source_img_height = 0
        source_img_width = 0
        if source_image:
            max_source_width = 800
            orig_width, orig_height = source_image.size
            if orig_width > max_source_width:
                ratio = max_source_width / orig_width
                source_img_width = max_source_width
                source_img_height = int(orig_height * ratio)
                source_image = source_image.resize(
                    (source_img_width, source_img_height), Image.LANCZOS
                )
            else:
                source_img_width = orig_width
                source_img_height = orig_height
        width = max(800, title_width, max_text_width, source_img_width + margin * 2)
        if hasattr(font, "getbbox"):
            line_height = max(25, font.getbbox("Ay")[3] + 7)
        else:
            line_height = max(25, font.getsize("Ay")[1] + 7)
        header_height = 60
        content_height = margin + line_height * len(lines)
        source_area_height = source_img_height + margin * 2 if source_image else 0
        total_height = header_height + content_height + source_area_height
        img = Image.new("RGB", (width, total_height), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (width, header_height)], fill="#4a6ea9")
        draw.text((margin, margin), title_text, font=title_font, fill="white")
        y_offset = header_height
        if source_image:
            x_center = (width - source_img_width) // 2
            img.paste(source_image, (x_center, y_offset + margin))
            y_offset += source_img_height + margin * 2
            draw.line(
                [
                    (margin, y_offset - margin // 2),
                    (width - margin, y_offset - margin // 2),
                ],
                fill="#cccccc",
                width=2,
            )
        y_position = y_offset
        for line in lines:
            if line.startswith("="):
                draw.line(
                    [(margin, y_position), (width - margin, y_position)],
                    fill="#cccccc",
                    width=1,
                )
            else:
                draw.text((margin, y_position), line, font=font, fill="black")
            y_position += line_height
        return img

    async def draw_error(self, api: str, error_msg: str) -> Image.Image:
        """绘制错误图像（HTML 卡片优先，失败降级 PIL）"""
        try:
            renderer = ResultCardRenderer()
            img_path = await renderer.render_error_html_async(api, error_msg)
            if img_path:
                return await asyncio.to_thread(Image.open, img_path)
        except Exception:
            pass
        return await asyncio.to_thread(renderer.render_error_pil, api, error_msg)
