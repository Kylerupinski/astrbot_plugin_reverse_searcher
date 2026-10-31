"""E-Hentai 上传跳转处理测试

E-Hentai 风控会拒绝「客户端自动跟随」的那一次跳转（实测固定 403），
必须手动 GET Location 才能拿到真实结果页。
"""

import asyncio

from ReverseSearcher.utils.api_request.ehentai_req import EHentai

NO_HITS_PAGE = (
    "<html><body><table class='itg'></table>"
    "<div>No unfiltered results in these categories</div></body></html>"
)


class _Resp:
    def __init__(self, text="", url="", status_code=200, headers=None):
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}


def _engine(send_response, get_response=None):
    eng = EHentai.__new__(EHentai)
    eng.is_ex = False
    eng.covers = False
    eng.similar = True
    eng.exp = False
    calls = {"send": [], "get": []}

    async def fake_send_request(method=None, endpoint="", url="", **kwargs):
        calls["send"].append({"method": method, "endpoint": endpoint, **kwargs})
        return send_response

    async def fake_get(url, headers=None, **kwargs):
        calls["get"].append({"url": url, "headers": headers})
        return get_response

    eng._send_request = fake_send_request
    eng.get = fake_get
    return eng, calls


def test_upload_redirect_is_followed_manually():
    send = _Resp(
        status_code=302,
        headers={"Location": "https://e-hentai.org/?f_shash=abc&fs_from=image.jpg"},
        url="https://upld.e-hentai.org/image_lookup.php",
    )
    follow = _Resp(
        text=NO_HITS_PAGE, url="https://e-hentai.org/?f_shash=abc", status_code=200
    )
    eng, calls = _engine(send, follow)

    resp = asyncio.run(eng.search(file=b"jpeg-bytes"))

    # 自动跟随必须被关闭（否则 E-Hentai 固定返回 403）
    assert calls["send"][0]["follow_redirects"] is False
    # 手动 GET 到结果页
    assert (
        calls["get"][0]["url"] == "https://e-hentai.org/?f_shash=abc&fs_from=image.jpg"
    )
    assert resp.url == "https://e-hentai.org/?f_shash=abc"
    assert resp.error == ""
    assert resp.raw == []


def test_no_redirect_no_extra_request():
    send = _Resp(
        text="Please wait a bit longer between each file search.",
        url="https://upld.e-hentai.org/image_lookup.php",
        status_code=200,
    )
    eng, calls = _engine(send, _Resp())
    resp = asyncio.run(eng.search(file=b"jpeg-bytes"))
    assert calls["get"] == []
    assert "频率" in resp.error


def test_absolute_location_used_as_is():
    send = _Resp(
        status_code=302,
        headers={"Location": "https://e-hentai.org/?f_shash=abs"},
        url="https://upld.e-hentai.org/image_lookup.php",
    )
    follow = _Resp(
        text=NO_HITS_PAGE, url="https://e-hentai.org/?f_shash=abs", status_code=200
    )
    eng, calls = _engine(send, follow)
    asyncio.run(eng.search(file=b"jpeg-bytes"))
    assert calls["get"][0]["url"] == "https://e-hentai.org/?f_shash=abs"
