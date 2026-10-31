"""合并转发（聊天记录）工具

QQ（aiocqhttp / OneBot v11 实现，如 NapCat、Lagrange）支持把多条消息合并成
一条「聊天记录」发送。实现方式参考 astrbot_plugin_outputpro 的 ForwardStep：
用 ``Nodes([])`` 收集多个 ``Node(uin, name, content)``，再把整个 Nodes 作为
一条消息发出。

其他平台不支持合并转发，或构建失败时返回 None，由调用方退回逐条发送。
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import Image, Node, Nodes, Plain

# 支持合并转发的平台名（匹配 event.get_platform_name()，忽略大小写）
FORWARD_PLATFORMS: tuple[str, ...] = ("aiocqhttp",)

# 拿不到机器人昵称时的节点显示名
DEFAULT_NODE_NAME = "AstrBot"


def supports_merge_forward(event: Any) -> bool:
    """当前事件所在平台是否支持合并转发"""
    try:
        platform = str(event.get_platform_name() or "").lower()
    except Exception:
        return False
    return any(key in platform for key in FORWARD_PLATFORMS)


def resolve_node_uin(event: Any) -> str:
    """合并转发节点使用的机器人账号（QQ 号），取不到时用 "0" """
    try:
        uin = event.get_self_id()
    except Exception:
        uin = None
    return str(uin or "0")


async def resolve_node_name(event: Any) -> str:
    """机器人昵称（节点显示名）；获取失败时用默认值"""
    bot = getattr(event, "bot", None)
    if bot is not None and hasattr(bot, "get_login_info"):
        try:
            info = await asyncio.wait_for(bot.get_login_info(), timeout=5)
            nickname = str((info or {}).get("nickname") or "").strip()
            if nickname:
                return nickname
        except Exception as exc:
            logger.debug(f"[ReverseSearcher] 获取机器人昵称失败，使用默认节点名: {exc}")
    return DEFAULT_NODE_NAME


async def build_forward_nodes(
    event: Any, messages: list[dict], node_name: str | None = None
) -> Any | None:
    """把 ``[{text, image}]`` 消息列表构造为合并转发节点集

    每个元素生成一个节点：有配图时为「图片 + 文本」，否则仅文本。

    参数:
        event: 消息事件（用于取机器人账号/昵称）
        messages: search_text_messages 返回的消息列表
        node_name: 指定节点显示名；为空时自动获取机器人昵称

    返回:
        Nodes | None: 可直接 ``event.chain_result([nodes])`` 发送的节点集；
        消息为空或构建失败时为 None（调用方应退回逐条发送）
    """
    if not messages:
        return None
    try:
        name = node_name or await resolve_node_name(event)
        uin = resolve_node_uin(event)
        nodes = Nodes([])
        for message in messages:
            content: list[Any] = []
            image = message.get("image")
            if image:
                try:
                    content.append(Image.fromBytes(image))
                except Exception as exc:
                    logger.debug(
                        f"[ReverseSearcher] 合并转发配图构建失败，该条仅发文本: {exc}"
                    )
            content.append(Plain(str(message.get("text") or "")))
            nodes.nodes.append(Node(uin=uin, name=name, content=content))
        return nodes if nodes.nodes else None
    except Exception as exc:
        logger.warning(f"[ReverseSearcher] 合并转发构建失败，退回逐条发送: {exc}")
        return None
