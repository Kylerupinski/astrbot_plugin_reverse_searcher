"""Yandex 响应解析测试（data-state 正常 / CAPTCHA / 空结果 / HTTP 错误）"""

import json

from ReverseSearcher.utils.response_parser.yandex_parser import YandexResponse


def _page_with_state(sites: list) -> str:
    state = {"initialState": {"cbirSites": {"sites": sites}}}
    return (
        "<html><body>"
        '<div class="Root" id="ImagesApp-123" data-state=\''
        + json.dumps(state, ensure_ascii=False)
        + "'></div></body></html>"
    )


class TestParseState:
    def test_sites_parsed(self):
        html = _page_with_state(
            [
                {
                    "url": "https://example.com/page",
                    "title": "示例标题",
                    "description": "描述文本",
                    "domain": "example.com",
                    "thumb": {"url": "//avatars.mds.yandex.net/i?id=1"},
                    "originalImage": {"width": 800, "height": 600},
                }
            ]
        )
        resp = YandexResponse(html, "https://yandex.com/images/search", status_code=200)
        assert resp.error == ""
        assert len(resp.raw) == 1
        item = resp.raw[0]
        assert item.title == "示例标题"
        assert item.thumbnail == "https://avatars.mds.yandex.net/i?id=1"
        assert item.author == "example.com"
        assert "800x600" in item.other_info
        assert resp.show_result().startswith("标题: 示例标题")

    def test_empty_sites_sets_reason(self):
        resp = YandexResponse(
            _page_with_state([]), "https://yandex.com/images/search", status_code=200
        )
        assert resp.raw == []
        assert "未返回相似图片" in resp.error
        assert resp.show_result() == resp.error


class TestErrorPages:
    def test_captcha_page(self):
        html = "<html><body><div class='captcha'>Are you a robot?</div></body></html>"
        resp = YandexResponse(html, "https://yandex.com/images/search", status_code=200)
        assert resp.raw == []
        assert "CAPTCHA" in resp.error
        assert resp.show_result() == resp.error

    def test_missing_data_state(self):
        resp = YandexResponse(
            "<html><body>nothing here</body></html>",
            "https://yandex.com/images/search",
            status_code=200,
        )
        assert resp.raw == []
        assert "data-state" in resp.error

    def test_http_error_status(self):
        resp = YandexResponse(
            "<html>blocked</html>", "https://yandex.com/images/search", status_code=429
        )
        assert resp.raw == []
        assert "429" in resp.error

    def test_invalid_json_state(self):
        resp = YandexResponse(
            '<div class="Root" id="ImagesApp-1" data-state="{not json}"></div>',
            "https://yandex.com/images/search",
            status_code=200,
        )
        assert resp.raw == []
        assert "JSON" in resp.error
