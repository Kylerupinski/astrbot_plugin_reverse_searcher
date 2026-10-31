"""合并转发节点构建测试（对应 astrbot_plugin_outputpro 的 Nodes/Node 用法）"""

import asyncio

import ReverseSearcher.utils.forward as fw


class _FakeImage:
    class _Item:
        def __init__(self, data):
            self.data = data

    @classmethod
    def fromBytes(cls, data):
        return cls._Item(data)


class _FakePlain:
    def __init__(self, text):
        self.text = text


class _FakeNode:
    def __init__(self, uin, name, content):
        self.uin = uin
        self.name = name
        self.content = content


class _FakeNodes:
    def __init__(self, nodes):
        self.nodes = list(nodes)


class _Bot:
    def __init__(self, nickname="测试机器人", fail=False):
        self.nickname = nickname
        self.fail = fail

    async def get_login_info(self):
        if self.fail:
            raise RuntimeError("api unavailable")
        return {"nickname": self.nickname}


class _Event:
    def __init__(self, platform="aiocqhttp", self_id="10086", bot=None):
        self.platform = platform
        self.self_id = self_id
        self.bot = bot or _Bot()

    def get_platform_name(self):
        return self.platform

    def get_self_id(self):
        return self.self_id


def _patch_components(monkeypatch):
    monkeypatch.setattr(fw, "Image", _FakeImage)
    monkeypatch.setattr(fw, "Plain", _FakePlain)
    monkeypatch.setattr(fw, "Node", _FakeNode)
    monkeypatch.setattr(fw, "Nodes", _FakeNodes)


class TestSupport:
    def test_aiocqhttp_supported(self):
        assert fw.supports_merge_forward(_Event(platform="aiocqhttp")) is True

    def test_other_platform_unsupported(self):
        assert fw.supports_merge_forward(_Event(platform="telegram")) is False

    def test_missing_platform_api(self):
        class _Bare:
            pass

        assert fw.supports_merge_forward(_Bare()) is False


class TestBuildNodes:
    def test_one_node_per_message_with_images(self, monkeypatch):
        _patch_components(monkeypatch)
        messages = [
            {"text": "汇总", "image": None},
            {"text": "结果 #1", "image": b"\xff\xd8\xff1"},
            {"text": "结果 #2", "image": None},
        ]
        nodes = asyncio.run(fw.build_forward_nodes(_Event(), messages))

        assert isinstance(nodes, _FakeNodes)
        assert len(nodes.nodes) == 3
        assert all(isinstance(n, _FakeNode) for n in nodes.nodes)
        assert {n.uin for n in nodes.nodes} == {"10086"}
        assert {n.name for n in nodes.nodes} == {"测试机器人"}

        # 第一条只有文本
        assert len(nodes.nodes[0].content) == 1
        assert isinstance(nodes.nodes[0].content[0], _FakePlain)
        assert nodes.nodes[0].content[0].text == "汇总"

        # 第二条：图片 + 文本
        content = nodes.nodes[1].content
        assert len(content) == 2
        assert isinstance(content[0], _FakeImage._Item)
        assert content[0].data == b"\xff\xd8\xff1"
        assert content[1].text == "结果 #1"

    def test_image_build_failure_falls_back_to_text(self, monkeypatch):
        _patch_components(monkeypatch)

        class _BrokenImage:
            @classmethod
            def fromBytes(cls, data):
                raise ValueError("bad image")

        monkeypatch.setattr(fw, "Image", _BrokenImage)
        messages = [{"text": "结果 #1", "image": b"broken"}]
        nodes = asyncio.run(fw.build_forward_nodes(_Event(), messages))
        assert len(nodes.nodes) == 1
        assert len(nodes.nodes[0].content) == 1
        assert nodes.nodes[0].content[0].text == "结果 #1"

    def test_empty_messages_returns_none(self, monkeypatch):
        _patch_components(monkeypatch)
        assert asyncio.run(fw.build_forward_nodes(_Event(), [])) is None

    def test_build_error_returns_none(self, monkeypatch):
        _patch_components(monkeypatch)

        class _BrokenNodes:
            def __init__(self, nodes):
                raise RuntimeError("unsupported")

        monkeypatch.setattr(fw, "Nodes", _BrokenNodes)
        result = asyncio.run(
            fw.build_forward_nodes(_Event(), [{"text": "x", "image": None}])
        )
        assert result is None

    def test_custom_node_name(self, monkeypatch):
        _patch_components(monkeypatch)
        nodes = asyncio.run(
            fw.build_forward_nodes(
                _Event(), [{"text": "x", "image": None}], node_name="自定义"
            )
        )
        assert nodes.nodes[0].name == "自定义"


class TestResolveSender:
    def test_uin_fallback(self, monkeypatch):
        class _NoSelfId(_Event):
            def get_self_id(self):
                raise RuntimeError("nope")

        assert fw.resolve_node_uin(_NoSelfId()) == "0"

    def test_node_name_from_bot(self):
        assert asyncio.run(fw.resolve_node_name(_Event())) == "测试机器人"

    def test_node_name_fallback_on_error(self):
        event = _Event(bot=_Bot(fail=True))
        assert asyncio.run(fw.resolve_node_name(event)) == fw.DEFAULT_NODE_NAME

    def test_node_name_fallback_without_bot(self):
        class _NoBot:
            platform = "aiocqhttp"
            bot = None

            def get_platform_name(self):
                return self.platform

            def get_self_id(self):
                return "1"

        assert asyncio.run(fw.resolve_node_name(_NoBot())) == fw.DEFAULT_NODE_NAME
