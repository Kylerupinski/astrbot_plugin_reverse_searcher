"""Cloudflare 人机验证（``Just a moment...``）通用过盾工具

站点被 Cloudflare 托管挑战拦截时（HTTP 403/503 + 挑战页 HTML），普通 HTTP
客户端无法完成 JS 验证。这里通过 [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)
服务过一次盾，拿到 ``cf_clearance`` 等 Cookie 与对应 User-Agent，供**任意搜索引擎**
复用（配置在插件顶层 ``flaresolverr``，无需每个引擎各写一遍）。

FlareSolverr 协议::

    POST {url}/v1
    {"cmd": "request.get", "url": target, "maxTimeout": 90000}
    -> {"status": "ok", "solution": {"cookies": [...], "userAgent": "..."}}

过盾结果按目标 URL 缓存（默认 10 分钟），避免每次搜索都过一遍盾。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx
from astrbot.api import logger

# Cloudflare 挑战页的典型特征（标题/脚本/Cookie 检查页）
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "cf-chl",
    "verify you are human",
    "checking your browser",
)

DEFAULT_CACHE_TTL = 600.0
DEFAULT_TIMEOUT = 90.0


def is_cloudflare_challenge(
    status_code: int | None, headers: dict | None, text: str
) -> bool:
    """判断响应是否为 Cloudflare 人机验证页

    参数:
        status_code: HTTP 状态码
        headers: 响应头
        text: 响应正文
    """
    if status_code not in (403, 429, 503):
        return False
    lowered_headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    if str(lowered_headers.get("cf-mitigated", "")).lower() == "challenge":
        return True
    body = str(text or "").lower()
    return any(marker in body for marker in CHALLENGE_MARKERS)


def parse_cookie_header(raw: str) -> dict[str, str]:
    """把 ``a=1; b=2`` 形式的 Cookie 字符串解析成字典"""
    cookies: dict[str, str] = {}
    for part in str(raw or "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def cookie_header(cookies: dict[str, str]) -> str:
    """字典 → 请求头 Cookie 字符串"""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


@dataclass
class CfSolution:
    """一次过盾的结果"""

    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""


class FlareSolverrClient:
    """FlareSolverr 客户端（进程级复用 + 按目标 URL 缓存）

    未配置地址或显式关闭时 ``enabled`` 为 ``False``，调用方应先判断。
    """

    def __init__(
        self,
        url: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        proxy: str = "",
        enabled: bool = True,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ):
        """
        参数:
            url: FlareSolverr 服务地址，如 ``http://127.0.0.1:8191``
            timeout: 过盾超时（秒）
            proxy: FlareSolverr 访问目标站点时使用的代理（可选）
            enabled: 是否启用（地址为空时自动视为关闭）
            cache_ttl: 过盾结果缓存时长（秒）
        """
        self.url: str = (url or "").strip().rstrip("/")
        try:
            self.timeout = float(timeout or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        self.proxy: str = (proxy or "").strip()
        self.enabled: bool = bool(enabled and self.url)
        self.cache_ttl = float(cache_ttl or DEFAULT_CACHE_TTL)
        self._cache: dict[str, tuple[float, CfSolution]] = {}

    async def solve(self, target_url: str) -> CfSolution | None:
        """过盾并返回 Cookie/UA；失败或未启用时返回 ``None``

        参数:
            target_url: 需要过盾的目标页面（通常为站点首页）
        """
        if not self.enabled:
            return None

        cached = self._cache.get(target_url)
        if cached and time.time() - cached[0] < self.cache_ttl:
            logger.info("[Cloudflare] 复用缓存的过盾 Cookie（%s）", target_url)
            return cached[1]

        payload: dict = {
            "cmd": "request.get",
            "url": target_url,
            "maxTimeout": int(self.timeout * 1000),
        }
        if self.proxy:
            payload["proxy"] = {"url": self.proxy}
        try:
            # 独立客户端直连 FlareSolverr（本地/内网），不受图片下载代理影响
            async with httpx.AsyncClient(timeout=self.timeout + 15) as client:
                resp = await client.post(f"{self.url}/v1", json=payload)
        except Exception as exc:
            logger.warning(
                "[Cloudflare] 连接 FlareSolverr 失败（%s）：%s", self.url, exc
            )
            return None

        if resp.status_code != 200:
            logger.warning(
                "[Cloudflare] FlareSolverr 返回 HTTP %s：%s",
                resp.status_code,
                (resp.text or "")[:200],
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("[Cloudflare] FlareSolverr 返回内容不是 JSON")
            return None

        if data.get("status") != "ok":
            logger.warning(
                "[Cloudflare] FlareSolverr 过盾失败：%s", data.get("message") or data
            )
            return None

        solution = data.get("solution") or {}
        cookies = self._parse_solution_cookies(solution.get("cookies"))
        if not cookies:
            logger.warning("[Cloudflare] FlareSolverr 过盾成功但未返回 Cookie")
            return None

        result = CfSolution(
            cookies=cookies,
            user_agent=str(solution.get("userAgent") or "").strip(),
        )
        self._cache[target_url] = (time.time(), result)
        logger.info(
            "[Cloudflare] FlareSolverr 过盾成功，取得 %d 个 Cookie（%s）",
            len(cookies),
            target_url,
        )
        return result

    @staticmethod
    def _parse_solution_cookies(raw: object) -> dict[str, str]:
        """``solution.cookies`` → 字典"""
        cookies: dict[str, str] = {}
        if not isinstance(raw, list):
            return cookies
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                cookies[name] = str(item.get("value") or "")
        return cookies
