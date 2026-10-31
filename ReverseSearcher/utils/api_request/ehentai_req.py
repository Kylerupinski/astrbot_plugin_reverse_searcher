from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from typing_extensions import override

from ..ext_tools import read_file
from ..response_parser import EHentaiResponse
from .base_req import BaseSearchReq


class EHentai(BaseSearchReq[EHentaiResponse]):
    """
    E-Hentai搜索请求类

    用于与E-Hentai/ExHentai图像搜索功能交互，支持多种搜索选项
    """

    def __init__(
        self,
        is_ex: bool = False,
        covers: bool = False,
        similar: bool = True,
        exp: bool = False,
        **request_kwargs: Any,
    ):
        """
        初始化E-Hentai搜索请求

        参数:
            is_ex: 是否使用ExHentai而不是E-Hentai
            covers: 是否搜索封面图像
            similar: 是否搜索相似图像
            exp: 是否使用扩展搜索
            **request_kwargs: 其他请求参数
        """
        base_url = "https://upld.exhentai.org" if is_ex else "https://upld.e-hentai.org"
        super().__init__(base_url, **request_kwargs)
        self.is_ex: bool = is_ex
        self.covers: bool = covers
        self.similar: bool = similar
        self.exp: bool = exp

    @override
    async def search(
        self,
        url: str | None = None,
        file: str | bytes | Path | None = None,
        **kwargs: Any,
    ) -> EHentaiResponse:
        """
        执行E-Hentai图像搜索

        参数:
            url: 图像URL
            file: 本地文件内容
            **kwargs: 其他搜索参数

        返回:
            EHentaiResponse: 搜索响应对象

        异常:
            ValueError: 当未提供url或file参数时抛出
        """
        endpoint = "upld/image_lookup.php" if self.is_ex else "image_lookup.php"
        data: dict[str, Any] = {"f_sfile": "File Search"}
        if url:
            # Add filename to tuple to enable Similarity Search
            files = {
                "sfile": (
                    "image.jpg",
                    await self.download(url),
                    "application/octet-stream",
                )
            }
        elif file:
            file_bytes = read_file(file)
            files = {"sfile": ("image.jpg", file_bytes, "application/octet-stream")}
        else:
            raise ValueError("Either 'url' or 'file' must be provided")
        if self.covers:
            data["fs_covers"] = "on"
        if self.similar:
            data["fs_similar"] = "on"
        if self.exp:
            data["fs_exp"] = "on"
        resp = await self._send_request(
            method="post",
            endpoint=endpoint,
            data=data,
            files=files,
            # 不让 HTTP 客户端自动跟随上传跳转：E-Hentai 的风控会拒绝
            # “客户端自动跟随”的那一次跳转（实测固定返回 403），
            # 手动 GET Location 才能拿到真实结果页。
            follow_redirects=False,
        )

        if resp.status_code in (301, 302, 303, 307, 308):
            location = (resp.headers or {}).get("Location") or (resp.headers or {}).get(
                "location"
            )
            if location:
                target = urljoin(resp.url, location)
                resp = await self.get(
                    target, headers={"Referer": "https://e-hentai.org/"}
                )

        # 把 HTTP 状态码一并交给解析器：限流/封禁时常返回 200 + 纯文本提示，
        # 状态码与响应体一起判断才能给出可读的失败原因
        return EHentaiResponse(resp.text, resp.url, status_code=resp.status_code)
