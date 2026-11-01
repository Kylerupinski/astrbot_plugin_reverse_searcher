"""AI or Not 检测与「AI 检测」引擎测试"""

import asyncio
import io
import json

from PIL import Image, ImageDraw

from ReverseSearcher.model import BaseSearchModel
from ReverseSearcher.utils import aiornot
from ReverseSearcher.utils.aiornot import AIDetectionResult, AIorNotDetector


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
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
        return _FakeResponse(self.status_code, self.body)


def _patch_network(monkeypatch, status_code=200, body="{}"):
    holder = {}

    class _Net(_FakeClient):
        status_code = None
        body = None

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.status_code = status_code
            self.body = body
            holder["client"] = self

    monkeypatch.setattr(aiornot, "Network", _Net)
    return holder


def _report(verdict="ai", confidence=0.97, generator=None):
    return json.dumps(
        {
            "id": "abc",
            "report": {
                "ai_generated": {
                    "verdict": verdict,
                    "ai": {"is_detected": verdict == "ai", "confidence": confidence},
                    "human": {
                        "is_detected": verdict == "human",
                        "confidence": 1 - confidence,
                    },
                    "generator": generator or {},
                },
                "meta": {},
            },
        }
    )


class TestDetector:
    def test_detects_ai(self, monkeypatch):
        body = _report("ai", 0.97, {"midjourney": {"confidence": 0.9}})
        holder = _patch_network(monkeypatch, body=body)
        result = asyncio.run(AIorNotDetector("key-123").detect(b"\xff\xd8imagebytes"))

        assert result.verdict == "ai"
        assert result.ai_probability == 0.97
        assert result.generator == "Midjourney"
        assert result.tone() == "warn"
        assert "97%" in result.label()
        assert "AI 生成" in result.label()

        url, kwargs = holder["client"].posts[0]
        assert url == aiornot.AIORNOT_ENDPOINT
        assert kwargs["headers"]["Authorization"] == "Bearer key-123"
        assert kwargs["params"] == {"only": ["ai_generated"]}
        assert kwargs["files"]["image"][0] == "image.jpg"

    def test_detects_human(self, monkeypatch):
        _patch_network(monkeypatch, body=_report("human", 0.03))
        result = asyncio.run(AIorNotDetector("key").detect(b"img"))
        assert result.verdict == "human"
        assert result.tone() == "ok"
        assert "非 AI 生成" in result.label()

    def test_unknown_verdict(self, monkeypatch):
        _patch_network(monkeypatch, body=_report("something-else", 0.5))
        result = asyncio.run(AIorNotDetector("key").detect(b"img"))
        assert result.verdict == "unknown"
        assert result.tone() == "neutral"
        assert "无法判定" in result.label()

    def test_http_error_is_reported(self, monkeypatch):
        _patch_network(
            monkeypatch, status_code=401, body='{"detail":"Invalid API key"}'
        )
        result = asyncio.run(AIorNotDetector("bad").detect(b"img"))
        assert result.failed
        assert "HTTP 401" in result.label()
        assert result.tone() == "neutral"

    def test_invalid_json(self, monkeypatch):
        _patch_network(monkeypatch, body="<html>gateway</html>")
        result = asyncio.run(AIorNotDetector("key").detect(b"img"))
        assert result.failed
        assert "JSON" in result.error

    def test_missing_report(self, monkeypatch):
        _patch_network(monkeypatch, body=json.dumps({"id": "x"}))
        result = asyncio.run(AIorNotDetector("key").detect(b"img"))
        assert result.failed
        assert "ai_generated" in result.error

    def test_request_exception_is_contained(self, monkeypatch):
        class _Boom:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                raise RuntimeError("network down")

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(aiornot, "Network", _Boom)
        result = asyncio.run(AIorNotDetector("key").detect(b"img"))
        assert result.failed
        assert "请求失败" in result.error

    def test_without_api_key(self):
        result = asyncio.run(AIorNotDetector("").detect(b"img"))
        assert result.failed
        assert "API Key" in result.error

    def test_oversized_image_rejected(self, monkeypatch):
        _patch_network(monkeypatch, body=_report())
        detector = AIorNotDetector("key")
        result = asyncio.run(detector.detect(b"x" * (aiornot.AIORNOT_MAX_BYTES + 1)))
        assert result.failed
        assert "10MB" in result.error

    def test_png_upload_sets_png_mime(self, monkeypatch):
        holder = _patch_network(monkeypatch, body=_report())
        png_header = b"\x89PNG\r\n\x1a\n" + b"rest"
        asyncio.run(AIorNotDetector("key").detect(png_header))
        _url, kwargs = holder["client"].posts[0]
        filename, data, mime = kwargs["files"]["image"]
        assert filename == "image.png"
        assert mime == "image/png"
        assert data == png_header


class TestTextFormatting:
    def test_text_block_for_ai(self):
        result = AIDetectionResult(
            verdict="ai", ai_probability=0.913, generator="Stable Diffusion"
        )
        block = result.text_block()
        assert "判定：AI 生成" in block
        assert "91%" in block
        assert "Stable Diffusion" in block

    def test_text_block_for_error(self):
        result = AIDetectionResult(verdict="error", error="HTTP 500：boom")
        block = result.text_block()
        assert "检测失败" in block
        assert "HTTP 500" in block

    def test_badge_structure(self):
        badge = AIDetectionResult(verdict="human", ai_probability=0.01).badge()
        assert badge["tone"] == "ok"
        assert "非 AI 生成" in badge["label"]


def _png_bytes(width=120, height=120) -> bytes:
    img = Image.new("RGB", (width, height), (20, 120, 200))
    ImageDraw.Draw(img).rectangle((20, 20, 90, 90), fill=(240, 60, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeEngineResponse:
    def __init__(self, raw=None, error=""):
        self.raw = raw or []
        self.error = error
        self.ai = None


def _model(**kwargs) -> BaseSearchModel:
    return BaseSearchModel(proxies=None, timeout=30, default_params={}, **kwargs)


class TestModelIntegration:
    def test_ai_engine_text_mode(self, monkeypatch):
        model = _model(aiornot_api_key="key")

        async def fake_detect_all(file=None, url=None, require_enabled=False):
            return [AIDetectionResult(verdict="ai", ai_probability=0.88)]

        monkeypatch.setattr(model, "detect_ai_all", fake_detect_all)
        messages = asyncio.run(model.search_text_messages(api="ai", file=_png_bytes()))
        assert len(messages) == 1
        assert "「AI 检测」" in messages[0]["text"]
        assert "88%" in messages[0]["text"]
        assert messages[0]["image"] is None

    def test_ai_engine_requires_key(self):
        model = _model()
        messages = asyncio.run(model.search_text_messages(api="ai", file=_png_bytes()))
        assert "AI 检测未启用" in messages[0]["text"]

    def test_ai_engine_search_returns_text(self, monkeypatch):
        model = _model(aiornot_api_key="key")

        async def fake_detect_all(file=None, url=None, require_enabled=False):
            return [AIDetectionResult(verdict="human", ai_probability=0.02)]

        monkeypatch.setattr(model, "detect_ai_all", fake_detect_all)
        text = asyncio.run(model.search(api="ai", file=_png_bytes()))
        assert "判定：非 AI 生成" in text

    def test_reverse_search_header_contains_ai_badges(self, monkeypatch):
        model = _model(aiornot_api_key="key")

        async def fake_detect(api, file=None, url=None, **kwargs):
            return _FakeEngineResponse()

        async def fake_precheck(file=None, url=None):
            return [{"label": "🤖 AI or Not：AI 生成概率 80%", "tone": "warn"}]

        monkeypatch.setattr(model, "_search_engine", fake_detect)
        monkeypatch.setattr(model, "_precheck_ai", fake_precheck)
        messages = asyncio.run(
            model.search_text_messages(api="google", file=_png_bytes())
        )
        assert "AI or Not：AI 生成概率 80%" in messages[0]["text"]

    def test_card_mode_passes_badges_to_renderer(self, monkeypatch):
        model = _model(aiornot_api_key="key")
        captured = {}

        async def fake_detect(api, file=None, url=None, **kwargs):
            return _FakeEngineResponse(
                raw=[
                    type(
                        "Item",
                        (),
                        {
                            "title": "t",
                            "url": "https://example.com",
                            "similarity": 90,
                            "source": "s",
                            "author": "",
                            "thumbnail": "",
                        },
                    )()
                ]
            )

        async def fake_precheck(file=None, url=None):
            return [{"label": "🤖 AI or Not：AI 生成概率 90%", "tone": "warn"}]

        async def fake_draw(api, items, source_image=None, ai_badges=None):
            captured["badges"] = ai_badges
            return Image.new("RGB", (10, 10))

        monkeypatch.setattr(model, "_search_engine", fake_detect)
        monkeypatch.setattr(model, "_precheck_ai", fake_precheck)
        monkeypatch.setattr(model, "draw_results", fake_draw)
        asyncio.run(model.search_and_draw(api="google", file=_png_bytes()))
        assert captured["badges"][0]["tone"] == "warn"

    def test_card_mode_ai_engine_draws_ai_card(self, monkeypatch):
        model = _model(aiornot_api_key="key")
        captured = {}

        async def fake_detect_all(file=None, url=None, require_enabled=False):
            return [AIDetectionResult(verdict="ai", ai_probability=0.7)]

        async def fake_draw_ai(api, detections, source_image=None):
            captured["verdict"] = detections[0].verdict
            return Image.new("RGB", (10, 10))

        monkeypatch.setattr(model, "detect_ai_all", fake_detect_all)
        monkeypatch.setattr(model, "draw_ai_result", fake_draw_ai)
        asyncio.run(model.search_and_draw(api="ai", file=_png_bytes()))
        assert captured["verdict"] == "ai"

    def test_detect_ai_disabled_returns_none(self):
        model = _model()
        assert asyncio.run(model.detect_ai(file=_png_bytes())) is None

    def test_detect_ai_reads_bytes(self, monkeypatch):
        model = _model(aiornot_api_key="key")
        seen = {}

        async def fake_detect(image, network_kwargs=None):
            seen["size"] = len(image)
            return AIDetectionResult(verdict="human", ai_probability=0.1)

        monkeypatch.setattr(model.ai_detector, "detect", fake_detect)
        payload = _png_bytes()
        result = asyncio.run(model.detect_ai(file=payload))
        assert result.verdict == "human"
        assert seen["size"] == len(payload)

    def test_unknown_engine_skips_ai_precheck(self, monkeypatch):
        model = _model(aiornot_api_key="key")
        called = []

        async def fake_precheck(file=None, url=None):
            called.append(1)
            return []

        monkeypatch.setattr(model, "_precheck_ai", fake_precheck)
        messages = asyncio.run(
            model.search_text_messages(api="nope", file=_png_bytes())
        )
        assert called == []
        assert "不支持的引擎" in messages[0]["text"]


class TestEmojiStripping:
    def test_strip_emoji_keeps_chinese(self):
        from ReverseSearcher.utils.render_card import _strip_emoji

        cleaned = _strip_emoji("🤖 AI or Not：AI 生成 ⚠️ 92%")
        assert "AI or Not" in cleaned
        assert "AI 生成" in cleaned
        assert "🤖" not in cleaned
        assert "⚠" not in cleaned

    def test_badge_labels_render_clean(self):
        from ReverseSearcher.utils.render_card import _strip_emoji

        badge = AIDetectionResult(verdict="ai", ai_probability=0.9).badge()
        assert _strip_emoji(badge["label"]) == badge["label"]
