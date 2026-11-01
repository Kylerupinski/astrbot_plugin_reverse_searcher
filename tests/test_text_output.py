"""文本模式分条输出（每条结果 = 文本 + 配图）与检测框裁剪测试"""

import asyncio
import io

from PIL import Image, ImageDraw

from ReverseSearcher.model import BaseSearchModel


class _FakeItem:
    def __init__(self, **attrs):
        self.title = attrs.get("title", "")
        self.url = attrs.get("url", "")
        self.similarity = attrs.get("similarity", 0)
        self.source = attrs.get("source", "")
        self.author = attrs.get("author", "")
        self.thumbnail = attrs.get("thumbnail", "")
        self.index_name = attrs.get("index_name", "")


class _FakeCharacter:
    def __init__(self, name, work):
        self.name = name
        self.work = work


class _FakeAnimeItem:
    def __init__(self, characters, box):
        self.characters = characters
        self.box = box


class _FakeResponse:
    """模拟引擎响应：可带 item_entries（新式）或只有 raw（老式）"""

    def __init__(self, raw=None, entries=None, error="", ai=None):
        self.raw = raw or []
        self._entries = entries
        self.error = error
        self.ai = ai

    def item_entries(self):
        if self._entries is None:
            raise AttributeError("no item_entries")
        return self._entries

    def show_result(self):
        return None


def _model(result_image_size: str = "standard") -> BaseSearchModel:
    return BaseSearchModel(
        proxies=None,
        timeout=30,
        default_params={},
        result_image_size=result_image_size,
    )


def _source_image(width=200, height=200) -> Image.Image:
    img = Image.new("RGB", (width, height), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.rectangle((50, 50, 150, 150), fill=(220, 40, 40))
    return img


def _png_bytes(width=200, height=200) -> bytes:
    buf = io.BytesIO()
    _source_image(width, height).save(buf, format="PNG")
    return buf.getvalue()


def _patch(model, monkeypatch, response) -> None:
    """把 _search_engine 替换为返回固定响应的假实现"""

    async def fake_engine(api, file=None, url=None, **kwargs):
        return response

    monkeypatch.setattr(model, "_search_engine", fake_engine)


class TestSearchTextMessages:
    def test_header_plus_one_message_per_entry(self, monkeypatch):
        model = _model()
        entries = [
            {"text": "结果 #1\n标题: A", "thumbnail": "", "crop_box": None},
            {"text": "结果 #2\n标题: B", "thumbnail": "", "crop_box": None},
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))

        messages = asyncio.run(model.search_text_messages(api="yandex", file=b"x"))

        assert len(messages) == 3
        assert messages[0]["text"].startswith("🔍「Yandex」搜索结果")
        assert "共 2 条" in messages[0]["text"]
        assert messages[0]["image"] is None
        assert messages[1]["text"] == "结果 #1\n标题: A"
        assert messages[2]["text"] == "结果 #2\n标题: B"

    def test_entries_capped_by_max_items(self, monkeypatch):
        model = _model()
        entries = [
            {"text": f"结果 #{i}", "thumbnail": "", "crop_box": None} for i in range(8)
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        messages = asyncio.run(model.search_text_messages(api="yandex", file=b"x"))
        assert len(messages) == model.MAX_TEXT_RESULTS + 1

    def test_empty_entries_reports_reason(self, monkeypatch):
        model = _model()
        response = _FakeResponse(entries=[], error="Yandex 要求人机验证")
        _patch(model, monkeypatch, response)
        messages = asyncio.run(model.search_text_messages(api="yandex", file=b"x"))
        assert len(messages) == 1
        assert "Yandex 要求人机验证" in messages[0]["text"]

    def test_no_entries_no_error(self, monkeypatch):
        model = _model()
        _patch(model, monkeypatch, _FakeResponse(entries=[]))
        messages = asyncio.run(model.search_text_messages(api="yandex", file=b"x"))
        assert len(messages) == 1
        assert "未找到相关结果" in messages[0]["text"]

    def test_exception_message_is_sanitized(self, monkeypatch):
        model = _model()

        async def fake_engine(api, file=None, url=None, **kwargs):
            raise RuntimeError(
                "connect failed https://serpapi.com/?api_key=SECRET123&x=1"
            )

        monkeypatch.setattr(model, "_search_engine", fake_engine)
        messages = asyncio.run(model.search_text_messages(api="google", file=b"x"))
        assert len(messages) == 1
        assert "搜索失败" in messages[0]["text"]
        assert "SECRET123" not in messages[0]["text"]
        assert "***" in messages[0]["text"]

    def test_ai_badge_in_header(self, monkeypatch):
        model = _model()
        entries = [{"text": "结果 #1", "thumbnail": "", "crop_box": None}]
        _patch(model, monkeypatch, _FakeResponse(entries=entries, ai=True))
        messages = asyncio.run(model.search_text_messages(api="animetrace", file=b"x"))
        assert "AnimeTrace：判定为 AI 生成" in messages[0]["text"]

    def test_falls_back_to_generic_entries(self, monkeypatch):
        model = _model()
        item = _FakeItem(
            title="作品标题",
            url="https://example.com/art",
            source="pixiv",
            author="画师",
            similarity=91.2,
        )
        # 没有 item_entries：退回通用字段排版
        _patch(model, monkeypatch, _FakeResponse(raw=[item]))
        messages = asyncio.run(model.search_text_messages(api="saucenao", file=b"x"))
        assert len(messages) == 2
        body = messages[1]["text"]
        assert body.startswith("结果 #1")
        assert "来源: pixiv" in body
        assert "标题: 作品标题" in body
        assert "作者: 画师" in body
        assert "相似度: 91.2%" in body
        assert "https://example.com/art" in body


class TestMessageImages:
    def test_thumbnail_downloaded_into_message(self, monkeypatch):
        model = _model()
        entries = [
            {
                "text": "结果 #1",
                "thumbnail": "https://example.com/thumb.jpg",
                "crop_box": None,
            }
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        called = {}

        async def fake_download(client, url):
            called["url"] = url
            return _source_image()

        monkeypatch.setattr(model, "_download_thumbnail", fake_download)

        messages = asyncio.run(model.search_text_messages(api="google", file=b"x"))
        assert called["url"] == "https://example.com/thumb.jpg"
        assert messages[1]["image"] is not None
        assert messages[1]["image"].startswith(b"\xff\xd8\xff")

    def test_thumbnail_failure_keeps_text_only(self, monkeypatch):
        model = _model()
        entries = [
            {
                "text": "结果 #1",
                "thumbnail": "https://example.com/x.jpg",
                "crop_box": None,
            }
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))

        async def fake_download(client, url):
            return None

        monkeypatch.setattr(model, "_download_thumbnail", fake_download)
        messages = asyncio.run(model.search_text_messages(api="google", file=b"x"))
        assert messages[1]["image"] is None

    def test_crop_box_uses_source_image(self, monkeypatch):
        model = _model()
        entries = [
            {"text": "结果 #1", "thumbnail": "", "crop_box": [0.25, 0.25, 0.75, 0.75]}
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        messages = asyncio.run(
            model.search_text_messages(api="animetrace", file=_png_bytes())
        )
        image = messages[1]["image"]
        assert image is not None and image.startswith(b"\xff\xd8\xff")
        # 裁剪后是 100x100 的区域（通过解码确认尺寸）
        decoded = Image.open(io.BytesIO(image))
        assert decoded.size == (100, 100)


class TestResultImageSize:
    def test_default_is_standard(self):
        assert _model().result_image_size == "standard"

    def test_unknown_value_falls_back(self):
        assert _model("ultra").result_image_size == "standard"
        assert _model("").result_image_size == "standard"

    def test_profiles_cover_three_tiers(self):
        assert set(BaseSearchModel.IMAGE_SIZE_PROFILES) == {
            "low",
            "standard",
            "original",
        }

    def test_encode_downscales_to_max_side(self):
        data = BaseSearchModel._encode_image_bytes(_source_image(800, 600), 85, 256)
        decoded = Image.open(io.BytesIO(data))
        assert decoded.size == (256, 192)

    def test_encode_keeps_small_images(self):
        data = BaseSearchModel._encode_image_bytes(_source_image(200, 200), 85, 640)
        assert Image.open(io.BytesIO(data)).size == (200, 200)

    def _messages_with(self, monkeypatch, size, image):
        model = _model(size)
        entries = [
            {
                "text": "结果 #1",
                "thumbnail": "https://example.com/thumb.jpg",
                "full_image": "https://example.com/full.jpg",
                "crop_box": None,
            }
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        called = []

        async def fake_download(client, url):
            called.append(url)
            return image

        monkeypatch.setattr(model, "_download_thumbnail", fake_download)
        messages = asyncio.run(model.search_text_messages(api="google", file=b"x"))
        return called, messages

    def test_standard_prefers_full_image(self, monkeypatch):
        called, messages = self._messages_with(monkeypatch, "standard", _source_image())
        assert called[0] == "https://example.com/full.jpg"
        assert messages[1]["image"] is not None

    def test_standard_downscales_oversized_full_image(self, monkeypatch):
        _called, messages = self._messages_with(
            monkeypatch, "standard", _source_image(1200, 900)
        )
        decoded = Image.open(io.BytesIO(messages[1]["image"]))
        assert decoded.size == (640, 480)

    def test_low_uses_thumbnail(self, monkeypatch):
        called, messages = self._messages_with(
            monkeypatch, "low", _source_image(1200, 900)
        )
        assert called[0] == "https://example.com/thumb.jpg"
        decoded = Image.open(io.BytesIO(messages[1]["image"]))
        assert decoded.size == (256, 192)

    def test_original_prefers_full_image_without_scaling(self, monkeypatch):
        called, messages = self._messages_with(
            monkeypatch, "original", _source_image(1200, 900)
        )
        assert called[0] == "https://example.com/full.jpg"
        decoded = Image.open(io.BytesIO(messages[1]["image"]))
        assert decoded.size == (1200, 900)

    def test_original_falls_back_to_thumbnail(self, monkeypatch):
        model = _model("original")
        entries = [
            {
                "text": "结果 #1",
                "thumbnail": "https://example.com/thumb.jpg",
                "full_image": "https://example.com/full.jpg",
                "crop_box": None,
            }
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        called = []

        async def fake_download(client, url):
            called.append(url)
            # 原图下载失败 → 回退缩略图
            return None if url.endswith("full.jpg") else _source_image()

        monkeypatch.setattr(model, "_download_thumbnail", fake_download)
        messages = asyncio.run(model.search_text_messages(api="google", file=b"x"))
        assert called == [
            "https://example.com/full.jpg",
            "https://example.com/thumb.jpg",
        ]
        assert messages[1]["image"] is not None

    def test_original_crop_keeps_source_resolution(self, monkeypatch):
        model = _model("original")
        entries = [
            {"text": "结果 #1", "thumbnail": "", "crop_box": [0.0, 0.0, 1.0, 1.0]}
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        messages = asyncio.run(
            model.search_text_messages(api="animetrace", file=_png_bytes(800, 800))
        )
        decoded = Image.open(io.BytesIO(messages[1]["image"]))
        assert decoded.size == (800, 800)

    def test_low_crop_is_scaled_down(self, monkeypatch):
        model = _model("low")
        entries = [
            {"text": "结果 #1", "thumbnail": "", "crop_box": [0.0, 0.0, 1.0, 1.0]}
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        messages = asyncio.run(
            model.search_text_messages(api="animetrace", file=_png_bytes(800, 800))
        )
        decoded = Image.open(io.BytesIO(messages[1]["image"]))
        assert decoded.size == (256, 256)


class TestSearchAndTextCompat:
    def test_joins_messages(self, monkeypatch):
        model = _model()
        entries = [
            {"text": "结果 #1\n标题: A", "thumbnail": "", "crop_box": None},
            {"text": "结果 #2\n标题: B", "thumbnail": "", "crop_box": None},
        ]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        out = asyncio.run(model.search_and_text(api="yandex", file=b"x"))
        assert out.startswith("🔍「Yandex」搜索结果")
        assert "结果 #1" in out and "结果 #2" in out
        assert out.count("结果 #") == 2

    def test_truncates_long_text(self, monkeypatch):
        model = _model()
        entries = [{"text": "x" * 5000, "thumbnail": "", "crop_box": None}]
        _patch(model, monkeypatch, _FakeResponse(entries=entries))
        out = asyncio.run(model.search_and_text(api="yandex", file=b"x"))
        assert len(out) <= model.MAX_TEXT_LENGTH + 30
        assert "已截断" in out


class TestCropThumbnail:
    def test_normalized_box(self):
        crop = BaseSearchModel._crop_thumbnail(
            _source_image(), [0.25, 0.25, 0.75, 0.75]
        )
        assert crop is not None
        assert crop.size == (100, 100)

    def test_pixel_box(self):
        crop = BaseSearchModel._crop_thumbnail(_source_image(), [50, 50, 150, 150])
        assert crop is not None
        assert crop.size == (100, 100)

    def test_invalid_box_returns_none(self):
        assert (
            BaseSearchModel._crop_thumbnail(_source_image(), [5000, 5000, 6000, 6000])
            is None
        )
        assert BaseSearchModel._crop_thumbnail(_source_image(), []) is None
        assert BaseSearchModel._crop_thumbnail(None, [0, 0, 1, 1]) is None
        assert (
            BaseSearchModel._crop_thumbnail(_source_image(), ["a", "b", "c", "d"])
            is None
        )

    def test_box_larger_than_source_rejected(self):
        # 归一化坐标 + 源图尺寸不一致时不会被误当成像素坐标裁出垃圾图
        assert (
            BaseSearchModel._crop_thumbnail(_source_image(50, 50), [0, 0, 1000, 1000])
            is None
        )

    def test_items_get_cropped_thumbnail(self):
        model = _model()
        raw = [
            _FakeAnimeItem([_FakeCharacter("角色A", "作品A")], [0.25, 0.25, 0.75, 0.75])
        ]
        items = model._build_items_from_raw(raw, source_image=_source_image())
        assert len(items) == 1
        thumb = items[0]["thumbnail_image"]
        assert isinstance(thumb, Image.Image)
        assert thumb.size == (100, 100)

    def test_items_without_source_image_have_no_thumbnail(self):
        model = _model()
        raw = [_FakeAnimeItem([_FakeCharacter("角色A", "作品A")], [0.1, 0.1, 0.2, 0.2])]
        items = model._build_items_from_raw(raw)
        assert items[0]["thumbnail_image"] is None

    def test_cropped_thumbnail_is_rgb_jpeg_encodable(self):
        crop = BaseSearchModel._crop_thumbnail(_source_image(), [0.1, 0.1, 0.5, 0.5])
        buf = io.BytesIO()
        crop.save(buf, format="JPEG")
        assert buf.getvalue().startswith(b"\xff\xd8\xff")


class TestBuildItemsDedup:
    def test_author_equal_to_source_is_dropped(self):
        model = _model()
        item = _FakeItem(title="t", source="example.com", author="example.com")
        items = model._build_items_from_raw([item])
        assert items[0]["source"] == "example.com"
        assert items[0]["author"] == ""

    def test_distinct_author_is_kept(self):
        model = _model()
        item = _FakeItem(title="t", source="pixiv", author="画师")
        items = model._build_items_from_raw([item])
        assert items[0]["author"] == "画师"
