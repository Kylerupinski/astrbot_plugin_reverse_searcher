"""Google Lens / SerpApi 错误响应处理测试"""

import json

import pytest

from ReverseSearcher.utils.api_request.google_lens_req import (
    SearchAPIError,
    _parse_json_body,
)
from ReverseSearcher.utils.response_parser.google_lens_parser import GoogleLensResponse


class _Resp:
    def __init__(self, text="", status_code=200, payload=None):
        self.text = text
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TestSerpApiErrorPayload:
    def test_error_field_is_surfaced(self):
        payload = {
            "search_metadata": {"status": "Success"},
            "error": "Google Lens hasn't returned any results for this query.",
        }
        resp = GoogleLensResponse(json.dumps(payload), "https://serpapi.com/search")
        assert resp.raw == []
        assert "hasn't returned any results" in resp.error
        assert resp.show_result() == resp.error

    def test_error_does_not_discard_visual_matches(self):
        payload = {
            "search_metadata": {"status": "Success"},
            "error": "Some warning",
            "visual_matches": [{"title": "t", "link": "https://example.com"}],
        }
        resp = GoogleLensResponse(json.dumps(payload), "https://serpapi.com/search")
        assert len(resp.raw) == 1
        assert resp.show_result().startswith("Google Lens Result:")


class TestAiOverviewShapes:
    def test_list_shape(self):
        payload = {
            "search_metadata": {"status": "Success"},
            "ai_overview": [{"text": "第一段"}, {"snippet": "第二段"}],
            "visual_matches": [{"title": "t", "link": "https://example.com"}],
        }
        resp = GoogleLensResponse(json.dumps(payload), "https://serpapi.com/search")
        assert "第一段" in resp.ai_overview
        assert "第二段" in resp.ai_overview

    def test_text_blocks_shape(self):
        payload = {
            "search_metadata": {"status": "Success"},
            "ai_overview": {"text_blocks": [{"snippet": "块内容"}]},
            "visual_matches": [{"title": "t", "link": "https://example.com"}],
        }
        resp = GoogleLensResponse(json.dumps(payload), "https://serpapi.com/search")
        assert resp.ai_overview == "块内容"


class TestNonJsonBody:
    def test_html_error_page_raises_api_error(self):
        with pytest.raises(SearchAPIError) as excinfo:
            _parse_json_body(
                _Resp(text="<html>502 Bad Gateway</html>", status_code=502), "SerpApi"
            )
        assert "502" in str(excinfo.value)
        assert "Bad Gateway" in str(excinfo.value)

    def test_json_body_ok(self):
        data = _parse_json_body(_Resp(payload={"ok": True}), "SerpApi")
        assert data == {"ok": True}
