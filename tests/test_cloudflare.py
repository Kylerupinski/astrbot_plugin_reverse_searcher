"""全局 Cloudflare 过盾（FlareSolverr）测试"""

import asyncio

from ReverseSearcher.utils.cloudflare import (
    CfSolution,
    FlareSolverrClient,
    cookie_header,
    is_cloudflare_challenge,
    parse_cookie_header,
)

CF_PAGE = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    "<body><div id='cf-chl'>checking your browser</div></body></html>"
)


class TestDetection:
    def test_cf_page(self):
        assert is_cloudflare_challenge(403, {}, CF_PAGE) is True

    def test_cf_header(self):
        assert is_cloudflare_challenge(403, {"cf-mitigated": "challenge"}, "") is True

    def test_attention_required(self):
        assert (
            is_cloudflare_challenge(503, {}, "<title>Attention Required!</title>")
            is True
        )

    def test_rate_limit_json_is_not_cf(self):
        body = '{"detail": "\u5f53\u524d\u641c\u7d22\u4efb\u52a1\u8f83\u591a"}'
        assert is_cloudflare_challenge(429, {}, body) is False

    def test_success_is_not_cf(self):
        assert is_cloudflare_challenge(200, {}, CF_PAGE) is False

    def test_none_status(self):
        assert is_cloudflare_challenge(None, {}, CF_PAGE) is False


class TestCookies:
    def test_parse_and_build(self):
        cookies = parse_cookie_header("cf_clearance=abc; __cf_bm=xyz; bad; =empty")
        assert cookies == {"cf_clearance": "abc", "__cf_bm": "xyz"}
        assert cookie_header(cookies) == "cf_clearance=abc; __cf_bm=xyz"

    def test_parse_empty(self):
        assert parse_cookie_header("") == {}
        assert parse_cookie_header(None) == {}


class TestFlareSolverrClient:
    def test_disabled_without_url(self):
        client = FlareSolverrClient("")
        assert client.enabled is False
        assert asyncio.run(client.solve("https://example.com/")) is None

    def test_disabled_flag(self):
        client = FlareSolverrClient("http://solver:8191", enabled=False)
        assert client.enabled is False

    def _patch_client(self, monkeypatch, payload, status_code=200, calls=None):
        calls = calls if calls is not None else []

        class _Resp:
            def __init__(self, payload, code):
                self._payload = payload
                self.status_code = code
                self.text = "" if payload is None else str(payload)

            def json(self):
                if self._payload is None:
                    raise ValueError("not json")
                return self._payload

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                calls.append((url, json))
                return _Resp(payload, status_code)

        import ReverseSearcher.utils.cloudflare as mod

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
        return calls

    def test_solve_success_and_cache(self, monkeypatch):
        payload = {
            "status": "ok",
            "solution": {
                "status": 200,
                "cookies": [
                    {"name": "cf_clearance", "value": "token"},
                    {"name": "__cf_bm", "value": "bm"},
                ],
                "userAgent": "UA-FROM-SOLVER",
            },
        }
        calls = self._patch_client(monkeypatch, payload)
        client = FlareSolverrClient("http://solver:8191", timeout=30)

        solution = asyncio.run(client.solve("https://soutubot.moe/"))
        assert isinstance(solution, CfSolution)
        assert solution.cookies == {"cf_clearance": "token", "__cf_bm": "bm"}
        assert solution.user_agent == "UA-FROM-SOLVER"
        assert calls[0][0] == "http://solver:8191/v1"
        assert calls[0][1]["cmd"] == "request.get"
        assert calls[0][1]["maxTimeout"] == 30000

        # 同一目标 URL 复用缓存，不再请求 FlareSolverr
        assert asyncio.run(client.solve("https://soutubot.moe/")) is not None
        assert len(calls) == 1

    def test_solve_includes_proxy(self, monkeypatch):
        payload = {
            "status": "ok",
            "solution": {"cookies": [{"name": "cf_clearance", "value": "t"}]},
        }
        calls = self._patch_client(monkeypatch, payload)
        client = FlareSolverrClient("http://solver:8191", proxy="http://127.0.0.1:7890")
        assert asyncio.run(client.solve("https://example.com/")) is not None
        assert calls[0][1]["proxy"] == {"url": "http://127.0.0.1:7890"}

    def test_solver_error_status(self, monkeypatch):
        self._patch_client(
            monkeypatch, {"status": "error", "message": "challenge not solved"}
        )
        client = FlareSolverrClient("http://solver:8191")
        assert asyncio.run(client.solve("https://example.com/")) is None

    def test_solver_http_error(self, monkeypatch):
        self._patch_client(monkeypatch, {"status": "ok"}, status_code=500)
        client = FlareSolverrClient("http://solver:8191")
        assert asyncio.run(client.solve("https://example.com/")) is None

    def test_solver_no_cookies(self, monkeypatch):
        self._patch_client(monkeypatch, {"status": "ok", "solution": {"cookies": []}})
        client = FlareSolverrClient("http://solver:8191")
        assert asyncio.run(client.solve("https://example.com/")) is None

    def test_solver_connection_error(self, monkeypatch):
        import ReverseSearcher.utils.cloudflare as mod

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise OSError("connection refused")

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
        client = FlareSolverrClient("http://solver:8191")
        assert asyncio.run(client.solve("https://example.com/")) is None
