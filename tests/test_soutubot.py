"""Soutubot（nhentai 图源）解析与请求测试"""

import asyncio
import json
import logging

from ReverseSearcher.utils.api_request import Soutubot
from ReverseSearcher.utils.cloudflare import CfSolution, is_cloudflare_challenge
from ReverseSearcher.utils.response_parser import SoutubotResponse

SAMPLE = {
    "status": "ok",
    "partial": False,
    "results": [
        {
            "score": 87.5,
            "path_segments": [
                {
                    "page_no": 12,
                    "language": "ja",
                    "external_id": "682359",
                    "thumbnail_url": "https://img.example/682359/012.webp",
                    "source_url": "https://nhentai.net/g/682359",
                    "page_url": "https://nhentai.net/g/682359/12/",
                    "metadata": {
                        "source": {
                            "key": "nhentai",
                            "name": "nhentai",
                            "id": "682359",
                            "url": "https://nhentai.net/g/682359",
                        },
                        "title": {
                            "primary": "[Fly Dish (Jakko)] Otonari Mama -S",
                            "japanese_or_alias": "[フライディッシュ] おとなりママ -S",
                        },
                        "creators": [{"name": "Jakko", "tag": "artist:jakko"}],
                        "tags": {
                            "other": [
                                "tag:sole female",
                                "tag:sole male",
                                "group:fly dish",
                            ]
                        },
                        "facts": {
                            "page_count": 41,
                            "category": "doujinshi",
                            "language": "japanese",
                        },
                    },
                }
            ],
        },
        {
            "score": 60.0,
            "path_segments": [
                {
                    "page_no": 3,
                    "language": "en",
                    "external_id": "682359",
                    "thumbnail_url": "https://img.example/682359/003.webp",
                    "page_url": "https://nhentai.net/g/682359/3/",
                    "metadata": {
                        "source": {
                            "id": "682359",
                            "url": "https://nhentai.net/g/682359",
                        }
                    },
                }
            ],
        },
        {
            "score": 42.0,
            "path_segments": [
                {
                    "page_no": 1,
                    "language": "en",
                    "external_id": "700001",
                    "thumbnail_url": "https://img.example/700001/001.webp",
                    "page_url": "https://nhentai.net/g/700001/1/",
                    "metadata": {
                        "source": {
                            "id": "700001",
                            "url": "https://nhentai.net/g/700001",
                        },
                        "title": {"primary": "Second Work"},
                        "creators": [{"name": "A"}, {"name": "B"}],
                        "facts": {"page_count": 20, "category": "manga"},
                    },
                }
            ],
        },
    ],
}


def _resp(**kwargs) -> SoutubotResponse:
    return SoutubotResponse(json.dumps(kwargs), "https://soutubot.moe/api/search")


class TestParser:
    def test_merges_same_gallery(self):
        resp = _resp(**SAMPLE)
        assert len(resp.raw) == 2
        first = resp.raw[0]
        assert first.gallery_id == "682359"
        # 同一画廊命中两页：保留最高分并累计命中页数
        assert first.similarity == 87.5
        assert first.hit_pages == 2

    def test_fields(self):
        item = _resp(**SAMPLE).raw[0]
        assert item.title.startswith("[Fly Dish (Jakko)]")
        assert item.author == "Jakko"
        assert item.source == "nhentai"
        assert item.url == "https://nhentai.net/g/682359/12/"
        assert item.thumbnail == "https://img.example/682359/012.webp"
        assert item.page_count == 41
        assert item.language == "ja"
        assert item.category == "doujinshi"
        assert item.tags == ["sole female", "sole male", "fly dish"]

    def test_sorted_by_score(self):
        scores = [item.similarity for item in _resp(**SAMPLE).raw]
        assert scores == sorted(scores, reverse=True)

    def test_second_item_fields(self):
        item = _resp(**SAMPLE).raw[1]
        assert item.title == "Second Work"
        assert item.author == "A / B"
        assert item.page_count == 20

    def test_empty_results(self):
        resp = _resp(status="ok", results=[])
        assert resp.raw == []
        assert "未在 nhentai 图源中找到" in resp.show_result()

    def test_rate_limited_detail(self):
        resp = _resp(detail="当前搜索任务较多，请稍后重试", results=[])
        assert resp.raw == []
        assert "请稍后重试" in resp.show_result()

    def test_invalid_json(self):
        resp = SoutubotResponse("<html>502</html>", "https://soutubot.moe/api/search")
        assert resp.raw == []
        assert "不是" in resp.show_result()

    def test_html_challenge_logs_details(self, caplog):
        body = (
            "<html><head><title>Attention Required! | Cloudflare</title></head>"
            "<body>Sorry, you have been blocked</body></html>"
        )
        resp = SoutubotResponse(
            body,
            "https://soutubot.moe/api/search",
            status_code=403,
            content_type="text/html; charset=UTF-8",
        )
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            text = resp.show_result()

        # 聊天里给出可读原因（状态码/content-type/页面标题）
        assert "HTTP 403" in text
        assert "text/html" in text
        assert "Cloudflare" in text
        # 控制台 WARNING 里带完整诊断信息
        assert "AI or Not" not in caplog.text
        assert "HTTP 403" in caplog.text
        assert "text/html" in caplog.text
        assert "Attention Required" in caplog.text
        assert "blocked" in caplog.text

    def test_empty_body_reports_rate_limit(self, caplog):
        resp = SoutubotResponse("", "https://soutubot.moe/api/search", status_code=429)
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            text = resp.show_result()
        assert "空响应" in text
        assert "HTTP 429" in caplog.text

    def test_non_object_json_logs_reason(self, caplog):
        resp = SoutubotResponse('["oops"]', "https://soutubot.moe/api/search")
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            text = resp.show_result()
        assert "JSON 对象" in text
        assert "不是预期的 JSON 对象" in caplog.text

    def test_partial_flag(self):
        data = dict(SAMPLE)
        data["partial"] = True
        resp = _resp(**data)
        assert resp.partial is True
        assert "可能不完整" in resp.show_result()

    def test_show_result_contains_links(self):
        text = _resp(**SAMPLE).show_result()
        assert "标题: [Fly Dish (Jakko)]" in text
        assert "相似度: 87.5%" in text
        assert "https://nhentai.net/g/682359/12/" in text

    def test_item_entries(self):
        entries = _resp(**SAMPLE).item_entries()
        assert len(entries) == 2
        assert entries[0]["thumbnail"] == "https://img.example/682359/012.webp"
        assert "结果 #1（相似度 87.5%）" in entries[0]["text"]
        assert "标签: sole female" in entries[0]["text"]


class _Resp:
    def __init__(
        self,
        body,
        code,
        url="https://soutubot.moe/api/search",
        content_type="application/json",
    ):
        self.text = body
        self.status_code = code
        self.url = url
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, owner):
        self.owner = owner

    async def post(self, url, **kwargs):
        return self.owner._post(url, kwargs)


_IMG = b"\xff\xd8\xff" + b"x" * 16


class _FakeNetwork:
    def __init__(self, resp_body="{}", status_code=200):
        self.resp_body = resp_body
        self.status_code = status_code
        self.posts = []
        self.downloads = []
        self.client = _FakeClient(self)
        self.queue = []

    def _post(self, url, kwargs):
        self.posts.append((url, kwargs))
        body = self.resp_body
        code = self.status_code
        if self.queue:
            body, code = self.queue.pop(0)
        content_type = (
            "text/html" if str(body).lstrip().startswith("<") else "application/json"
        )
        return _Resp(body, code, url, content_type)

    async def aclose(self):
        return None


def _make_req(body=None, status_code=200, **kwargs):
    """构造带假 Network 的请求对象（下载路径直接返回假图片字节）"""
    fake = _FakeNetwork(
        resp_body=body or json.dumps({"status": "ok", "results": []}),
        status_code=status_code,
    )
    req = Soutubot(network=fake, **kwargs)

    async def fake_download(url):
        fake.downloads.append(url)
        return _IMG

    req.download = fake_download  # type: ignore[method-assign]
    return req, fake


class TestCloudflare:
    CF_PAGE = (
        "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        "<body><div id='cf-chl'>checking your browser</div></body></html>"
    )

    def test_cf_page_detected(self):
        resp = _Resp(self.CF_PAGE, 403)
        assert (
            is_cloudflare_challenge(resp.status_code, resp.headers, resp.text) is True
        )

    def test_cf_header_detected(self):
        assert is_cloudflare_challenge(403, {"cf-mitigated": "challenge"}, "") is True

    def test_normal_429_not_cf(self):
        body = json.dumps({"detail": "当前搜索任务较多，请稍后重试"})
        assert is_cloudflare_challenge(429, {}, body) is False

    def test_cookies_are_sent(self):
        req, fake = _make_req(cookies="cf_clearance=abc; __cf_bm=xyz")
        asyncio.run(req.search(file=b"\xff\xd8\xff"))
        _url, kwargs = fake.posts[0]
        assert kwargs["headers"]["Cookie"] == "cf_clearance=abc; __cf_bm=xyz"

    def test_custom_user_agent_applied(self):
        req, fake = _make_req(user_agent="UA-TEST/1.0")
        asyncio.run(req.search(file=b"\xff\xd8\xff"))
        assert fake.posts[0][1]["headers"]["User-Agent"] == "UA-TEST/1.0"

    def test_challenge_without_solver_shows_hint(self, caplog):
        req, _fake = _make_req(body=self.CF_PAGE, status_code=403)
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            resp = asyncio.run(req.search(file=b"\xff\xd8\xff"))
        text = resp.show_result()
        assert "Cloudflare" in text
        assert "flaresolverr" in text
        assert "cf_clearance" in text
        assert "Cloudflare" in caplog.text

    def test_challenge_retries_with_solver(self, caplog):
        class _FakeSolver:
            enabled = True

            def __init__(self):
                self.calls = 0

            async def solve(self, url):
                self.calls += 1
                return CfSolution(
                    cookies={"cf_clearance": "solved"}, user_agent="UA-SOLVED"
                )

        solver = _FakeSolver()
        req, fake = _make_req(body=self.CF_PAGE, status_code=403, cf_solver=solver)
        # 第一次 403 挑战页，过盾后第二次返回正常 JSON
        fake.queue = [(self.CF_PAGE, 403)]
        fake.body_after_solve = json.dumps({"status": "ok", "results": []})

        original_post = fake._post

        def post_after_solve(url, kwargs):
            if solver.calls:
                fake.resp_body = fake.body_after_solve
                fake.status_code = 200
            return original_post(url, kwargs)

        fake._post = post_after_solve  # type: ignore[method-assign]
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            resp = asyncio.run(req.search(file=b"\xff\xd8\xff"))
        assert solver.calls == 1
        assert len(fake.posts) == 2
        assert fake.posts[1][1]["headers"]["Cookie"] == "cf_clearance=solved"
        assert fake.posts[1][1]["headers"]["User-Agent"] == "UA-SOLVED"
        assert resp.raw == []

    def test_disabled_solver_skips(self):
        class _Disabled:
            enabled = False

            async def solve(self, url):  # pragma: no cover - 不应被调用
                raise AssertionError("disabled solver must not be called")

        req, _fake = _make_req(cf_solver=_Disabled())
        assert asyncio.run(req._apply_cf_clearance()) is False


class TestRequest:
    def test_posts_multipart_with_factor(self):
        req, fake = _make_req(factor=1.4, max_results=3)
        asyncio.run(req.search(file=b"\xff\xd8\xffdata"))

        url, kwargs = fake.posts[0]
        assert url == "https://soutubot.moe/api/search"
        assert kwargs["data"]["factor"] == "1.4"
        assert kwargs["data"]["metadata_mode"] == "display"
        assert kwargs["files"]["file"][1].startswith(b"\xff\xd8\xff")
        assert kwargs["headers"]["Origin"] == "https://soutubot.moe"

    def test_factor_normalization(self):
        assert Soutubot(network=_FakeNetwork(), factor="1.4").factor == "1.4"
        assert Soutubot(network=_FakeNetwork(), factor=1.3).factor == "1.2"
        assert Soutubot(network=_FakeNetwork(), factor=None).factor == "1.2"

    def test_url_is_downloaded_first(self):
        req, fake = _make_req()
        asyncio.run(req.search(url="https://example.com/a.jpg"))
        assert fake.downloads == ["https://example.com/a.jpg"]
        assert fake.posts[0][1]["files"]["file"][1].startswith(b"\xff\xd8\xff")

    def test_requires_file_or_url(self):
        req = Soutubot(network=_FakeNetwork())
        try:
            asyncio.run(req.search())
        except ValueError as exc:
            assert "url" in str(exc) and "file" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")

    def test_cf_solver_injected(self):
        solver = object()
        req = Soutubot(network=_FakeNetwork(), cf_solver=solver)
        assert req.cf_solver is solver

    def test_model_forwards_cf_solver(self):
        from ReverseSearcher.model import BaseSearchModel

        solver = object()
        model = BaseSearchModel(
            proxies=None, timeout=20, default_params={}, cf_solver=solver
        )
        assert model.cf_solver is solver

    def test_error_status_surfaces_detail(self):
        body = json.dumps({"detail": "当前搜索任务较多，请稍后重试"})
        req, _fake = _make_req(body=body, status_code=429)
        resp = asyncio.run(req.search(file=b"\xff\xd8\xff"))
        assert resp.raw == []
        assert "请稍后重试" in (resp.error or "")

    def test_content_type_forwarded(self):
        body = json.dumps({"status": "ok", "results": []})
        fake = _FakeNetwork(resp_body=body, status_code=200)
        req = Soutubot(network=fake)

        async def fake_download(url):
            return _IMG

        req.download = fake_download  # type: ignore[method-assign]
        resp = asyncio.run(req.search(file=b"\xff\xd8\xff"))
        assert resp.content_type == "application/json"

    def test_request_logs_response_summary(self, caplog):
        body = "<html><title>blocked</title></html>"
        req, _fake = _make_req(body=body, status_code=403)
        with caplog.at_level(logging.INFO, logger="astrbot"):
            resp = asyncio.run(req.search(file=b"\xff\xd8\xff"))
        assert "HTTP 403" in caplog.text
        assert "text/html" in caplog.text
        assert "length" not in caplog.text  # 中文日志
        with caplog.at_level(logging.WARNING, logger="astrbot"):
            resp.show_result()
        assert "blocked" in caplog.text


class TestEngineIntegration:
    def test_registry_and_params(self):
        from ReverseSearcher.engine_registry import ENGINE_REGISTRY, IntentRouter
        from ReverseSearcher.model import BaseSearchModel

        assert ENGINE_REGISTRY["soutubot"].label == "Soutubot"
        assert ENGINE_REGISTRY["soutubot"].req_class is Soutubot
        assert IntentRouter.match("帮我找这个nhentai本子的图源") == "soutubot"

        model = BaseSearchModel(proxies=None, timeout=20, default_params={})
        params = {"factor": "1.4", "max_results": 3}
        engine_params = model._prepare_engine_params("soutubot", params)
        assert engine_params == {
            "factor": "1.4",
            "metadata_mode": "display",
            "max_results": 3,
            "cookies": None,
            "user_agent": "",
        }
        assert params == {}
