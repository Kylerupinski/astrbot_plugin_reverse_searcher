"""Illuminarty 免费备用检测与「AI or Not → Illuminarty」回退链测试"""

import asyncio
import io
import json

from PIL import Image, ImageDraw

from ReverseSearcher.model import BaseSearchModel
from ReverseSearcher.utils import illuminarty as illum
from ReverseSearcher.utils.aiornot import AIDetectionResult
from ReverseSearcher.utils.illuminarty import IlluminartyDetector


class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Client:
    status_code = 200
    body = "{}"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _Resp(self.status_code, self.body)


def _patch_network(monkeypatch, status_code=200, body="{}"):
    holder = {}

    class _Net(_Client):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.status_code = status_code
            self.body = body
            holder["client"] = self

    monkeypatch.setattr(illum, "Network", _Net)
    return holder


def _ok(probability):
    return json.dumps(
        {"data": {"probability": probability, "details": {}}, "status": "success"}
    )


def _png(width=120, height=120) -> bytes:
    img = Image.new("RGB", (width, height), (30, 120, 200))
    ImageDraw.Draw(img).rectangle((20, 20, 90, 90), fill=(240, 60, 60))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _gif() -> bytes:
    img = Image.new("RGB", (64, 64), (10, 200, 120))
    buf = io.BytesIO()
    img.save(buf, "GIF")
    return buf.getvalue()


class TestIlluminartyDetector:
    def test_high_probability_is_ai(self, monkeypatch):
        holder = _patch_network(monkeypatch, body=_ok(0.93))
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))

        assert not result.failed
        assert result.verdict == "ai"
        assert result.ai_probability == 0.93
        assert result.provider == "Illuminarty"
        assert result.tone() == "warn"
        assert "Illuminarty" in result.label()

        url, kwargs = holder["client"].posts[0]
        assert url == illum.ILLUMINARTY_ENDPOINT
        assert "file" in kwargs["files"]
        assert kwargs["headers"]["Origin"] == "https://app.illuminarty.ai"

    def test_low_probability_is_human(self, monkeypatch):
        _patch_network(monkeypatch, body=_ok(0.02))
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.verdict == "human"
        assert result.tone() == "ok"

    def test_threshold_boundary(self, monkeypatch):
        _patch_network(monkeypatch, body=_ok(0.5))
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.verdict == "ai"

    def test_http_error(self, monkeypatch):
        _patch_network(monkeypatch, status_code=502, body="bad gateway")
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.failed
        assert "HTTP 502" in result.error

    def test_invalid_json(self, monkeypatch):
        _patch_network(monkeypatch, body="<html>")
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.failed
        assert "JSON" in result.error

    def test_status_not_success(self, monkeypatch):
        _patch_network(
            monkeypatch,
            body=json.dumps({"status": "error", "message": "rate limited"}),
        )
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.failed
        assert "rate limited" in result.error

    def test_missing_probability(self, monkeypatch):
        _patch_network(monkeypatch, body=json.dumps({"status": "success", "data": {}}))
        result = asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        assert result.failed
        assert "probability" in result.error

    def test_disabled_detector(self):
        result = asyncio.run(IlluminartyDetector(enabled=False).detect(_png()))
        assert result.failed
        assert "未启用" in result.error

    def test_gif_is_converted_to_jpeg(self, monkeypatch):
        holder = _patch_network(monkeypatch, body=_ok(0.1))
        asyncio.run(IlluminartyDetector(enabled=True).detect(_gif()))
        _url, kwargs = holder["client"].posts[0]
        filename, payload, mime = kwargs["files"]["file"]
        assert mime == "image/jpeg"
        assert payload[:2] == b"\xff\xd8"
        assert filename.endswith(".jpg")

    def test_png_kept_as_png(self, monkeypatch):
        holder = _patch_network(monkeypatch, body=_ok(0.1))
        asyncio.run(IlluminartyDetector(enabled=True).detect(_png()))
        _url, kwargs = holder["client"].posts[0]
        _fn, payload, mime = kwargs["files"]["file"]
        assert mime == "image/png"
        assert payload == _png()


def _model(**kwargs) -> BaseSearchModel:
    return BaseSearchModel(proxies=None, timeout=20, default_params={}, **kwargs)


class TestFallbackChain:
    def test_ai_or_not_success_skips_illuminarty(self, monkeypatch):
        model = _model(aiornot_api_key="k", illuminarty_enabled=True)
        calls = []

        async def primary(image, network_kwargs=None):
            calls.append("primary")
            return AIDetectionResult(verdict="ai", ai_probability=0.9)

        async def fallback(image, network_kwargs=None):
            calls.append("fallback")
            return AIDetectionResult(verdict="human", ai_probability=0.1)

        monkeypatch.setattr(model.ai_detector, "detect", primary)
        monkeypatch.setattr(model.illuminarty_detector, "detect", fallback)
        result = asyncio.run(model.detect_ai(file=_png()))
        assert result.verdict == "ai"
        assert calls == ["primary"]

    def test_falls_back_when_primary_fails(self, monkeypatch):
        model = _model(aiornot_api_key="k", illuminarty_enabled=True)
        calls = []

        async def primary(image, network_kwargs=None):
            calls.append("primary")
            return AIDetectionResult(verdict="error", error="HTTP 402：quota")

        async def fallback(image, network_kwargs=None):
            calls.append("fallback")
            return AIDetectionResult(
                verdict="ai", ai_probability=0.88, provider="Illuminarty"
            )

        monkeypatch.setattr(model.ai_detector, "detect", primary)
        monkeypatch.setattr(model.illuminarty_detector, "detect", fallback)
        result = asyncio.run(model.detect_ai(file=_png()))
        assert result.verdict == "ai"
        assert result.provider == "Illuminarty"
        assert "已自动切换" in result.fallback_note
        assert calls == ["primary", "fallback"]

    def test_both_fail_returns_combined_error(self, monkeypatch):
        model = _model(aiornot_api_key="k", illuminarty_enabled=True)

        async def primary(image, network_kwargs=None):
            return AIDetectionResult(verdict="error", error="HTTP 402：quota")

        async def fallback(image, network_kwargs=None):
            return AIDetectionResult(
                verdict="error", provider="Illuminarty", error="HTTP 502：bad"
            )

        monkeypatch.setattr(model.ai_detector, "detect", primary)
        monkeypatch.setattr(model.illuminarty_detector, "detect", fallback)
        results = asyncio.run(model.detect_ai_all(file=_png()))
        assert [r.failed for r in results] == [True, True]
        combined = "；".join(f"{r.provider}：{r.error}" for r in results)
        assert "AI or Not" in combined
        assert "Illuminarty" in combined

    def test_illuminarty_only(self, monkeypatch):
        model = _model(illuminarty_enabled=True)
        assert model.ai_detect_available is True

        async def fallback(image, network_kwargs=None):
            return AIDetectionResult(
                verdict="human", ai_probability=0.05, provider="Illuminarty"
            )

        monkeypatch.setattr(model.illuminarty_detector, "detect", fallback)
        result = asyncio.run(model.detect_ai(file=_png()))
        assert result.verdict == "human"
        assert result.provider == "Illuminarty"

    def test_ai_engine_text_uses_fallback_provider(self, monkeypatch):
        model = _model(illuminarty_enabled=True)

        async def fallback(file=None, url=None, require_enabled=False):
            return [
                AIDetectionResult(
                    verdict="ai",
                    ai_probability=0.77,
                    provider="Illuminarty",
                    fallback_note="AI or Not 不可用，已自动切换备用",
                )
            ]

        monkeypatch.setattr(model, "detect_ai_all", fallback)
        messages = asyncio.run(model.search_text_messages(api="ai", file=_png()))
        text = messages[0]["text"]
        assert "检测来源：Illuminarty" in text
        assert "已自动切换备用" in text
        assert "77%" in text

    def test_precheck_badge_mentions_provider(self, monkeypatch):
        model = _model(illuminarty_enabled=True)

        async def fake_detect_all(file=None, url=None, require_enabled=False):
            return [
                AIDetectionResult(
                    verdict="human", ai_probability=0.03, provider="Illuminarty"
                )
            ]

        monkeypatch.setattr(model, "detect_ai_all", fake_detect_all)
        badges = asyncio.run(model._precheck_ai(file=_png()))
        assert badges[0]["label"].startswith("Illuminarty：")
