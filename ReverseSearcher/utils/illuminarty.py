"""Illuminarty 网页版 AI 生成检测（作为 AI or Not 的免费备用）

app.illuminarty.ai 的主页在**未登录**状态下即可上传图片并给出「AI Probability」，
前端实际调用的是同站接口：

    POST https://app.illuminarty.ai/api/analysis/image
    multipart/form-data: file=<图片>   （png/jpg/jpeg/webp，≤3MB）
    返回: {"data": {"probability": 0.008, "details": {}}, "status": "success"}

其中 ``probability`` 为 0~1 的 AI 生成概率（站点按 ×100 显示为百分比）。
这是该网站未公开的网页接口（非官方 API），可能随时变更或限流，因此默认关闭、
仅在 AI or Not 失败时作为备用；解析失败时返回错误结果，不影响正常搜图。
"""

from __future__ import annotations

import asyncio
import io
import json

from astrbot.api import logger
from PIL import Image

from .aiornot import AIDetectionResult
from .network import Network

ILLUMINARTY_ENDPOINT = "https://app.illuminarty.ai/api/analysis/image"

# 网页端限制：单张不超过 3MB，仅支持 png/jpg/jpeg/webp
ILLUMINARTY_MAX_BYTES = 3 * 1024 * 1024

# 浏览器特征头：该接口没有鉴权，但按网页请求发送可降低被风控的概率
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Origin": "https://app.illuminarty.ai",
    "Referer": "https://app.illuminarty.ai/",
    "Accept": "application/json",
}

# 判定阈值：概率 ≥ 0.5 视为 AI 生成
_AI_THRESHOLD = 0.5


class IlluminartyDetector:
    """Illuminarty 主页识别接口客户端"""

    def __init__(self, enabled: bool = False, timeout: float = 60.0):
        self.enabled = bool(enabled)
        self.timeout = float(timeout or 60)

    async def detect(
        self, image: bytes, network_kwargs: dict | None = None
    ) -> AIDetectionResult:
        """检测图片 AI 生成概率

        参数:
            image: 图片字节（不支持的格式/超大图会自动转成 JPEG）
            network_kwargs: 代理/超时等连接参数

        返回:
            AIDetectionResult: 成功时 verdict 为 ai/human，失败时 error 非空
        """
        if not self.enabled:
            return AIDetectionResult(
                verdict="error", provider="Illuminarty", error="未启用 Illuminarty"
            )
        if not image:
            return AIDetectionResult(
                verdict="error", provider="Illuminarty", error="图片内容为空"
            )

        payload, mime_type = await self._prepare_image(image)
        try:
            async with Network(**(network_kwargs or {})) as client:
                resp = await client.post(
                    ILLUMINARTY_ENDPOINT,
                    headers=_HEADERS,
                    files={"file": ("image.jpg", payload, mime_type)},
                    timeout=self.timeout,
                )
        except Exception as exc:
            logger.debug(f"[Illuminarty] 请求失败: {type(exc).__name__}: {exc}")
            return AIDetectionResult(
                verdict="error",
                provider="Illuminarty",
                error=f"请求失败（{type(exc).__name__}）",
            )

        if resp.status_code != 200:
            snippet = (resp.text or "").strip().replace("\n", " ")[:160]
            logger.debug(f"[Illuminarty] HTTP {resp.status_code}: {snippet}")
            return AIDetectionResult(
                verdict="error",
                provider="Illuminarty",
                error=f"HTTP {resp.status_code}：{snippet}",
            )

        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return AIDetectionResult(
                verdict="error", provider="Illuminarty", error="返回内容不是合法 JSON"
            )

        if not isinstance(data, dict) or data.get("status") != "success":
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "")
            return AIDetectionResult(
                verdict="error",
                provider="Illuminarty",
                error=f"接口返回异常：{message[:120]}" if message else "接口返回异常",
            )

        payload_data = data.get("data")
        probability = None
        if isinstance(payload_data, dict):
            probability = payload_data.get("probability")
        try:
            probability = float(probability) if probability is not None else None
        except (TypeError, ValueError):
            probability = None
        if probability is None:
            return AIDetectionResult(
                verdict="error",
                provider="Illuminarty",
                error="返回中缺少 probability",
            )

        probability = max(0.0, min(1.0, probability))
        return AIDetectionResult(
            verdict="ai" if probability >= _AI_THRESHOLD else "human",
            ai_probability=probability,
            provider="Illuminarty",
        )

    async def _prepare_image(self, image: bytes) -> tuple[bytes, str]:
        """网页接口只收 png/jpg/webp 且 ≤3MB，必要时转 JPEG 并压缩"""
        mime_type = _sniff_mime(image)
        if (
            mime_type in ("image/png", "image/webp")
            and len(image) <= ILLUMINARTY_MAX_BYTES
        ):
            return image, mime_type
        if mime_type == "image/jpeg" and len(image) <= ILLUMINARTY_MAX_BYTES:
            return image, mime_type
        converted = await _to_jpeg(image)
        return converted or image, "image/jpeg"


def _sniff_mime(data: bytes) -> str:
    """按文件头判断 MIME"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


async def _to_jpeg(data: bytes) -> bytes | None:
    """转 JPEG 并压到 3MB 以内（失败返回 None）"""

    def convert() -> bytes | None:
        try:
            img = Image.open(io.BytesIO(data))
            img.seek(0)
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            max_side = 1500
            if max(img.size) > max_side:
                ratio = max_side / max(img.size)
                img = img.resize(
                    (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                    Image.LANCZOS,
                )
            for quality in (88, 80, 70, 60):
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                payload = buf.getvalue()
                if len(payload) <= ILLUMINARTY_MAX_BYTES:
                    return payload
            return None
        except Exception as exc:
            logger.debug(f"[Illuminarty] 图片转换失败: {exc}")
            return None

    return await asyncio.to_thread(convert)
