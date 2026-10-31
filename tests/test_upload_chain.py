"""临时图床上传链测试

Google Lens / Yandex 的本地图搜要求图床返回**可直接下载的图片直链**：
临时图床可能返回 HTML 展示页（旧版 tmpfiles 即如此），第三方抓取到网页后
搜索必然为空。因此上传后必须回读校验并自动切换下一个图床。
"""

import asyncio

import pytest

from ReverseSearcher.utils.api_request.base_req import BaseSearchReq

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class _FakeResponse:
    def __init__(self, *, text="", status_code=200, content=b"", ctype="text/html"):
        self.text = text
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """按 host 返回不同结果；get 用于回读校验"""

    def __init__(self, uploads: dict, fetches: dict):
        self.uploads = uploads
        self.fetches = fetches
        self.posted: list[str] = []
        self.fetched: list[str] = []

    async def post(self, url, data=None, files=None):
        self.posted.append(url)
        return self.uploads[url]

    async def get(self, url, headers=None, timeout=None):
        self.fetched.append(url)
        return self.fetches.get(url, _FakeResponse(status_code=404))


class _Probe(BaseSearchReq):
    async def search(self, url=None, file=None, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _probe(client) -> _Probe:
    probe = _Probe.__new__(_Probe)
    probe._client = client
    return probe


HOST_HTML = "https://host-html/upload"
HOST_GOOD = "https://host-good/upload"


def test_skips_host_returning_html_page():
    html_url = "https://host-html/abc/image.jpg"
    good_url = "https://host-good/abc.jpg"
    client = _FakeClient(
        uploads={
            HOST_HTML: _FakeResponse(
                text='{"data": {"url": "https://host-html/abc/image.jpg"}}'
            ),
            HOST_GOOD: _FakeResponse(text=f'{{"files": [{{"url": "{good_url}"}}]}}'),
        },
        fetches={
            # HTML 展示页：即使 Content-Type 声称是图片也要拒绝
            html_url: _FakeResponse(
                status_code=200, content=b"<!DOCTYPE html>", ctype="image/jpeg"
            ),
            good_url: _FakeResponse(status_code=200, content=JPEG, ctype="image/jpeg"),
        },
    )
    probe = _probe(client)
    probe._UPLOAD_HOSTS = (
        ("host-html", HOST_HTML, None, "file", ["data", "url"]),
        ("host-good", HOST_GOOD, None, "files[]", ["files", 0, "url"]),
    )

    url = asyncio.run(probe._upload_image(JPEG))

    assert url == good_url
    assert client.posted == [HOST_HTML, HOST_GOOD]
    assert html_url in client.fetched


def test_all_hosts_fail_raises_with_reasons():
    client = _FakeClient(
        uploads={HOST_HTML: _FakeResponse(text="<html>down</html>")},
        fetches={},
    )
    probe = _probe(client)
    probe._UPLOAD_HOSTS = (("host-html", HOST_HTML, None, "file", ["data", "url"]),)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(probe._upload_image(JPEG))
    assert "host-html" in str(excinfo.value)


def test_plain_text_url_host_supported():
    good_url = "https://host-good/abc.jpg"
    client = _FakeClient(
        uploads={HOST_GOOD: _FakeResponse(text=good_url + "\n")},
        fetches={
            good_url: _FakeResponse(status_code=200, content=JPEG, ctype="image/jpeg")
        },
    )
    probe = _probe(client)
    probe._UPLOAD_HOSTS = (("host-good", HOST_GOOD, None, "file", None),)

    assert asyncio.run(probe._upload_image(JPEG)) == good_url


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (JPEG, True),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, True),
        (b"GIF89a" + b"\x00" * 16, True),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", True),
        (b"<!DOCTYPE html><html>", False),
        (b"", False),
    ],
)
def test_looks_like_image(data, expected):
    assert BaseSearchReq._looks_like_image(data) is expected


def test_normalize_upload_url_tmpfiles_dl():
    assert (
        BaseSearchReq._normalize_upload_url("https://tmpfiles.org/abc/image.jpg")
        == "https://tmpfiles.org/dl/abc/image.jpg"
    )
    assert (
        BaseSearchReq._normalize_upload_url("https://x0.at/abc.jpg")
        == "https://x0.at/abc.jpg"
    )
