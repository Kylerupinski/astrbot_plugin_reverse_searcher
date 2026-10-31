"""搜索请求基类

所有搜索引擎请求类的抽象基类，继承 Network 提供统一的 HTTP 请求能力
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, Generic, TypeVar

from astrbot.api import logger

from ..network import RESP, Network
from ..response_parser.base_parser import BaseSearchResponse
from ..types import FileContent

T = TypeVar("T", bound=BaseSearchResponse[Any])


class BaseSearchReq(Network, ABC, Generic[T]):
    """搜索请求基类，继承 Network 的所有 HTTP 方法"""

    base_url: str = ""

    def __init__(
        self,
        base_url: str = "",
        network: Network | None = None,
        **request_kwargs: Any,
    ):
        if network is not None:
            # 使用外部传入的 Network 实例（复用其 client）
            self._client = network.client
            self._owned_client = False
        else:
            super().__init__(**request_kwargs)
            self._owned_client = True
        self.base_url = base_url

    @abstractmethod
    async def search(
        self,
        url: str | None = None,
        file: FileContent = None,
        **kwargs: Any,
    ) -> T:
        """执行搜索，子类必须实现"""
        raise NotImplementedError

    # 临时图床候选（按可用性排序，前一个失败自动换下一个）
    #
    # 注意：图床必须返回**可直接下载的图片 URL**，因为 Google Lens / Yandex
    # 是由第三方服务器去抓取该 URL。tmpfiles.org 现在返回的链接（含 /dl/）
    # 是一个带广告的 HTML 展示页（Content-Type: text/html），第三方抓取到的是
    # 网页而不是图片，最终表现为「搜索无结果」。所以上传后必须回读校验。
    _UPLOAD_HOSTS: tuple[tuple[str, str, dict | None, str, list | None], ...] = (
        # (名称, 上传地址, 额外表单字段, 文件字段名, JSON 取值路径)
        ("uguu.se", "https://uguu.se/upload.php", None, "files[]", ["files", 0, "url"]),
        ("x0.at", "https://x0.at", None, "file", None),
        (
            "pomf.lain.la",
            "https://pomf.lain.la/upload.php",
            None,
            "files[]",
            ["files", 0, "url"],
        ),
        (
            "litterbox.catbox.moe",
            "https://litterbox.catbox.moe/resources/internals/api.php",
            {"reqtype": "fileupload", "time": "1h"},
            "fileToUpload",
            None,
        ),
        (
            "tmpfiles.org",
            "https://tmpfiles.org/api/v1/upload",
            None,
            "file",
            ["data", "url"],
        ),
    )

    @staticmethod
    def _normalize_upload_url(url: str) -> str:
        """把图床返回的展示页链接尽量修正为直链"""
        url = url.strip()
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)
        # tmpfiles.org 的展示页与直链路径不同（直链在 /dl/ 下）
        if "tmpfiles.org/" in url and "/dl/" not in url:
            url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        return url

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        """按文件头判断字节是否为图片（图床可能把 HTML 当图片返回）"""
        if not data:
            return False
        if data.startswith(b"\xff\xd8\xff"):  # JPEG
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
            return True
        if data.startswith((b"GIF87a", b"GIF89a")):  # GIF
            return True
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WebP
            return True
        if data.startswith(b"BM"):  # BMP
            return True
        return bool(data[:2] == b"II" or data[:2] == b"MM")  # TIFF

    async def _verify_uploaded_image(self, url: str) -> bool:
        """回读上传结果，确认 URL 真的返回图片而不是 HTML 展示页"""
        try:
            resp = await self._client.get(
                url, headers={"Accept": "image/*,*/*"}, timeout=20
            )
            if resp.status_code != 200:
                logger.debug(
                    f"[BaseSearchReq] 图床回读失败 HTTP {resp.status_code}: {url[:100]}"
                )
                return False
            ctype = (resp.headers.get("content-type") or "").lower()
            if not self._looks_like_image(resp.content):
                logger.debug(
                    f"[BaseSearchReq] 图床返回的不是图片（{ctype or '无 Content-Type'}）: "
                    f"{url[:100]}"
                )
                return False
            return True
        except Exception as e:
            logger.debug(f"[BaseSearchReq] 图床回读异常 {url[:100]}: {e}")
            return False

    async def _upload_image(self, file: FileContent) -> str:
        """上传图片到临时图床，返回第三方可抓取的图片直链

        Google Lens / Yandex 的本地图搜依赖该直链：它们由服务端抓取 URL 内容。
        因此每一步都必须校验「回读得到的确实是图片字节」，否则第三方只会拿到
        一个 HTML 页面，搜索必然返回空结果（旧实现的 tmpfiles 即此问题）。
        """
        if not file:
            raise ValueError("File content is empty or None")

        failures: list[str] = []
        for name, upload_url, data, field_name, json_path in self._UPLOAD_HOSTS:
            try:
                resp = await self._client.post(
                    upload_url,
                    data=data,
                    files={field_name: ("image.jpg", file, "image/jpeg")},
                )
                resp.raise_for_status()
                text = resp.text.strip()

                candidate = ""
                if json_path:
                    try:
                        obj = json.loads(text)
                        value = obj
                        for key in json_path:
                            value = value[key]
                        if isinstance(value, str) and value.startswith("http"):
                            candidate = value
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        candidate = ""
                # 纯文本 URL 响应（litterbox / x0.at 等）
                if not candidate and text.startswith("http"):
                    candidate = text.splitlines()[0].strip()

                if not candidate:
                    failures.append(f"{name}: 未返回 URL")
                    continue

                candidate = self._normalize_upload_url(candidate)
                if not await self._verify_uploaded_image(candidate):
                    failures.append(f"{name}: 返回的链接不是图片")
                    continue
                logger.debug(f"[BaseSearchReq] 图片上传成功（{name}）: {candidate}")
                return candidate
            except Exception as e:
                failures.append(f"{name}: {type(e).__name__}: {e}")
                logger.debug(
                    f"[BaseSearchReq] 上传到 {upload_url} 失败，尝试下一个: {e}"
                )
                continue

        raise RuntimeError(
            "所有临时图床均不可用（Google/Yandex 本地图搜需要可被第三方抓取的图片直链）："
            + "；".join(failures)
        )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        # 只有自己创建的 client 才关闭，复用的不关闭
        if getattr(self, "_owned_client", True):
            await self._client.aclose()

    async def _send_request(
        self,
        method: str,
        endpoint: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> RESP:
        """发送 HTTP 请求"""
        request_url = url or (
            f"{self.base_url}/{endpoint}" if endpoint else self.base_url
        )
        method = method.lower()
        if method == "get":
            kwargs.pop("files", None)
            return await self.get(request_url, **kwargs)
        elif method == "post":
            return await self.post(request_url, **kwargs)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
