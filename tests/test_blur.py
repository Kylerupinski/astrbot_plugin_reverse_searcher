"""E-Hentai / Soutubot 结果图模糊（过审）测试"""

import asyncio
import io
import random
from typing import ClassVar

from PIL import Image, ImageStat

from ReverseSearcher.model import BaseSearchModel

_ENGINES = ("ehentai", "soutubot")


def _noise_image(size=(240, 240)) -> Image.Image:
    rng = random.Random(1234)
    img = Image.new("RGB", size)
    img.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(size[0] * size[1])
        ]
    )
    return img


def _stddev(img: Image.Image) -> float:
    stat = ImageStat.Stat(img.convert("L"))
    return stat.stddev[0]


def _model(**kwargs) -> BaseSearchModel:
    return BaseSearchModel(proxies=None, timeout=20, default_params={}, **kwargs)


class TestBlurRadii:
    def test_disabled_by_default(self):
        model = _model()
        assert model.blur_radii == {}
        for engine in _ENGINES:
            assert model._blur_radius(engine) is None

    def test_enabled_with_auto_radius(self):
        model = _model(blur_radii={"ehentai": 0, "soutubot": 0})
        assert model._blur_radius("ehentai") == 0
        assert model._blur_radius("soutubot") == 0
        assert model._blur_radius("google") is None

    def test_explicit_radius_and_invalid(self):
        model = _model(blur_radii={"ehentai": 18, "soutubot": "bad", "google": -5})
        assert model._blur_radius("ehentai") == 18
        assert model._blur_radius("soutubot") == 0
        assert model._blur_radius("google") == 0

    def test_collect_from_config(self):
        from ReverseSearcher.model import collect_blur_radii

        default_params = {
            "ehentai": {"blur_image": True, "blur_radius": 24},
            "soutubot": {"blur_image": True},
            "google": {"blur_image": True},
        }
        assert collect_blur_radii(default_params) == {"ehentai": 24, "soutubot": 0}
        assert collect_blur_radii({}) == {}
        assert collect_blur_radii(
            {"ehentai": {"blur_image": True, "blur_radius": "x"}}
        ) == {"ehentai": 0}
        assert collect_blur_radii({"ehentai": {"blur_image": False}}) == {}


class TestBlurImage:
    def test_auto_radius_reduces_detail(self):
        model = _model()
        img = _noise_image()
        blurred = model._apply_blur_image(img, 0)
        assert blurred.size == img.size
        assert _stddev(blurred) < _stddev(img)

    def test_large_image_auto_radius_is_clamped(self):
        model = _model()
        img = _noise_image((1600, 1600))
        blurred = model._apply_blur_image(img, 0)
        # 半径上限 40：模糊后细节大幅减少但仍有少量差异
        assert _stddev(blurred) < _stddev(img) * 0.2

    def test_explicit_radius(self):
        model = _model()
        img = _noise_image()
        light = model._apply_blur_image(img, 6)
        heavy = model._apply_blur_image(img, 30)
        assert _stddev(heavy) < _stddev(light)

    def test_palette_image_converted(self):
        model = _model()
        img = Image.new("P", (64, 64))
        out = model._apply_blur_image(img, 12)
        assert out.mode == "RGB"


class TestCardPath:
    def test_blur_items_inplace(self):
        model = _model(blur_radii={"ehentai": 0})
        img = _noise_image()
        items = [{"thumbnail_image": img}, {"thumbnail_image": None}]
        asyncio.run(model._blur_items_inplace("ehentai", items))
        assert _stddev(items[0]["thumbnail_image"]) < _stddev(img)
        assert items[1]["thumbnail_image"] is None

    def test_no_blur_for_other_engine(self):
        model = _model(blur_radii={"ehentai": 0})
        img = _noise_image()
        items = [{"thumbnail_image": img}]
        asyncio.run(model._blur_items_inplace("saucenao", items))
        assert items[0]["thumbnail_image"] is img

    def test_disabled_keeps_image(self):
        model = _model()
        img = _noise_image()
        items = [{"thumbnail_image": img}]
        asyncio.run(model._blur_items_inplace("soutubot", items))
        assert items[0]["thumbnail_image"] is img

    def test_search_and_draw_blurs_result_thumbs(self, monkeypatch):
        model = _model(blur_radii={"ehentai": 0})
        img = _noise_image()

        class _Item:
            title = "x"
            url = "http://x"
            thumbnail = "http://x/1.jpg"
            similarity = 90.0
            source = "nhentai"
            author = ""

        class FakeResponse:
            raw: ClassVar[list] = [_Item()]
            error: ClassVar[str] = ""

        async def fake_search(api, **kwargs):
            return FakeResponse()

        async def fake_precheck(**kwargs):
            return []

        async def fake_load(file, url, network_kwargs):
            return None

        async def fake_download(client, url):
            return img.copy()

        captured = {}

        async def fake_draw(api, items, source_image, ai_badges=None):
            captured["items"] = items
            return Image.new("RGB", (10, 10))

        monkeypatch.setattr(model, "_search_engine", fake_search)
        monkeypatch.setattr(model, "_precheck_ai", fake_precheck)
        monkeypatch.setattr(model, "_load_source_image", fake_load)
        monkeypatch.setattr(model, "_download_thumbnail", fake_download)
        monkeypatch.setattr(model, "draw_results", fake_draw)

        asyncio.run(model.search_and_draw(api="ehentai"))
        thumb = captured["items"][0]["thumbnail_image"]
        assert _stddev(thumb) < _stddev(img)

    def test_search_and_draw_keeps_query_image(self, monkeypatch):
        """查询图（source_image）不应被模糊，只有结果图被模糊"""
        model = _model(blur_radii={"soutubot": 0})
        img = _noise_image()
        source = _noise_image()

        class _Item:
            title = "x"
            url = "http://x"
            thumbnail = "http://x/1.jpg"
            similarity = 90.0
            source = "nhentai"
            author = ""

        class FakeResponse:
            raw: ClassVar[list] = [_Item()]
            error: ClassVar[str] = ""

        async def fake_search(api, **kwargs):
            return FakeResponse()

        async def fake_precheck(**kwargs):
            return []

        async def fake_load(file, url, network_kwargs):
            return source

        async def fake_download(client, url):
            return img.copy()

        captured = {}

        async def fake_draw(api, items, source_image, ai_badges=None):
            captured["source"] = source_image
            captured["items"] = items
            return Image.new("RGB", (10, 10))

        monkeypatch.setattr(model, "_search_engine", fake_search)
        monkeypatch.setattr(model, "_precheck_ai", fake_precheck)
        monkeypatch.setattr(model, "_load_source_image", fake_load)
        monkeypatch.setattr(model, "_download_thumbnail", fake_download)
        monkeypatch.setattr(model, "draw_results", fake_draw)

        asyncio.run(model.search_and_draw(api="soutubot"))
        assert captured["source"] is source
        assert _stddev(captured["items"][0]["thumbnail_image"]) < _stddev(img)


class TestTextPath:
    def _run_entry(self, model, api):
        img = _noise_image()
        calls = []

        async def fake_download(client, url):
            calls.append(url)
            return img.copy()

        model._download_thumbnail = fake_download  # type: ignore[method-assign]
        data = asyncio.run(
            model._entry_image_bytes(
                None, {"thumbnail": "http://x/1.jpg"}, None, api=api
            )
        )
        assert data
        return Image.open(io.BytesIO(data)), img

    def test_blurred_for_ehentai(self):
        model = _model(blur_radii={"ehentai": 20})
        out, original = self._run_entry(model, "ehentai")
        assert _stddev(out) < _stddev(original) * 0.5

    def test_blurred_for_soutubot(self):
        model = _model(blur_radii={"soutubot": 20})
        out, original = self._run_entry(model, "soutubot")
        assert _stddev(out) < _stddev(original) * 0.5

    def test_unblurred_for_other_engine(self):
        model = _model(blur_radii={"ehentai": 20})
        out, original = self._run_entry(model, "google")
        assert _stddev(out) > _stddev(original) * 0.5
