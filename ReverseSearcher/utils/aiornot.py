"""AI or Not 图片 AI 生成检测

官方文档：https://docs.aiornot.com/api-reference/reports-by-modality/image

接口：
    POST https://api.aiornot.com/v2/image/sync
    Authorization: Bearer <API Key>
    multipart/form-data: image=<图片文件>
    可选 query: only=ai_generated（只跑 AI 生成检测，避免 deepfake 等额外计费）

返回（节选）：
    {
      "report": {
        "ai_generated": {
          "verdict": "ai" | "human" | "unknown",
          "ai":    {"is_detected": true,  "confidence": 0.97},
          "human": {"is_detected": false, "confidence": 0.03},
          "generator": {"midjourney": {"confidence": 0.9}, ...}
        }
      }
    }

本模块把检测结果整理成可直接展示的徽章/文本；任何失败都返回带 error 的结果，
不会抛异常影响后续搜图。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

from .network import Network

AIORNOT_ENDPOINT = "https://api.aiornot.com/v2/image/sync"

# 官方限制：单次请求图片不超过 10MB
AIORNOT_MAX_BYTES = 10 * 1024 * 1024

# verdict -> (tone, 中文判定)
_VERDICT_TEXT = {
    "ai": ("warn", "AI 生成"),
    "human": ("ok", "非 AI 生成"),
    "unknown": ("neutral", "无法判定"),
}


@dataclass
class AIDetectionResult:
    """一次 AI 生成检测的结果"""

    verdict: str = "unknown"  # ai / human / unknown / error
    ai_probability: float | None = None
    generator: str = ""
    provider: str = "AI or Not"
    fallback_note: str = ""
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error) or self.verdict == "error"

    def _percent(self) -> str:
        if self.ai_probability is None:
            return ""
        try:
            value = float(self.ai_probability)
        except (TypeError, ValueError):
            return ""
        return f"{max(0.0, min(1.0, value)) * 100:.0f}%"

    def label(self) -> str:
        """用于卡片徽章/文本一行的短标签（不含 emoji，PIL 字体无 emoji 字形）"""
        if self.failed:
            reason = (self.error or "未知错误").strip()
            if len(reason) > 80:
                reason = reason[:77] + "..."
            return f"{self.provider} 检测失败：{reason}"

        verdict_cn = _VERDICT_TEXT.get(self.verdict, _VERDICT_TEXT["unknown"])[1]
        percent = self._percent()
        if self.verdict == "unknown":
            return f"{self.provider}：无法判定（可能画质过低）"
        text = f"{self.provider}：{verdict_cn}"
        if percent:
            text += f"，AI 生成概率 {percent}"
        if self.verdict == "ai" and self.generator:
            text += f"（疑似 {self.generator}）"
        return text

    def text_line(self) -> str:
        """纯文本模式展示的一行（带 emoji，平台字体可正常渲染）"""
        return f"🤖 {self.label()}"

    def tone(self) -> str:
        """徽章配色：warn / ok / neutral"""
        if self.failed:
            return "neutral"
        return _VERDICT_TEXT.get(self.verdict, _VERDICT_TEXT["unknown"])[0]

    def verdict_text(self) -> str:
        """判定结果的中文文案"""
        if self.failed:
            return "检测失败"
        return _VERDICT_TEXT.get(self.verdict, _VERDICT_TEXT["unknown"])[1]

    def probability_text(self) -> str:
        """AI 生成概率文案（无法取得时为 —）"""
        if self.failed:
            return "—"
        return self._percent() or "—"

    def text_block(self) -> str:
        """多行文本（纯文本模式下展示）"""
        if self.failed:
            return self.text_line()
        lines = [
            "🤖 AI 生成检测结果",
            f"检测来源：{self.provider}"
            + (f"（{self.fallback_note}）" if self.fallback_note else ""),
            f"判定：{self.verdict_text()}",
            f"AI 生成概率：{self.probability_text()}",
        ]
        if self.verdict == "ai" and self.generator:
            lines.append(f"疑似生成器：{self.generator}")
        return "\n".join(lines)

    def badge(self) -> dict:
        """卡片渲染使用的徽章结构（text 为文本模式用的带 emoji 版本）"""
        return {"label": self.label(), "tone": self.tone(), "text": self.text_line()}


def _guess_image_type(data: bytes) -> tuple[str, str]:
    """按文件头猜图片类型，返回 (文件名, MIME)，用于 multipart 上传"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image.png", "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image.webp", "image/webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image.tiff", "image/tiff"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image.gif", "image/gif"
    return "image.jpg", "image/jpeg"


class AIorNotDetector:
    """AI or Not v2 同步检测客户端"""

    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = (api_key or "").strip()
        self.timeout = float(timeout or 20)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def detect(
        self, image: bytes, network_kwargs: dict | None = None
    ) -> AIDetectionResult:
        """检测图片是否为 AI 生成

        参数:
            image: 图片字节（jpg/png/webp 等）
            network_kwargs: 代理/超时等连接参数

        返回:
            AIDetectionResult: 成功时为 ai/human/unknown，失败时 error 非空
        """
        if not self.enabled:
            return AIDetectionResult(verdict="error", error="未配置 AI or Not API Key")
        if not image:
            return AIDetectionResult(verdict="error", error="图片内容为空")
        if len(image) > AIORNOT_MAX_BYTES:
            return AIDetectionResult(
                verdict="error", error="图片超过 10MB，AI or Not 拒绝处理"
            )

        filename, mime_type = _guess_image_type(image)
        try:
            async with Network(**(network_kwargs or {})) as client:
                resp = await client.post(
                    AIORNOT_ENDPOINT,
                    params={"only": ["ai_generated"]},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"image": (filename, image, mime_type)},
                    timeout=self.timeout,
                )
        except Exception as exc:
            logger.warning(f"[AIorNot] 请求失败: {type(exc).__name__}: {exc}")
            return AIDetectionResult(
                verdict="error", error=f"请求失败（{type(exc).__name__}）"
            )

        if resp.status_code != 200:
            snippet = (resp.text or "").strip().replace("\n", " ")[:160]
            logger.warning(f"[AIorNot] 接口返回 HTTP {resp.status_code}: {snippet}")
            return AIDetectionResult(
                verdict="error", error=f"HTTP {resp.status_code}：{snippet}"
            )

        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return AIDetectionResult(verdict="error", error="返回内容不是合法 JSON")

        report = data.get("report") if isinstance(data, dict) else None
        ai_report = report.get("ai_generated") if isinstance(report, dict) else None
        if not isinstance(ai_report, dict):
            return AIDetectionResult(
                verdict="error", error="返回中缺少 ai_generated 检测结果"
            )

        verdict = str(ai_report.get("verdict") or "unknown").strip().lower()
        if verdict not in _VERDICT_TEXT:
            verdict = "unknown"

        return AIDetectionResult(
            verdict=verdict,
            ai_probability=_read_confidence(ai_report.get("ai")),
            generator=_top_generator(ai_report.get("generator")),
        )


def _read_confidence(block: Any) -> float | None:
    """读取 ai.confidence（0~1）"""
    if not isinstance(block, dict):
        return None
    value = block.get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _top_generator(block: Any) -> str:
    """取置信度最高的生成器名称（如 Midjourney），置信度太低则不展示"""
    if not isinstance(block, dict):
        return ""
    best_name, best_conf = "", 0.0
    for name, pred in block.items():
        confidence = _read_confidence(pred)
        if confidence is None or confidence < 0.5:
            continue
        if confidence > best_conf:
            best_name, best_conf = name, confidence
    return best_name.replace("_", " ").title() if best_name else ""
