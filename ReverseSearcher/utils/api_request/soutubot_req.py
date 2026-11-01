"""Soutubot 搜索请求（soutubot.moe，nhentai 图源检索）

网站没有公开 API，前端直接调用同站接口：

    POST https://soutubot.moe/api/search
    multipart/form-data:
        file          图片文件
        factor        1.2 常规 / 1.4 严格（更容易没结果）
        metadata_mode display
    返回 JSON，字段见 response_parser.soutubot_parser

站点会做任务排队限流（HTTP 429 + ``{"detail": "当前搜索任务较多，请稍后重试"}``），
解析器会把该提示原样交给用户。

站点也有 Cloudflare 人机验证（部分服务器 IP 会拿到 ``Just a moment...`` 的 403 页面）。
过盾逻辑统一在 ``utils.cloudflare``（全局 ``flaresolverr`` 配置），本类只负责：

1. 检测到挑战页 → 调全局过盾客户端取 Cookie/UA → 重试一次；
2. 也支持手动 ``cookies``（浏览器里过盾后的 ``cf_clearance`` 等），作为兜底。
"""

from __future__ import annotations

from typing import Any, ClassVar

from astrbot.api import logger
from typing_extensions import override

from ..cloudflare import (
    cookie_header,
    is_cloudflare_challenge,
    parse_cookie_header,
)
from ..ext_tools import read_file
from ..response_parser import SoutubotResponse
from .base_req import BaseSearchReq

_BASE_URL = "https://soutubot.moe"


class Soutubot(BaseSearchReq[SoutubotResponse]):
    """Soutubot（nhentai 图源检索）请求类"""

    DEFAULT_UA: ClassVar[str] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    # 站点没有鉴权，但按网页请求附带浏览器特征头可降低被风控的概率
    _HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://soutubot.moe",
        "Referer": "https://soutubot.moe/",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }

    def __init__(
        self,
        factor: float | str = 1.2,
        metadata_mode: str = "display",
        max_results: int = 10,
        cookies: str | None = None,
        user_agent: str = "",
        **request_kwargs: Any,
    ):
        """
        初始化 Soutubot 请求

        参数:
            factor: 搜索模式，1.2 常规 / 1.4 严格
            metadata_mode: 元数据模式（网页固定 display）
            max_results: 最多返回多少条结果
            cookies: 手动 Cookie（如浏览器过盾后的 ``cf_clearance=...``）
            user_agent: 与 Cookie 匹配的 User-Agent（留空用内置 Chrome UA）
            **request_kwargs: 其他请求参数（代理/超时/``cf_solver`` 等）
        """
        super().__init__(_BASE_URL, **request_kwargs)
        self.factor: str = self._normalize_factor(factor)
        self.metadata_mode: str = metadata_mode or "display"
        self.max_results: int = int(max_results or 10)
        self.cookies: dict[str, str] = parse_cookie_header(cookies or "")
        self.user_agent: str = (user_agent or "").strip() or self.DEFAULT_UA

    @staticmethod
    def _normalize_factor(factor: float | str) -> str:
        """把 factor 规范成站点接受的 ``1.2`` / ``1.4``"""
        try:
            value = float(factor)
        except (TypeError, ValueError):
            return "1.2"
        return "1.4" if value >= 1.4 else "1.2"

    @override
    async def search(
        self,
        url: str | None = None,
        file: str | bytes | Any = None,
        **kwargs: Any,
    ) -> SoutubotResponse:
        """
        执行 Soutubot 图源检索

        参数:
            url: 图像 URL（内部会先下载）
            file: 本地图片（bytes 或路径）

        返回:
            SoutubotResponse: 解析后的响应对象

        异常:
            ValueError: 未提供 url 或 file
        """
        if url:
            file_bytes = await self.download(url)
        elif file:
            file_bytes = read_file(file)
        else:
            raise ValueError("Either 'url' or 'file' must be provided")

        data = {"factor": self.factor, "metadata_mode": self.metadata_mode}
        files = {"file": ("image.jpg", file_bytes, "image/jpeg")}
        logger.info(
            "[Soutubot] 发起搜索：source=%s | factor=%s | image=%d 字节",
            "url" if url else "file",
            self.factor,
            len(file_bytes),
        )

        resp = await self._post_search(data, files)
        if is_cloudflare_challenge(resp.status_code, resp.headers, resp.text):
            logger.warning(
                "[Soutubot] 触发 Cloudflare 人机验证（HTTP %s），尝试自动过盾",
                resp.status_code,
            )
            if await self._apply_cf_clearance():
                resp = await self._post_search(data, files)
                if is_cloudflare_challenge(resp.status_code, resp.headers, resp.text):
                    logger.warning(
                        "[Soutubot] 自动过盾后仍被 Cloudflare 拦截，请改用代理或手动 Cookie"
                    )
            else:
                logger.warning(
                    "[Soutubot] 当前出口 IP 被 Cloudflare 拦截；可在顶层 "
                    "flaresolverr 配置 FlareSolverr 自动过盾，或在 "
                    "default_params.soutubot.cookies 填入浏览器过盾后的 cf_clearance"
                )

        content_type = (resp.headers or {}).get("content-type", "")
        logger.info(
            "[Soutubot] 接口响应：HTTP %s | content-type=%s | 长度=%d 字节",
            resp.status_code,
            content_type or "未知",
            len(resp.text or ""),
        )
        # 失败细节统一由解析器以 WARNING 输出（带 URL/页面标题/内容片段），
        # 这里只记录响应概况，避免同一次失败打两条告警。
        return SoutubotResponse(
            resp.text,
            resp.url,
            status_code=resp.status_code,
            content_type=content_type,
            max_results=self.max_results,
        )

    # ── 内部实现 ────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        headers = {**self._HEADERS, "User-Agent": self.user_agent}
        if self.cookies:
            headers["Cookie"] = cookie_header(self.cookies)
        return headers

    async def _post_search(self, data: dict, files: dict):
        """发送一次搜索请求"""
        return await self._send_request(
            method="post",
            endpoint="api/search",
            data=data,
            files=files,
            headers=self._build_headers(),
        )

    async def _apply_cf_clearance(self) -> bool:
        """通过全局 FlareSolverr 过盾并写入 Cookie；成功返回 True"""
        solver = self.cf_solver
        if solver is None or not getattr(solver, "enabled", False):
            return False
        solution = await solver.solve(f"{_BASE_URL}/")
        if solution is None:
            return False
        self.cookies.update(solution.cookies)
        if solution.user_agent:
            self.user_agent = solution.user_agent
        return True
