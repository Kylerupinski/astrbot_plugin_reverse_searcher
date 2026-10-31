"""E-Hentai 响应解析测试（现行 / 旧版列表模板 + 限流与封禁页）

现行 e-hentai 列表模板的标题节点是 div.glink，旧实现写成 .gllink，
导致所有字段解析为空（卡片里只剩空行、文本输出返回 None）。
"""

from ReverseSearcher.utils.response_parser.ehentai_parser import (
    EHentaiItem,
    EHentaiResponse,
)

# 现行模板：td.gl1c/gl2c/gl3c/gl4c + div.glink + div.gt
NEW_ROW = """
<tr>
  <td class="gl1c glcat"><div class="cn ct1">Misc</div></td>
  <td class="gl2c">
    <div class="glthumb" id="it100"><div>
      <img src="https://ehgt.org/w/02/753/10569-3ugikucg.webp" alt="(circle) Title [AI Generated]" title="(circle) Title [AI Generated]">
    </div></div>
    <div><div id="posted_100">2026-10-30 13:55</div></div>
  </td>
  <td class="gl3c glname">
    <a href="https://e-hentai.org/g/100/abcdef1234/">
      <div class="glink">(circle) Title [AI Generated]</div>
      <div>
        <div class="gt" title="parody:some series">some series</div>
        <div class="gt" title="character:some girl">some girl</div>
      </div>
    </a>
  </td>
  <td class="gl4c glhide"><div><a href="https://e-hentai.org/uploader/Someone">Someone</a></div><div>250 pages</div></td>
</tr>
"""

# 旧版模板：div.gllink（多一个 l）
OLD_ROW = """
<tr>
  <td>
    <div class="gllink"><a href="https://e-hentai.org/g/200/oldtoken/">旧版标题</a></div>
    <div class="cs">Doujinshi</div>
    <div id="posted_200">2020-01-01 00:00</div>
    <div class="gl4c"><div>42 pages</div></div>
  </td>
</tr>
"""


def _page(rows: str) -> str:
    return f"<html><body><table class='itg'>{rows}</table></body></html>"


class TestCurrentLayout:
    def test_title_url_and_fields(self):
        from pyquery import PyQuery

        item = EHentaiItem(PyQuery(NEW_ROW))
        assert item.title == "(circle) Title [AI Generated]"
        assert item.url == "https://e-hentai.org/g/100/abcdef1234/"
        assert item.type == "Misc"
        assert item.date == "2026-10-30 13:55"
        assert item.pages == "250"  # 不能取成上传者名字
        assert item.thumbnail.startswith("https://ehgt.org/")
        assert item.tags == ["parody:some series", "character:some girl"]

    def test_response_parses_rows(self):
        resp = EHentaiResponse(_page(NEW_ROW), "https://e-hentai.org/", status_code=200)
        assert resp.error == ""
        assert len(resp.raw) == 1
        text = resp.show_result()
        assert text and "现行" not in text
        assert "(circle) Title" in text
        assert "https://e-hentai.org/g/100/abcdef1234/" in text


class TestLegacyLayout:
    def test_gllink_still_supported(self):
        from pyquery import PyQuery

        item = EHentaiItem(PyQuery(OLD_ROW))
        assert item.title == "旧版标题"
        assert item.url == "https://e-hentai.org/g/200/oldtoken/"
        assert item.type == "Doujinshi"
        assert item.pages == "42"


class TestErrorPages:
    def test_rate_limited_text(self):
        resp = EHentaiResponse(
            "Please wait a bit longer between each file search.",
            "https://upld.e-hentai.org/image_lookup.php",
            status_code=200,
        )
        assert resp.raw == []
        assert "频率" in resp.error
        # 文本输出把原因带回给调用方，不再静默返回 None
        assert resp.show_result() == resp.error

    def test_forbidden_page(self):
        resp = EHentaiResponse(
            "<html><body><h1>403 Forbidden</h1> Request forbidden by administrative rules. </body></html>",
            "https://e-hentai.org/",
            status_code=403,
        )
        assert resp.raw == []
        assert "403" in resp.error

    def test_http_error_status(self):
        resp = EHentaiResponse(
            "<html>oops</html>", "https://e-hentai.org/", status_code=503
        )
        assert resp.raw == []
        assert "503" in resp.error

    def test_no_unfiltered_results_is_not_an_error(self):
        resp = EHentaiResponse(
            "<html><body>No unfiltered results in these categories</body></html>",
            "https://e-hentai.org/",
            status_code=200,
        )
        assert resp.raw == []
        assert resp.error == ""
        assert resp.show_result() is None
