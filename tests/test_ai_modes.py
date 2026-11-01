"""AI 检测双通道模式（both / fallback）与控制台告警测试"""

import asyncio
import io
import logging

from PIL import Image

from ReverseSearcher.model import BaseSearchModel
from ReverseSearcher.utils.aiornot import AIDetectionResult


def _png(width=90, height=90) -> bytes:
    img = Image.new("RGB", (width, height), (30, 120, 200))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _model(**kwargs) -> BaseSearchModel:
    return BaseSearchModel(proxies=None, timeout=20, default_params={}, **kwargs)


def _fake(detector, monkeypatch, result):
    async def _detect(image, network_kwargs=None):
        return result

    monkeypatch.setattr(detector, "detect", _detect)


class TestBothMode:
    def test_runs_both_channels(self, monkeypatch):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        calls = []

        async def primary(image, network_kwargs=None):
            calls.append("primary")
            return AIDetectionResult(verdict="ai", ai_probability=0.15)

        async def fallback(image, network_kwargs=None):
            calls.append("fallback")
            return AIDetectionResult(
                verdict="ai", ai_probability=0.82, provider="Illuminarty"
            )

        monkeypatch.setattr(model.ai_detector, "detect", primary)
        monkeypatch.setattr(model.illuminarty_detector, "detect", fallback)

        results = asyncio.run(model.detect_ai_all(file=_png()))
        assert sorted(calls) == ["fallback", "primary"]
        assert [r.provider for r in results] == ["AI or Not", "Illuminarty"]
        assert [r.ai_probability for r in results] == [0.15, 0.82]

    def test_badges_include_both_channels(self, monkeypatch):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="human", ai_probability=0.15),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(
                verdict="ai", ai_probability=0.82, provider="Illuminarty"
            ),
        )
        badges = asyncio.run(model._precheck_ai(file=_png()))
        assert len(badges) == 2
        assert badges[0]["label"].startswith("AI or Not：")
        assert badges[1]["label"].startswith("Illuminarty：")
        assert badges[0]["tone"] == "ok"
        assert badges[1]["tone"] == "warn"

    def test_text_output_lists_both_results(self, monkeypatch):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="human", ai_probability=0.15),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(
                verdict="ai", ai_probability=0.82, provider="Illuminarty"
            ),
        )
        messages = asyncio.run(model.search_text_messages(api="ai", file=_png()))
        text = messages[0]["text"]
        assert "AI or Not" in text
        assert "Illuminarty" in text
        assert "15%" in text
        assert "82%" in text

    def test_detect_ai_returns_first_success(self, monkeypatch):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="human", ai_probability=0.1),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(verdict="ai", ai_probability=0.9, provider="Illuminarty"),
        )
        result = asyncio.run(model.detect_ai(file=_png()))
        assert result.provider == "AI or Not"

    def test_one_channel_failure_keeps_other(self, monkeypatch, caplog):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="error", error="HTTP 402：quota"),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(verdict="ai", ai_probability=0.7, provider="Illuminarty"),
        )
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            results = asyncio.run(model.detect_ai_all(file=_png()))
        assert len(results) == 2
        assert results[0].failed
        assert results[1].verdict == "ai"
        assert "AI 检测通道不可用" in caplog.text
        assert "HTTP 402" in caplog.text

    def test_invalid_mode_defaults_to_fallback(self):
        model = _model(ai_detect_mode="weird")
        assert model.ai_detect_mode == "fallback"


class TestWarnings:
    def test_fallback_mode_warns_when_primary_fails(self, monkeypatch, caplog):
        model = _model(aiornot_api_key="k", illuminarty_enabled=True)
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="error", error="HTTP 401：bad key"),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(
                verdict="human", ai_probability=0.1, provider="Illuminarty"
            ),
        )
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            asyncio.run(model.detect_ai_all(file=_png()))
        assert "AI or Not" in caplog.text
        assert "HTTP 401" in caplog.text

    def test_warns_for_each_failed_channel(self, monkeypatch, caplog):
        model = _model(
            aiornot_api_key="k", illuminarty_enabled=True, ai_detect_mode="both"
        )
        _fake(
            model.ai_detector,
            monkeypatch,
            AIDetectionResult(verdict="error", error="boom-a"),
        )
        _fake(
            model.illuminarty_detector,
            monkeypatch,
            AIDetectionResult(verdict="error", provider="Illuminarty", error="boom-b"),
        )
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            asyncio.run(model.detect_ai_all(file=_png()))
        assert "boom-a" in caplog.text
        assert "boom-b" in caplog.text
        assert caplog.text.count("AI 检测通道不可用") == 2

    def test_disabled_channels_do_not_warn(self, caplog):
        model = _model()
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            results = asyncio.run(model.detect_ai_all(file=_png()))
        assert results == []
        assert caplog.text == ""


class TestAICardRendering:
    def test_render_card_with_two_channels(self):
        from ReverseSearcher.utils.render_card import ResultCardRenderer

        detections = [
            AIDetectionResult(verdict="human", ai_probability=0.15),
            AIDetectionResult(
                verdict="ai", ai_probability=0.82, provider="Illuminarty"
            ),
        ]
        card = ResultCardRenderer().render_ai_pil("ai", detections, None)
        assert card.width == ResultCardRenderer.CARD_WIDTH
        assert card.height > 300

    def test_render_card_with_error_block(self):
        from ReverseSearcher.utils.render_card import ResultCardRenderer

        detections = [
            AIDetectionResult(verdict="error", error="HTTP 402：quota"),
            AIDetectionResult(
                verdict="ai", ai_probability=0.82, provider="Illuminarty"
            ),
        ]
        card = ResultCardRenderer().render_ai_pil("ai", detections, None)
        assert card.height > 240

    def test_render_card_accepts_single_result(self):
        from ReverseSearcher.utils.render_card import ResultCardRenderer

        card = ResultCardRenderer().render_ai_pil(
            "ai", AIDetectionResult(verdict="ai", ai_probability=0.5), None
        )
        assert card.width == ResultCardRenderer.CARD_WIDTH
