"""AnimeTrace 响应解析测试（正常结果 / 额度耗尽 / 畸形条目）

旧实现直接 resp_data["code"] / resp_data["data"]，额度耗尽时 data 是 {}，
会把字典键当结果项解析并抛异常，最终只剩一张含糊的错误卡片。
"""

from ReverseSearcher.utils.response_parser.anime_trace_parser import AnimeTraceResponse


def _response(payload: dict) -> AnimeTraceResponse:
    return AnimeTraceResponse(payload, "https://api.animetrace.com/v1/search")


class TestNormal:
    def test_characters_parsed(self):
        resp = _response(
            {
                "code": 0,
                "ai": False,
                "trace_id": "t1",
                "data": [
                    {
                        "box": [0.1, 0.2, 0.5, 0.6],
                        "box_id": "b1",
                        "character": [{"character": "角色A", "work": "作品A"}],
                    }
                ],
            }
        )
        assert resp.error == ""
        assert resp.ai is False
        assert len(resp.raw) == 1
        assert resp.raw[0].characters[0].name == "角色A"
        assert resp.raw[0].box == [0.1, 0.2, 0.5, 0.6]
        text = resp.show_result()
        assert "作品名: 作品A" in text
        assert "角色名: 角色A" in text

    def test_malformed_item_skipped(self):
        resp = _response(
            {
                "code": 0,
                "data": [
                    "not-a-dict",
                    {"box": [0, 0, 1, 1], "box_id": "x", "character": []},
                ],
            }
        )
        assert len(resp.raw) == 1


class TestQuotaExhausted:
    def test_message_returned_instead_of_exception(self):
        resp = _response(
            {
                "code": 17728,
                "message": "今回の使用上限に達しました",
                "zh_message": "已达到本次使用上限",
                "data": {},
            }
        )
        assert resp.raw == []
        assert "已达到本次使用上限" in resp.error
        assert resp.show_result() == resp.error

    def test_missing_data_field(self):
        resp = _response({"code": 500, "message": "boom"})
        assert resp.raw == []
        assert "boom" in resp.error
        assert resp.show_result() == resp.error

    def test_no_characters_no_error_returns_none(self):
        resp = _response(
            {"code": 0, "data": [{"box": [0, 0, 1, 1], "box_id": "x", "character": []}]}
        )
        assert resp.raw
        assert resp.show_result() is None
