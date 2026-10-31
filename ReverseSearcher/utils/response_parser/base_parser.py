from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class BaseResParser(ABC):
    """
    响应项解析基类

    解析单个搜索结果项的基类，提供通用的属性和解析接口
    """

    def __init__(self, data: Any, **kwargs: Any):
        """
        初始化响应项解析器

        参数:
            data: 原始响应数据
            **kwargs: 其他解析参数
        """
        self.origin: Any = data
        self.url: str = ""
        self.thumbnail: str = ""
        self.title: str = ""
        self.similarity: float = 0.0
        self._parse_data(data, **kwargs)

    @abstractmethod
    def _parse_data(self, data: Any, **kwargs: Any) -> None:
        """
        解析响应数据

        参数:
            data: 原始响应数据
            **kwargs: 其他解析参数

        异常:
            NotImplementedError: 子类必须实现此方法
        """


class BaseSearchResponse(ABC, Generic[T]):
    """
    搜索响应基类

    解析完整搜索响应的基类，包含多个搜索结果项
    """

    raw: list[T]  # 类型声明，不设默认值避免共享

    def __init__(self, resp_data: Any, resp_url: str, **kwargs: Any):
        """
        初始化搜索响应解析器

        参数:
            resp_data: 原始响应数据
            resp_url: 响应URL
            **kwargs: 其他解析参数
        """
        self.origin: Any = resp_data
        self.url: str = resp_url
        self.raw = []  # 实例属性初始化
        self._parse_response(resp_data, resp_url=resp_url, **kwargs)

    @abstractmethod
    def _parse_response(self, resp_data: Any, **kwargs: Any) -> None:
        """
        解析完整响应数据

        参数:
            resp_data: 原始响应数据
            **kwargs: 其他解析参数

        异常:
            NotImplementedError: 子类必须实现此方法
        """

    @abstractmethod
    def show_result(self) -> str | None:
        """
        生成可读的搜索结果文本

        返回:
            Optional[str]: 格式化的搜索结果文本，无结果时返回None

        异常:
            NotImplementedError: 子类必须实现此方法
        """

    # ── 分条输出（文本模式下逐条发送：一条结果 = 文本 + 图片）──────

    @staticmethod
    def _format_similarity(sim: Any) -> str:
        """把相似度格式化为 ``92.5%``；无法格式化时原样返回"""
        if isinstance(sim, (int, float)):
            return f"{sim:.1f}%" if sim > 0 else ""
        return str(sim).strip() if sim else ""

    def item_entries(self) -> list[dict]:
        """按结果条目拆分文本与图片线索（供文本模式逐条发送）

        返回:
            list[dict]: 每项含
                - ``text``: 该条结果的文本
                - ``thumbnail``: 缩略图 URL（可为空）
                - ``crop_box``: 需要从源图裁剪的检测框（AnimeTrace 用，可为 None）

        默认按通用字段（来源/标题/作者/相似度/链接）排版，
        各引擎可覆盖以保留自身字段（如 E-Hentai 标签、AnimeTrace 角色）。
        """
        entries: list[dict] = []
        for idx, item in enumerate(self.raw[:5], 1):
            title = getattr(item, "title", "") or ""
            author = getattr(item, "author", "") or ""
            source = (
                getattr(item, "source", "") or getattr(item, "index_name", "") or ""
            )
            url = getattr(item, "url", "") or ""
            similarity = self._format_similarity(getattr(item, "similarity", 0))

            lines = [f"结果 #{idx}"]
            if source:
                lines.append(f"来源: {source}")
            if title:
                lines.append(f"标题: {title}")
            if author and author != source:
                lines.append(f"作者: {author}")
            if similarity:
                lines.append(f"相似度: {similarity}")
            if url:
                lines.append(f"链接: {url}")
            entries.append(
                {
                    "text": "\n".join(lines),
                    "thumbnail": getattr(item, "thumbnail", "") or "",
                    # 原始大图（支持该字段的引擎才有），供「原图」档位使用
                    "full_image": getattr(item, "full_image", "") or "",
                    "crop_box": None,
                }
            )
        return entries
