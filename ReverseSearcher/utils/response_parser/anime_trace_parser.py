from typing import Any, NamedTuple

from typing_extensions import override

from .base_parser import BaseResParser, BaseSearchResponse


class Character(NamedTuple):
    """
    角色信息命名元组

    存储识别出的动漫角色名称和作品名
    """

    name: str
    work: str


class AnimeTraceItem(BaseResParser):
    """
    AnimeTrace搜索结果项解析器

    解析单个识别结果，包含角色信息和位置框
    """

    def __init__(self, data: dict[str, Any], **kwargs: Any):
        """
        初始化AnimeTrace结果项解析器

        参数:
            data: 原始结果数据
            **kwargs: 其他解析参数
        """
        super().__init__(data, **kwargs)

    @override
    def _parse_data(self, data: dict[str, Any], **kwargs: Any) -> None:
        """
        解析AnimeTrace结果数据

        参数:
            data: 原始结果数据
            **kwargs: 其他解析参数
        """
        self.box: list[float] = list(data.get("box") or [])
        self.box_id: str = str(data.get("box_id", ""))
        character_data = data.get("character") or []
        self.characters: list[Character] = []
        for char_info in character_data:
            if not isinstance(char_info, dict):
                continue
            character = Character(
                str(char_info.get("character", "")), str(char_info.get("work", ""))
            )
            self.characters.append(character)


class AnimeTraceResponse(BaseSearchResponse[AnimeTraceItem]):
    """
    AnimeTrace搜索响应解析器

    解析完整的AnimeTrace API响应，包含多个识别结果
    """

    def __init__(self, resp_data: dict[str, Any], resp_url: str, **kwargs: Any) -> None:
        """
        初始化AnimeTrace响应解析器

        参数:
            resp_data: 原始响应数据
            resp_url: 响应URL
            **kwargs: 其他解析参数
        """
        super().__init__(resp_data, resp_url, **kwargs)

    @override
    def _parse_response(self, resp_data: dict[str, Any], **kwargs: Any) -> None:
        """
        解析AnimeTrace响应数据

        参数:
            resp_data: 原始响应数据
            **kwargs: 其他解析参数
        """
        self.error: str = ""
        self.code: int = 0
        self.ai: bool | None = None
        self.trace_id: str = ""
        self.raw: list[AnimeTraceItem] = []

        if not isinstance(resp_data, dict):
            self.error = f"AnimeTrace 返回格式异常：{type(resp_data).__name__}"
            return

        self.code = int(resp_data.get("code") or 0)
        self.ai = resp_data.get("ai")  # None 表示未请求 AI 检测
        self.trace_id = resp_data.get("trace_id", "")

        results = resp_data.get("data")
        if not isinstance(results, list):
            # 限流/额度用尽时 data 是 {}，旧实现会把 dict 的键当成结果项解析并抛异常
            message = (
                resp_data.get("zh_message")
                or resp_data.get("message")
                or resp_data.get("msg")
                or ""
            )
            self.error = (
                f"AnimeTrace 返回错误（code={self.code}）：{message}"
                if message
                else f"AnimeTrace 返回格式异常（code={self.code}，缺少 data 列表）"
            )
            return

        parsed: list[AnimeTraceItem] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(AnimeTraceItem(item))
            except Exception:
                continue
        self.raw = parsed

    def item_entries(self) -> list[dict]:
        """按角色拆分文本（文本模式逐条发送）

        AnimeTrace 的一个检测框可能对应多个候选角色，逐个展开；
        每条结果携带检测框，供调用方从源图裁出对应区域作为配图。
        """
        entries: list[dict] = []
        for item in self.raw[:5]:
            for character in item.characters:
                if len(entries) >= 10:
                    return entries
                lines = [f"结果 #{len(entries) + 1}"]
                if character.work:
                    lines.append(f"作品: {character.work}")
                if character.name:
                    lines.append(f"角色: {character.name}")
                entries.append(
                    {
                        "text": "\n".join(lines),
                        "thumbnail": "",
                        "full_image": "",
                        "crop_box": item.box,
                    }
                )
        return entries

    def show_result(self) -> str | None:
        """
        生成可读的搜索结果文本

        返回:
            str: 格式化的搜索结果文本
        """
        has_characters = False
        if self.raw:
            for item in self.raw:
                if item.characters:
                    has_characters = True
                    break
        if not has_characters:
            # 有明确错误（限流/模型不可用等）时优先展示原因
            return getattr(self, "error", "") or None
        lines = []
        if self.ai is not None:
            lines.append(f"是否为 AI 生成: {'是' if self.ai else '否'}")
        else:
            lines.append("是否为 AI 生成: 未检测")
        lines.append("-" * 50)
        if self.raw:
            for _, item in enumerate(self.raw, 1):
                if characters := item.characters:
                    for j, character in enumerate(characters, 1):
                        lines.append(f"结果 #{j}")
                        lines.append(f"作品名: {character.work}")
                        lines.append(f"角色名: {character.name}")
                        lines.append("-" * 50)
        return "\n".join(lines)
